"""Behavior tests for Nawa's local data contract; run python3 -m unittest test_store."""
import csv
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from nawa.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.path = self.directory / "tasks.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_unicode_and_injection_are_literal_and_persistent(self):
        title = "مهمة '); DROP TABLE tasks; -- 🍊"
        task = self.store.create_task(title, notes="تفاصيل\nسطر ثانٍ", tags=["شخصي", "عمل", "شخصي"])
        self.store.close()
        self.store = Store(self.path)
        loaded = self.store.get_task(task["id"])
        self.assertEqual(loaded["title"], title)
        self.assertEqual(loaded["tags"], ["شخصي", "عمل"])
        self.assertEqual(len(self.store.list_tasks()), 1)
        if sys.platform != 'win32':
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_date_and_field_validation_does_not_write(self):
        cases = [dict(title=" "), dict(title="a", due_date="2025-02-29"),
                 dict(title="a", due_date="2026-1-1"), dict(title="a", priority=True),
                 dict(title="a", priority=4), dict(title="a", status="unknown"),
                 dict(title="a", reminder_at="2026-10-22T25:00"),
                 dict(title="a", tags="tag"), dict(title="a", list_id="missing"),
                 dict(title="a", other="bad"), dict(title="a\x00b")]
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.create_task(**fields)
        self.assertEqual(self.store.list_tasks(), [])
        self.assertIsNotNone(self.store.create_task("leap", due_date="2028-02-29"))

    def test_lists_rehome_all_tasks_including_trash(self):
        group = self.store.create_list("المنزل")
        first = self.store.create_task("شراء", list_id=group["id"])
        other = self.store.create_task("اتصال", list_id=group["id"])
        self.store.trash_task(other["id"])
        self.assertEqual(self.store.list_lists()[0]["count"], 1)
        self.store.delete_list(group["id"])
        self.assertEqual(self.store.list_lists(), [])
        self.assertIsNone(self.store.get_task(first["id"])["list_id"])
        self.assertIsNone(self.store.get_task(other["id"])["list_id"])

    def test_views_and_stats_have_disjoint_upcoming_and_today(self):
        today = dt.date.today()
        for label, delta in (("yesterday", -1), ("today", 0), ("tomorrow", 1), ("week", 7), ("later", 8)):
            self.store.create_task(label, due_date=(today + dt.timedelta(days=delta)).isoformat())
        self.store.create_task("undated")
        done = self.store.create_task("done", status="done", due_date=today.isoformat())
        trash = self.store.create_task("trash", due_date=today.isoformat())
        self.store.trash_task(trash["id"])
        self.assertEqual({t["title"] for t in self.store.list_tasks("today")}, {"yesterday", "today"})
        self.assertEqual({t["title"] for t in self.store.list_tasks("upcoming")}, {"tomorrow", "week"})
        self.assertEqual(self.store.stats(), dict(all=6, today=2, upcoming=2, done=1, overdue=1, trash=1))
        self.assertEqual(self.store.list_tasks("done")[0]["id"], done["id"])

    def test_search_is_unicode_casefolded_and_wildcards_are_literal(self):
        first = self.store.create_task("100% complete", notes="AbC", tags=["أعمال"])
        second = self.store.create_task("under_score")
        self.store.add_subtask(second["id"], "Straße")
        self.assertEqual([t["id"] for t in self.store.list_tasks(search="%")], [first["id"]])
        self.assertEqual([t["id"] for t in self.store.list_tasks(search="_")], [second["id"]])
        self.assertEqual([t["id"] for t in self.store.list_tasks(search="ABC")], [first["id"]])
        self.assertEqual([t["id"] for t in self.store.list_tasks(search="STRASSE")], [second["id"]])
        self.assertEqual(self.store.list_tasks(search="' OR 1=1 --"), [])

    def test_subtasks_toggle_cascade_and_trash_restore(self):
        task = self.store.create_task("parent")
        sub = self.store.add_subtask(task["id"], "child")
        self.assertTrue(self.store.toggle_subtask(sub["id"], True)["subtasks"][0]["done"])
        self.store.trash_task(task["id"])
        self.assertEqual(self.store.list_tasks(), [])
        self.store.restore_task(task["id"])
        self.assertEqual(self.store.list_tasks()[0]["id"], task["id"])
        self.store.trash_task(task["id"])
        self.assertEqual(self.store.purge_trash(), 1)
        self.assertIsNone(self.store.get_task(task["id"]))
        with self.assertRaises(ValueError):
            self.store.toggle_subtask(sub["id"], False)

    def test_delete_subtask(self):
        task = self.store.create_task("parent")
        sub = self.store.add_subtask(task["id"], "child")
        self.store.delete_subtask(sub["id"])
        self.assertEqual(self.store.get_task(task["id"])["subtasks"], [])

    def test_editor_save_validation_is_atomic(self):
        task = self.store.create_task("original")
        sub = self.store.add_subtask(task["id"], "original step")
        other = self.store.create_task("other")
        alien = self.store.add_subtask(other["id"], "alien")
        before = self.store.get_task(task["id"])
        with self.assertRaises(ValueError):
            self.store.save_task_details(task["id"], {"title": "changed"}, [dict(id=sub["id"], title=" ", done=False)])
        self.assertEqual(self.store.get_task(task["id"]), before)
        with self.assertRaises(ValueError):
            self.store.save_task_details(task["id"], {"title": "changed"}, [alien])
        self.assertEqual(self.store.get_task(task["id"]), before)
        with self.assertRaises(ValueError):
            self.store.save_task_details(task["id"], {"title": "changed", "list_id": "missing"}, [])
        self.assertEqual(self.store.get_task(task["id"]), before)
        saved = self.store.save_task_details(task["id"], {"title": "saved"}, [dict(id=None, title="replacement", done=True)])
        self.assertEqual(saved["title"], "saved")
        self.assertEqual(len(saved["subtasks"]), 1)
        self.assertEqual(saved["subtasks"][0]["title"], "replacement")
        self.assertTrue(saved["subtasks"][0]["done"])

    def test_editor_completion_recurrence_uses_final_edited_subtasks(self):
        task = self.store.save_task_details(None, {"title": "monthly", "repeat": "monthly", "due_date": "2027-01-31"},
                                            [dict(title="old", done=False)])
        sub = task["subtasks"][0]
        self.store.save_task_details(task["id"], {"status": "done", "title": "updated"},
                                     [dict(sub, title="edited", done=True), dict(id=None, title="new", done=True)])
        successor = self.store.list_tasks()[0]
        self.assertEqual(successor["due_date"], "2027-02-28")
        self.assertEqual(successor["title"], "updated")
        self.assertEqual([s["title"] for s in successor["subtasks"]], ["edited", "new"])
        self.assertEqual([s["done"] for s in successor["subtasks"]], [False, False])

    def test_monthly_recurrence_clamps_and_does_not_duplicate_on_toggle(self):
        task = self.store.create_task("monthly", due_date="2028-01-31", repeat="monthly", reminder_at="2028-01-31T09:30")
        self.store.add_subtask(task["id"], "reset me")
        self.store.complete_task(task["id"])
        generated = self.store.list_tasks()[0]
        self.assertEqual(generated["due_date"], "2028-02-29")
        self.assertEqual(generated["reminder_at"], "2028-02-29T09:30")
        self.assertFalse(generated["subtasks"][0]["done"])
        self.store.complete_task(task["id"], False)
        self.store.complete_task(task["id"])
        self.assertEqual(len(self.store.list_tasks()), 1)
        self.assertEqual(self.store.list_tasks()[0]["id"], generated["id"])
        self.store.complete_task(generated["id"])
        self.assertEqual(self.store.list_tasks()[0]["due_date"], "2028-03-29")

    def test_daily_and_weekly_recurrence_without_due(self):
        for repeat, delta in (("daily", 1), ("weekly", 7)):
            task = self.store.create_task(repeat, repeat=repeat)
            self.store.complete_task(task["id"])
            active = next(t for t in self.store.list_tasks() if t["title"] == repeat)
            self.assertEqual(active["due_date"], (dt.date.today() + dt.timedelta(days=delta)).isoformat())

    def test_json_roundtrip_idempotence_and_conflicts_preserve_live_data(self):
        group = self.store.create_list("عائلة")
        task = self.store.create_task("original", list_id=group["id"], repeat="daily", due_date="2026-10-20")
        self.store.add_subtask(task["id"], "subtask")
        self.store.complete_task(task["id"])
        backup = self.directory / "backup.json"
        self.store.export_json(backup)
        other = Store(self.directory / "other.db")
        try:
            first = other.import_json(backup)
            self.assertEqual(first["imported"], 2)
            self.assertEqual(first["lists_imported"], 1)
            self.assertEqual(other.import_json(backup), dict(imported=0, skipped=2, conflicts=0, lists_imported=0))
            other.update_task(task["id"], title="local edit")
            report = other.import_json(backup)
            self.assertEqual(report["conflicts"], 1)
            self.assertEqual(other.get_task(task["id"])["title"], "local edit")
            other.complete_task(task["id"], False)
            other.complete_task(task["id"])
            self.assertEqual(len(other.list_tasks()), 1)
        finally:
            other.close()

    def test_malformed_json_rolls_back_entire_import(self):
        self.store.create_task("keep")
        backup = self.directory / "bad.json"
        self.store.export_json(backup)
        payload = json.loads(backup.read_text(encoding='utf-8'))
        payload["lists"].append(dict(id="newlist", name="new", color="#aabbcc"))
        payload["tasks"].append(dict(payload["tasks"][0], id="newtask", due_date="2026-02-30"))
        backup.write_text(json.dumps(payload))
        with self.assertRaises(ValueError):
            self.store.import_json(backup)
        self.assertEqual(len(self.store.list_tasks()), 1)
        self.assertEqual(self.store.list_lists(), [])

    def test_json_import_rolls_back_on_existing_subtask_collision(self):
        task = self.store.create_task("keep")
        self.store.add_subtask(task["id"], "sub")
        backup = self.directory / "collision.json"
        self.store.export_json(backup)
        payload = json.loads(backup.read_text(encoding='utf-8'))
        one = dict(payload["tasks"][0], id="first", subtasks=[])
        two = dict(payload["tasks"][0], id="second")
        payload["tasks"] = [one, two]
        backup.write_text(json.dumps(payload))
        with self.assertRaises(ValueError):
            self.store.import_json(backup)
        self.assertIsNone(self.store.get_task("first"))
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_csv_roundtrip_unicode_quotes_tags_and_repeat_import(self):
        self.store.create_task('شراء "أغراض", اليوم', notes="line one\nسطر ثان", tags=["a,b", "عائلة"], priority=3, status="doing", due_date="2026-12-31")
        target = self.directory / "tasks.csv"
        self.store.export_csv(target)
        other = Store(":memory:")
        try:
            self.assertEqual(other.import_csv(target)["imported"], 1)
            self.assertEqual(other.import_csv(target)["skipped"], 1)
            task = other.list_tasks()[0]
            self.assertEqual(task["tags"], ["a,b", "عائلة"])
            self.assertEqual(task["status"], "doing")
            self.assertEqual(task["priority"], 3)
        finally:
            other.close()

    def test_notion_csv_and_bad_row_transaction(self):
        target = self.directory / "notion.csv"
        target.write_text("Name,Status,Due date,Priority,Tags,Notes\nWrite,In progress,2026-12-31,High,work,hello\n", encoding="utf-8")
        self.assertEqual(self.store.import_csv(target)["imported"], 1)
        task = self.store.list_tasks()[0]
        self.assertEqual((task["status"], task["priority"]), ("doing", 3))
        target.write_text("Name,Due date\nvalid,2026-01-01\nbad,not a date\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "CSV row 3"):
            self.store.import_csv(target)
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_arabic_csv_columns(self):
        target = self.directory / "arabic.csv"
        target.write_text("المهمة,الحالة,تاريخ الاستحقاق,الأولوية,الوسوم\nدراسة,مكتملة,2026-10-22,عالية,مدرسة\n", encoding="utf-8-sig")
        self.assertEqual(self.store.import_csv(target)["imported"], 1)
        self.assertEqual(self.store.list_tasks("done")[0]["title"], "دراسة")

    def test_reminders_persist_once_per_schedule_and_skip_done_trash(self):
        task = self.store.create_task("notify", reminder_at="2026-10-22T09:00")
        done = self.store.create_task("done", status="done", reminder_at="2026-10-22T09:00")
        trash = self.store.create_task("trash", reminder_at="2026-10-22T09:00")
        self.store.trash_task(trash["id"])
        self.assertEqual(self.store.due_reminders("2026-10-22T08:59"), [])
        self.assertEqual([t["id"] for t in self.store.due_reminders("2026-10-22T09:00")], [task["id"]])
        self.store.mark_reminded(task["id"])
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.due_reminders("2026-10-22T12:00"), [])
        self.store.update_task(task["id"], reminder_at="2026-10-22T10:00")
        self.assertEqual(len(self.store.due_reminders("2026-10-22T12:00")), 1)

    def test_sqlite_backup_includes_live_wal(self):
        task = self.store.create_task("live WAL")
        self.store.add_subtask(task["id"], "also backed up")
        snapshot = self.directory / "backup.sqlite3"
        self.store.backup(snapshot)
        other = Store(snapshot)
        try:
            self.assertEqual(other.get_task(task["id"])["subtasks"][0]["title"], "also backed up")
            self.assertEqual(other.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.store.update_task(task["id"], title="changed after snapshot")
            self.assertEqual(other.get_task(task["id"])["title"], "live WAL")
        finally:
            other.close()
        with self.assertRaises(ValueError):
            self.store.backup(self.path)

    def test_all_exports_protect_database_sidecars_and_aliases(self):
        task = self.store.create_task("keep my data")
        paths = [self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"), Path(str(self.path) + "-journal")]
        link = self.directory / "db-link"
        try:
            link.symlink_to(self.path)
        except OSError:
            if sys.platform != 'win32': raise
        else:
            paths.append(link)
        hardlink = self.directory / "db-hardlink"
        os.link(self.path, hardlink)
        paths.append(hardlink)
        for method in (self.store.export_json, self.store.export_csv, self.store.backup):
            for path in paths:
                with self.subTest(method=method.__name__, path=path), self.assertRaises(ValueError):
                    method(path)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get_task(task["id"])["title"], "keep my data")

    def test_default_location_is_private_and_environment_override(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.directory / "data"), "LOCALAPPDATA": str(self.directory / "data"), "NAWA_DB_PATH": ""}):
            other = Store()
            try:
                name = "Nawa" if sys.platform == "win32" else "nawa"
                self.assertEqual(other.path, str(self.directory / "data" / name / "tasks.sqlite3"))
                if sys.platform != 'win32':
                    self.assertEqual(os.stat(Path(other.path).parent).st_mode & 0o777, 0o700)
            finally:
                other.close()
        with patch.dict(os.environ, {"NAWA_DB_PATH": str(self.directory / "override.db")}):
            other = Store()
            try:
                self.assertEqual(other.path, str(self.directory / "override.db"))
            finally:
                other.close()


if __name__ == "__main__":
    unittest.main()
