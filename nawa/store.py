"""Private, local SQLite persistence for Nawa (Python standard library only).

No task content leaves this machine. JSON imports merge by stable IDs: existing
records are never silently overwritten. Dates are local calendar dates.
"""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid


SCHEMA_VERSION = 2
TASK_FIELDS = {"title", "notes", "due_date", "priority", "status", "list_id",
               "tags", "repeat", "reminder_at"}
TASK_KEYS = TASK_FIELDS | {"id", "created_at", "updated_at", "completed_at",
                          "deleted_at", "subtasks"}


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _id():
    return str(uuid.uuid4())


def _text(value, label, required=False):
    if not isinstance(value, str):
        raise ValueError(f"{label}: expected text")
    if "\x00" in value:
        raise ValueError(f"{label}: NUL characters are not allowed")
    if required and not value.strip():
        raise ValueError(f"{label}: cannot be empty")
    return value.strip() if required else value


def _date(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("due_date must use YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("due_date is not a valid calendar date") from exc
    return value


def _reminder(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
        raise ValueError("reminder_at must use local YYYY-MM-DDTHH:MM")
    try:
        dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("reminder_at is not a valid local date and time") from exc
    return value


def _timestamp(value, label, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}: expected an ISO timestamp")
    try:
        dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}: invalid ISO timestamp") from exc
    return value


def _fields(values):
    unknown = set(values) - TASK_FIELDS
    if unknown:
        raise ValueError("Unknown task fields: " + ", ".join(sorted(unknown)))
    result = dict(values)
    for key in ("title", "notes"):
        if key in result:
            result[key] = _text(result[key], key, key == "title")
    if "due_date" in result:
        result["due_date"] = _date(result["due_date"])
    if "reminder_at" in result:
        result["reminder_at"] = _reminder(result["reminder_at"])
    if "priority" in result and (type(result["priority"]) is not int or result["priority"] not in range(4)):
        raise ValueError("priority must be an integer from 0 to 3")
    if "status" in result and result["status"] not in ("todo", "doing", "done"):
        raise ValueError("status must be todo, doing, or done")
    if "repeat" in result and result["repeat"] not in ("none", "daily", "weekly", "monthly"):
        raise ValueError("repeat must be none, daily, weekly, or monthly")
    if "list_id" in result and result["list_id"] is not None:
        result["list_id"] = _text(result["list_id"], "list_id", True)
    if "tags" in result:
        if not isinstance(result["tags"], list):
            raise ValueError("tags must be a list of strings")
        tags = [_text(tag, "tag", True) for tag in result["tags"]]
        result["tags"] = list(dict.fromkeys(tags))
    return result


def _next_date(day, repeat):
    if repeat == "daily":
        return day + dt.timedelta(days=1)
    if repeat == "weekly":
        return day + dt.timedelta(days=7)
    year, month = day.year, day.month + 1
    if month == 13:
        year, month = year + 1, 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class Store:
    def __init__(self, path=None):
        if path is None:
            path = os.environ.get("NAWA_DB_PATH") or None
        if path is None:
            base = os.environ.get("XDG_DATA_HOME")
            root = Path(base).expanduser() if base and Path(base).is_absolute() else Path.home() / ".local/share"
            directory = root / "nawa"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
            path = directory / "tasks.sqlite3"
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = str(Path(self.path).expanduser())
            # Create privately before SQLite opens the database and sidecars.
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
        self.conn = sqlite3.connect(self.path, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.conn.close()
            raise ValueError("This database was created by a newer version of Nawa")
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS lists (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                    due_date TEXT, priority INTEGER NOT NULL DEFAULT 0 CHECK(priority BETWEEN 0 AND 3),
                    status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done')),
                    list_id TEXT REFERENCES lists(id) ON DELETE SET NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    repeat TEXT NOT NULL DEFAULT 'none' CHECK(repeat IN ('none','daily','weekly','monthly')),
                    reminder_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    completed_at TEXT, deleted_at TEXT, reminded_at TEXT,
                    recurrence_source_id TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS subtasks (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0,1)),
                    position INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS tasks_due ON tasks(deleted_at,status,due_date);
                CREATE INDEX IF NOT EXISTS tasks_list ON tasks(list_id);
                CREATE INDEX IF NOT EXISTS subtasks_task ON subtasks(task_id,position);
            """)
            from .finance_store import initialize
            initialize(self.conn)
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        from .finance_store import FinanceStore
        self.finance = FinanceStore(self)

    def close(self):
        self.conn.close()

    def _task(self, row):
        if row is None:
            return None
        task = {key: row[key] for key in TASK_KEYS if key != "subtasks"}
        task["tags"] = json.loads(task["tags"])
        task["subtasks"] = [{"id": sub["id"], "title": sub["title"], "done": bool(sub["done"])}
                            for sub in self.conn.execute(
                                "SELECT * FROM subtasks WHERE task_id=? ORDER BY position,id", (task["id"],))]
        return task

    def get_task(self, task_id):
        return self._task(self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def _require(self, task_id):
        task = self.get_task(task_id)
        if task is None:
            raise ValueError("Task does not exist")
        return task

    def _check_list(self, list_id):
        if list_id is not None and not self.conn.execute("SELECT 1 FROM lists WHERE id=?", (list_id,)).fetchone():
            raise ValueError("List does not exist")

    def _insert(self, task, recurrence_source_id=None):
        values = {key: value for key, value in task.items() if key != "subtasks"}
        values["tags"] = json.dumps(values["tags"], ensure_ascii=False)
        values["recurrence_source_id"] = recurrence_source_id
        columns = list(values)
        self.conn.execute("INSERT INTO tasks (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")",
                          [values[key] for key in columns])
        for position, sub in enumerate(task["subtasks"]):
            self.conn.execute("INSERT INTO subtasks(id,task_id,title,done,position) VALUES(?,?,?,?,?)",
                              (sub["id"], task["id"], sub["title"], int(sub["done"]), position))

    def create_task(self, title, **fields):
        fields["title"] = title
        values = _fields(fields)
        timestamp = _now()
        task = dict(id=_id(), title="", notes="", due_date=None, priority=0, status="todo",
                    list_id=None, tags=[], repeat="none", reminder_at=None,
                    created_at=timestamp, updated_at=timestamp, completed_at=None,
                    deleted_at=None, subtasks=[])
        task.update(values)
        if task["status"] == "done":
            task["completed_at"] = timestamp
        with self.conn:
            self._check_list(task["list_id"])
            self._insert(task)
        return self.get_task(task["id"])

    def update_task(self, task_id, **fields):
        values = _fields(fields)
        with self.conn:
            self._update_task(task_id, values)
        return self.get_task(task_id)

    def _update_task(self, task_id, values):
        """Update inside the caller's transaction, including repeat generation."""
        values = dict(values)
        previous = self._require(task_id)
        if "list_id" in values:
            self._check_list(values["list_id"])
        if "tags" in values:
            values["tags"] = json.dumps(values["tags"], ensure_ascii=False)
        if "status" in values:
            values["completed_at"] = (previous["completed_at"] or _now()) if values["status"] == "done" else None
        if "reminder_at" in values and values["reminder_at"] != previous["reminder_at"]:
            values["reminded_at"] = None
        values["updated_at"] = _now()
        self.conn.execute("UPDATE tasks SET " + ",".join(key + "=?" for key in values) + " WHERE id=?",
                          [*values.values(), task_id])
        if values.get("status") == "done" and previous["status"] != "done" and not previous["deleted_at"]:
            self._repeat(self._require(task_id))

    def save_task_details(self, task_id, fields, subtasks):
        """Save one editor dialog atomically; None creates a new parent task.

        The supplied subtask array is the complete desired list. Existing IDs
        must belong to this parent; None or missing IDs create new subtasks.
        Repeat generation happens after the final edited subtasks are stored.
        """
        if not isinstance(fields, dict) or not isinstance(subtasks, list):
            raise ValueError("Expected task fields and a subtask list")
        values = _fields(fields)
        if task_id is None and "title" not in values:
            raise ValueError("title cannot be empty")
        normalized, seen = [], set()
        for sub in subtasks:
            if not isinstance(sub, dict) or type(sub.get("done", False)) is not bool:
                raise ValueError("Invalid subtask record")
            sub_id = sub.get("id")
            sub_id = _id() if sub_id is None else _text(sub_id, "Subtask ID", True)
            if sub_id in seen:
                raise ValueError("Duplicate subtask ID")
            seen.add(sub_id)
            normalized.append(dict(id=sub_id, title=_text(sub.get("title"), "Subtask title", True),
                                   done=sub.get("done", False)))
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            creating = task_id is None
            if creating:
                task_id = _id()
            else:
                self._require(task_id)
            self._check_list(values.get("list_id"))
            for sub in normalized:
                owner = self.conn.execute("SELECT task_id FROM subtasks WHERE id=?", (sub["id"],)).fetchone()
                if owner and owner["task_id"] != task_id:
                    raise ValueError("A subtask ID belongs to a different task")
            if creating:
                timestamp = _now()
                task = dict(id=task_id, title="", notes="", due_date=None, priority=0, status="todo",
                            list_id=None, tags=[], repeat="none", reminder_at=None,
                            created_at=timestamp, updated_at=timestamp, completed_at=None,
                            deleted_at=None, subtasks=normalized)
                task.update(values)
                if task["status"] == "done":
                    task["completed_at"] = timestamp
                self._insert(task)
                if task["status"] == "done":
                    self._repeat(task)
            else:
                self.conn.execute("DELETE FROM subtasks WHERE task_id=?", (task_id,))
                for position, sub in enumerate(normalized):
                    self.conn.execute("INSERT INTO subtasks(id,task_id,title,done,position) VALUES(?,?,?,?,?)",
                                      (sub["id"], task_id, sub["title"], int(sub["done"]), position))
                self._update_task(task_id, values)
        return self.get_task(task_id)

    def _repeat(self, task):
        if task["repeat"] == "none" or self.conn.execute(
                "SELECT 1 FROM tasks WHERE recurrence_source_id=?", (task["id"],)).fetchone():
            return
        base = dt.date.fromisoformat(task["due_date"]) if task["due_date"] else dt.date.today()
        due = _next_date(base, task["repeat"])
        timestamp = _now()
        copied = dict(task, id=_id(), status="todo", due_date=due.isoformat(), completed_at=None,
                      created_at=timestamp, updated_at=timestamp, deleted_at=None,
                      subtasks=[dict(id=_id(), title=sub["title"], done=False) for sub in task["subtasks"]])
        if task["reminder_at"]:
            reminder = dt.datetime.fromisoformat(task["reminder_at"])
            copied["reminder_at"] = (reminder + (due - base)).isoformat(timespec="minutes")
        self._insert(copied, recurrence_source_id=task["id"])

    def complete_task(self, task_id, done=True):
        if type(done) is not bool:
            raise ValueError("done must be a boolean")
        return self.update_task(task_id, status="done" if done else "todo")

    def list_tasks(self, view="all", list_id=None, search="", sort="smart"):
        today = dt.date.today().isoformat()
        week = (dt.date.today() + dt.timedelta(days=7)).isoformat()
        clauses = {
            "all": ("deleted_at IS NULL AND status!='done'", []),
            "today": ("deleted_at IS NULL AND status!='done' AND due_date<=?", [today]),
            "upcoming": ("deleted_at IS NULL AND status!='done' AND due_date>? AND due_date<=?", [today, week]),
            "done": ("deleted_at IS NULL AND status='done'", []),
            "trash": ("deleted_at IS NOT NULL", []),
        }
        if view not in clauses:
            raise ValueError("Unknown task view")
        sorts = {
            "smart": "CASE WHEN due_date IS NOT NULL AND due_date<=date('now','localtime') THEN 0 ELSE 1 END, priority DESC, due_date IS NULL, due_date, created_at DESC, id",
            "due": "due_date IS NULL, due_date, priority DESC, id",
            "title": "title COLLATE NOCASE, id",
            "created": "created_at DESC, id",
            "priority": "priority DESC, due_date IS NULL, due_date, id",
        }
        if sort not in sorts:
            raise ValueError("Unknown sort order")
        where, args = clauses[view]
        if list_id is not None:
            where += " AND list_id=?"
            args.append(list_id)
        # Casefold in Python gives correct Unicode behavior and literal %, _ and
        # backslash searches; SQL LIKE would interpret those as wildcards.
        query = _text(search, "search").strip().casefold()
        tasks = [self._task(row) for row in self.conn.execute("SELECT * FROM tasks WHERE " + where + " ORDER BY " + sorts[sort], args)]
        if query:
            tasks = [task for task in tasks if query in "\n".join(
                [task["title"], task["notes"], *task["tags"], *[sub["title"] for sub in task["subtasks"]]]).casefold()]
        return tasks

    def trash_task(self, task_id):
        with self.conn:
            task = self._require(task_id)
            if not task["deleted_at"]:
                self.conn.execute("UPDATE tasks SET deleted_at=?,updated_at=? WHERE id=?", (_now(), _now(), task_id))
        return self.get_task(task_id)

    def restore_task(self, task_id):
        with self.conn:
            self._require(task_id)
            self.conn.execute("UPDATE tasks SET deleted_at=NULL,updated_at=? WHERE id=?", (_now(), task_id))
        return self.get_task(task_id)

    def purge_trash(self):
        with self.conn:
            cursor = self.conn.execute("DELETE FROM tasks WHERE deleted_at IS NOT NULL")
        return cursor.rowcount

    def list_lists(self):
        return [dict(row) for row in self.conn.execute("""
            SELECT l.id,l.name,l.color,COUNT(t.id) AS count FROM lists l LEFT JOIN tasks t
            ON t.list_id=l.id AND t.deleted_at IS NULL AND t.status!='done'
            GROUP BY l.id ORDER BY l.name COLLATE NOCASE,l.id
        """)]

    def create_list(self, name, color="#648977"):
        name = _text(name, "List name", True)
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("List color must be #RRGGBB")
        result = dict(id=_id(), name=name, color=color)
        with self.conn:
            self.conn.execute("INSERT INTO lists(id,name,color) VALUES(?,?,?)", (result["id"], name, color))
        return dict(result, count=0)

    def delete_list(self, list_id):
        with self.conn:
            self.conn.execute("UPDATE tasks SET list_id=NULL,updated_at=? WHERE list_id=?", (_now(), list_id))
            self.conn.execute("DELETE FROM lists WHERE id=?", (list_id,))

    def add_subtask(self, task_id, title):
        title = _text(title, "Subtask title", True)
        subtask_id = _id()
        with self.conn:
            self._require(task_id)
            position = self.conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM subtasks WHERE task_id=?", (task_id,)).fetchone()[0]
            self.conn.execute("INSERT INTO subtasks(id,task_id,title,position) VALUES(?,?,?,?)", (subtask_id, task_id, title, position))
            self.conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (_now(), task_id))
        return dict(id=subtask_id, title=title, done=False)

    def toggle_subtask(self, subtask_id, done):
        if type(done) is not bool:
            raise ValueError("done must be a boolean")
        with self.conn:
            row = self.conn.execute("SELECT task_id FROM subtasks WHERE id=?", (subtask_id,)).fetchone()
            if row is None:
                raise ValueError("Subtask does not exist")
            self.conn.execute("UPDATE subtasks SET done=? WHERE id=?", (int(done), subtask_id))
            self.conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (_now(), row["task_id"]))
        return self.get_task(row["task_id"])

    def delete_subtask(self, subtask_id):
        with self.conn:
            row = self.conn.execute("SELECT task_id FROM subtasks WHERE id=?", (subtask_id,)).fetchone()
            if row:
                self.conn.execute("DELETE FROM subtasks WHERE id=?", (subtask_id,))
                self.conn.execute("UPDATE tasks SET updated_at=? WHERE id=?", (_now(), row["task_id"]))

    def stats(self):
        result = {view: len(self.list_tasks(view)) for view in ("all", "today", "upcoming", "done", "trash")}
        today = dt.date.today().isoformat()
        result["overdue"] = self.conn.execute("SELECT COUNT(*) FROM tasks WHERE deleted_at IS NULL AND status!='done' AND due_date<?", (today,)).fetchone()[0]
        return result

    def due_reminders(self, now=None):
        if now is None:
            now = dt.datetime.now()
        if isinstance(now, str):
            now = dt.datetime.fromisoformat(now)
        if not isinstance(now, dt.datetime):
            raise ValueError("now must be a datetime or ISO timestamp")
        if now.tzinfo is not None:
            now = now.astimezone().replace(tzinfo=None)
        return [self._task(row) for row in self.conn.execute("""
            SELECT * FROM tasks WHERE deleted_at IS NULL AND status!='done'
            AND reminder_at IS NOT NULL AND reminder_at<=?
            AND (reminded_at IS NULL OR reminded_at!=reminder_at) ORDER BY reminder_at,id
        """, (now.isoformat(timespec="minutes"),))]

    def mark_reminded(self, task_id):
        with self.conn:
            self._require(task_id)
            self.conn.execute("UPDATE tasks SET reminded_at=reminder_at WHERE id=?", (task_id,))

    def _guard_output(self, path):
        if self.path == ":memory:":
            return
        target = Path(path).expanduser().resolve()
        live = Path(self.path).resolve()
        protected = {live, Path(str(live) + "-wal"), Path(str(live) + "-shm"), Path(str(live) + "-journal")}
        if target in protected:
            raise ValueError("Choose an output path different from the live database and its sidecar files")
        # Hard links resolve to different names but can still identify live data.
        if target.exists():
            for entry in protected:
                if entry.exists() and os.path.samefile(target, entry):
                    raise ValueError("Output path refers to the live database or its sidecar files")

    def _write_atomic(self, path, callback):
        self._guard_output(path)
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".nawa-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                callback(handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def export_json(self, path):
        with self.conn:
            # BEGIN gives all export queries one coherent read snapshot.
            self.conn.execute("BEGIN")
            payload = dict(format="nawa", schema_version=SCHEMA_VERSION, exported_at=_now(),
                           lists=[{k: row[k] for k in ("id", "name", "color")} for row in self.conn.execute("SELECT * FROM lists ORDER BY id")],
                           tasks=[self._task(row) for row in self.conn.execute("SELECT * FROM tasks ORDER BY id")],
                           recurrence_links=[dict(id=row["id"], source_id=row["recurrence_source_id"])
                                             for row in self.conn.execute("SELECT id,recurrence_source_id FROM tasks WHERE recurrence_source_id IS NOT NULL")],
                           finance=self.finance.dump())
        self._write_atomic(path, lambda handle: json.dump(payload, handle, ensure_ascii=False, indent=2))
        return {"tasks": len(payload["tasks"]), "lists": len(payload["lists"])}

    def _validate_import(self, data):
        if not isinstance(data, dict) or data.get("format") != "nawa" or data.get("schema_version") not in (1, SCHEMA_VERSION):
            raise ValueError("Expected a Nawa JSON backup with schema_version 1 or 2")
        if not isinstance(data.get("tasks"), list) or not isinstance(data.get("lists"), list):
            raise ValueError("Backup tasks and lists must be arrays")
        lists, tasks, seen_lists, seen_tasks, seen_subs = [], [], set(), set(), set()
        for item in data["lists"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid list record")
            record = {key: _text(item.get(key), key, True) for key in ("id", "name", "color")}
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", record["color"]):
                raise ValueError("Invalid list color")
            if record["id"] in seen_lists:
                raise ValueError("Duplicate list ID in backup")
            seen_lists.add(record["id"])
            lists.append(record)
        existing_lists = {row[0] for row in self.conn.execute("SELECT id FROM lists")}
        for item in data["tasks"]:
            if not isinstance(item, dict) or not TASK_KEYS.issubset(item):
                raise ValueError("Task record is missing required fields")
            record = _fields({key: item[key] for key in TASK_FIELDS})
            record["id"] = _text(item["id"], "Task ID", True)
            if record["id"] in seen_tasks:
                raise ValueError("Duplicate task ID in backup")
            seen_tasks.add(record["id"])
            if record["list_id"] is not None and record["list_id"] not in seen_lists | existing_lists:
                raise ValueError("Task references a missing list")
            for key in ("created_at", "updated_at", "completed_at", "deleted_at"):
                record[key] = _timestamp(item[key], key, key in ("completed_at", "deleted_at"))
            if (record["status"] == "done") != (record["completed_at"] is not None):
                raise ValueError("Task completion timestamp does not match status")
            if not isinstance(item["subtasks"], list):
                raise ValueError("Subtasks must be an array")
            record["subtasks"] = []
            for sub in item["subtasks"]:
                if not isinstance(sub, dict) or type(sub.get("done")) is not bool:
                    raise ValueError("Invalid subtask record")
                normalized = dict(id=_text(sub.get("id"), "Subtask ID", True),
                                  title=_text(sub.get("title"), "Subtask title", True), done=sub["done"])
                if normalized["id"] in seen_subs:
                    raise ValueError("Duplicate subtask ID in backup")
                seen_subs.add(normalized["id"])
                record["subtasks"].append(normalized)
            tasks.append(record)
        links = data.get("recurrence_links", [])
        if not isinstance(links, list):
            raise ValueError("Invalid recurrence links")
        link_map, sources = {}, set()
        for item in links:
            if not isinstance(item, dict):
                raise ValueError("Invalid recurrence link")
            child = _text(item.get("id"), "Recurrence task ID", True)
            source = _text(item.get("source_id"), "Recurrence source ID", True)
            if child not in seen_tasks or child == source or child in link_map or source in sources:
                raise ValueError("Invalid or duplicate recurrence link")
            link_map[child] = source
            sources.add(source)
        return lists, tasks, link_map

    def import_json(self, path):
        try:
            with Path(path).expanduser().open(encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("Cannot read backup: invalid JSON or text encoding") from exc
        result = dict(imported=0, skipped=0, conflicts=0, lists_imported=0)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            lists, tasks, links = self._validate_import(data)
            financial = self.finance.validate_dump(data.get('finance')) if data['schema_version'] >= 2 else ([], [])
            for item in lists:
                existing = self.conn.execute("SELECT * FROM lists WHERE id=?", (item["id"],)).fetchone()
                if existing:
                    if dict(existing) != item:
                        result["conflicts"] += 1
                else:
                    self.conn.execute("INSERT INTO lists(id,name,color) VALUES(?,?,?)", (item["id"], item["name"], item["color"]))
                    result["lists_imported"] += 1
            for task in tasks:
                existing = self.get_task(task["id"])
                if existing:
                    result["skipped"] += 1
                    if existing != task:
                        result["conflicts"] += 1
                    continue
                # Global subtask UUID conflicts must not modify another task.
                if any(self.conn.execute("SELECT 1 FROM subtasks WHERE id=?", (sub["id"],)).fetchone() for sub in task["subtasks"]):
                    raise ValueError("A subtask ID belongs to a different existing task")
                source = links.get(task["id"])
                if source and self.conn.execute("SELECT 1 FROM tasks WHERE recurrence_source_id=?", (source,)).fetchone():
                    result["conflicts"] += 1
                    result["skipped"] += 1
                    continue
                self._insert(task, source)
                result["imported"] += 1
            financial_result = self.finance.merge(financial)
            if financial[0] or financial[1]:
                result.update(financial_result)
        return result

    def export_csv(self, path):
        rows = [self._task(row) for row in self.conn.execute("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY created_at,id")]
        def write(handle):
            writer = csv.writer(handle)
            writer.writerow(["Name", "Status", "Due date", "Priority", "Tags", "Notes"])
            for task in rows:
                writer.writerow([task["title"], task["status"], task["due_date"] or "", task["priority"],
                                 json.dumps(task["tags"], ensure_ascii=False), task["notes"]])
        self._write_atomic(path, write)
        return {"tasks": len(rows)}

    def import_csv(self, path):
        aliases = {"name": "title", "title": "title", "task": "title", "الاسم": "title", "المهمة": "title", "العنوان": "title",
                   "status": "status", "الحالة": "status", "due date": "due_date", "due_date": "due_date", "date": "due_date", "التاريخ": "due_date", "تاريخ الاستحقاق": "due_date",
                   "priority": "priority", "الأولوية": "priority", "الاولوية": "priority", "tags": "tags", "الوسوم": "tags",
                   "notes": "notes", "الملاحظات": "notes"}
        statuses = {"todo": "todo", "not started": "todo", "to do": "todo", "لم تبدأ": "todo", "قيد الانتظار": "todo",
                    "doing": "doing", "in progress": "doing", "قيد التنفيذ": "doing", "done": "done", "complete": "done", "completed": "done", "مكتملة": "done", "مكتمل": "done"}
        priorities = {"": 0, "none": 0, "لا شيء": 0, "low": 1, "منخفضة": 1, "medium": 2, "متوسطة": 2, "high": 3, "عالية": 3}
        prepared = []
        try:
            with Path(path).expanduser().open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise ValueError("CSV file is empty")
                mapped = {key: aliases.get(key.strip().casefold()) for key in reader.fieldnames}
                if "title" not in mapped.values():
                    raise ValueError("CSV needs a Name or title column")
                for number, row in enumerate(reader, 2):
                    if None in row:
                        raise ValueError(f"CSV row {number}: too many columns")
                    values = {target: (row[source] or "").strip() for source, target in mapped.items() if target}
                    if not any(values.values()):
                        continue
                    try:
                        values["status"] = statuses.get(values.get("status", "").casefold() or "todo")
                        if values["status"] is None:
                            raise ValueError("unknown status")
                        raw_priority = values.get("priority", "").casefold()
                        values["priority"] = int(raw_priority) if raw_priority.isdigit() else priorities.get(raw_priority)
                        raw_tags = values.get("tags", "")
                        if raw_tags.startswith("["):
                            values["tags"] = json.loads(raw_tags)
                        else:
                            values["tags"] = [tag.strip() for tag in re.split(r"[,;،]", raw_tags) if tag.strip()]
                        prepared.append(_fields(values))
                    except (ValueError, TypeError) as exc:
                        raise ValueError(f"CSV row {number}: {exc}") from exc
        except UnicodeError as exc:
            raise ValueError("CSV must use UTF-8 encoding") from exc
        result = dict(imported=0, skipped=0, conflicts=0, lists_imported=0)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            for values in prepared:
                # CSV has no stable IDs. Skip identical content to make repeat imports safe.
                candidates = self.conn.execute("SELECT * FROM tasks WHERE title=? AND deleted_at IS NULL", (values["title"],)).fetchall()
                normalized = dict(notes="", due_date=None, priority=0, status="todo", list_id=None,
                                  tags=[], repeat="none", reminder_at=None, **{"title": values["title"]})
                normalized.update(values)
                if any(all(self._task(row)[key] == value for key, value in normalized.items()) for row in candidates):
                    result["skipped"] += 1
                    continue
                timestamp = _now()
                task = dict(normalized, id=_id(), created_at=timestamp, updated_at=timestamp,
                            completed_at=timestamp if normalized["status"] == "done" else None,
                            deleted_at=None, subtasks=[])
                self._insert(task)
                result["imported"] += 1
        return result

    def backup(self, path):
        self._guard_output(path)
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".nawa-backup-", dir=target.parent)
        os.close(fd)
        try:
            destination = sqlite3.connect(temporary)
            try:
                self.conn.backup(destination)
                destination.execute("PRAGMA journal_mode=DELETE")
            finally:
                destination.close()
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return str(target)
