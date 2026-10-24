"""Local expense ledger. Money is stored as integer halalas, never binary floats."""
from .i18n import tr
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import calendar
import csv
import re
import uuid

CATEGORIES = ['سكن', 'طعام', 'مواصلات', 'فواتير', 'تسوق', 'صحة', 'ترفيه', 'تعليم', 'أخرى']
MAX_MINOR = 999_999_999_999
DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def money(value, allow_zero=False):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(tr('اكتب المبلغ كعدد واضح، مثل 125.50.'))
    text = str(value).translate(DIGITS).strip().replace('٬', ',').replace('٫', '.')
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', text):
        raise ValueError(tr('المبلغ غير صالح؛ استخدم منزلتين عشريتين كحد أقصى، مثل 1,250.75.'))
    try:
        result = int(Decimal(text.replace(',', '')) * 100)
    except (InvalidOperation, ValueError):
        raise ValueError(tr('المبلغ غير صالح.'))
    if result < (0 if allow_zero else 1) or result > MAX_MINOR:
        raise ValueError(tr('أدخل مبلغًا موجبًا ضمن النطاق المدعوم.'))
    return result


def formatted(minor):
    return f'{Decimal(minor) / 100:,.2f}'


def month_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}', value):
        raise ValueError(tr('الشهر غير صالح.'))
    date.fromisoformat(value + '-01')
    return value


def shifted_month(month, offset):
    day = date.fromisoformat(month_key(month) + '-01')
    index = day.year * 12 + day.month - 1 + offset
    return f'{index // 12:04}-{index % 12 + 1:02}'


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, amount_minor INTEGER NOT NULL CHECK(amount_minor>0),
        category TEXT NOT NULL, spent_on TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)''')
    conn.execute('CREATE INDEX IF NOT EXISTS expenses_month ON expenses(deleted_at,spent_on)')
    conn.execute('''CREATE TABLE IF NOT EXISTS expense_budgets (
        month TEXT PRIMARY KEY, amount_minor INTEGER NOT NULL CHECK(amount_minor>=0))''')


def validate_record(item):
    fields = ['id', 'title', 'category', 'spent_on', 'notes', 'created_at', 'updated_at', 'deleted_at', 'amount_minor']
    if not isinstance(item, dict) or not all(k in item for k in fields):
        raise ValueError(tr('سجل مصروف غير مكتمل في النسخة الاحتياطية.'))
    out = {k: item[k] for k in fields}
    for k in ['id', 'title', 'category', 'notes']:
        if not isinstance(out[k], str) or '\x00' in out[k] or (k != 'notes' and not out[k].strip()):
            raise ValueError(tr('نص غير صالح في بيانات المصروف.'))
    if type(out['amount_minor']) is not int or not 0 < out['amount_minor'] <= MAX_MINOR:
        raise ValueError(tr('قيمة مصروف غير صالحة في النسخة الاحتياطية.'))
    if not isinstance(out['spent_on'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', out['spent_on']):
        raise ValueError(tr('تاريخ المصروف غير صالح.'))
    date.fromisoformat(out['spent_on'])
    for k in ['created_at', 'updated_at', 'deleted_at']:
        if k == 'deleted_at' and out[k] is None:
            continue
        if not isinstance(out[k], str):
            raise ValueError(tr('تاريخ حفظ غير صالح.'))
        datetime.fromisoformat(out[k])
    return out


class FinanceStore:
    def __init__(self, store):
        self.store, self.conn = store, store.conn

    def create(self, title, amount, category='أخرى', spent_on=None, notes=''):
        now = datetime.now().isoformat(timespec='seconds')
        item = validate_record(dict(id=str(uuid.uuid4()), title=title.strip(), amount_minor=money(amount),
            category=category.strip(), spent_on=spent_on or date.today().isoformat(), notes=notes,
            created_at=now, updated_at=now, deleted_at=None))
        with self.conn:
            self.insert(item)
        return self.get(item['id'])

    def insert(self, item):
        cols = list(item)
        self.conn.execute('INSERT INTO expenses (' + ','.join(cols) + ') VALUES (' + ','.join('?' for _ in cols) + ')', [item[c] for c in cols])

    def get(self, expense_id):
        row = self.conn.execute('SELECT * FROM expenses WHERE id=?', (expense_id,)).fetchone()
        return dict(row) if row else None

    def update(self, expense_id, title, amount, category, spent_on, notes=''):
        old = self.get(expense_id)
        if not old or old['deleted_at']:
            raise ValueError(tr('المصروف غير موجود.'))
        new = validate_record(dict(old, title=title.strip(), amount_minor=money(amount), category=category.strip(),
            spent_on=spent_on, notes=notes, updated_at=datetime.now().isoformat(timespec='seconds')))
        with self.conn:
            self.conn.execute('UPDATE expenses SET title=?,amount_minor=?,category=?,spent_on=?,notes=?,updated_at=? WHERE id=?',
                (new['title'], new['amount_minor'], new['category'], new['spent_on'], new['notes'], new['updated_at'], expense_id))
        return self.get(expense_id)

    def delete(self, expense_id):
        with self.conn:
            now = datetime.now().isoformat(timespec='seconds')
            self.conn.execute('UPDATE expenses SET deleted_at=?,updated_at=? WHERE id=?', (now, now, expense_id))

    def restore(self, expense_id):
        with self.conn:
            self.conn.execute('UPDATE expenses SET deleted_at=NULL,updated_at=? WHERE id=?',
                (datetime.now().isoformat(timespec='seconds'), expense_id))

    def list(self, month, search='', category=None):
        month_key(month)
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM expenses WHERE deleted_at IS NULL AND substr(spent_on,1,7)=? ORDER BY spent_on DESC,created_at DESC,id", (month,))]
        if category:
            rows = [r for r in rows if r['category'] == category]
        needle = search.strip().casefold()
        if needle:
            rows = [r for r in rows if needle in '\n'.join([r['title'], r['category'], r['notes']]).casefold()]
        return rows

    def set_budget(self, month, amount):
        month_key(month)
        with self.conn:
            if amount is None or amount == '':
                self.conn.execute('DELETE FROM expense_budgets WHERE month=?', (month,))
            else:
                value = money(amount, allow_zero=True)
                self.conn.execute('INSERT INTO expense_budgets(month,amount_minor) VALUES(?,?) ON CONFLICT(month) DO UPDATE SET amount_minor=excluded.amount_minor', (month, value))

    def summary(self, month):
        rows = self.list(month)
        categories, daily = defaultdict(int), defaultdict(int)
        for row in rows:
            categories[row['category']] += row['amount_minor']
            daily[int(row['spent_on'][-2:])] += row['amount_minor']
        total = sum(categories.values())
        budget = self.conn.execute('SELECT amount_minor FROM expense_budgets WHERE month=?', (month,)).fetchone()
        previous = sum(r['amount_minor'] for r in self.list(shifted_month(month, -1)))
        days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
        return dict(total=total, count=len(rows), budget=budget[0] if budget else None, previous=previous,
            categories=sorted(categories.items(), key=lambda x: (-x[1], x[0])),
            daily=[daily[d] for d in range(1, days + 1)],
            trend=[(m, sum(r['amount_minor'] for r in self.list(m))) for m in [shifted_month(month, o) for o in range(-5, 1)]])

    def dump(self):
        return dict(expenses=[dict(r) for r in self.conn.execute('SELECT * FROM expenses ORDER BY id')],
            budgets=[dict(r) for r in self.conn.execute('SELECT * FROM expense_budgets ORDER BY month')])

    def validate_dump(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get('expenses'), list) or not isinstance(payload.get('budgets'), list):
            raise ValueError(tr('قسم المصاريف في النسخة الاحتياطية غير صالح.'))
        expenses = [validate_record(r) for r in payload['expenses']]
        if len({r['id'] for r in expenses}) != len(expenses):
            raise ValueError(tr('معرّفات مصاريف مكررة.'))
        budgets, seen = [], set()
        for row in payload['budgets']:
            if not isinstance(row, dict):
                raise ValueError(tr('ميزانية غير صالحة.'))
            month = month_key(row.get('month'))
            value = row.get('amount_minor')
            if month in seen or type(value) is not int or not 0 <= value <= MAX_MINOR:
                raise ValueError(tr('ميزانية غير صالحة أو مكررة.'))
            seen.add(month)
            budgets.append(dict(month=month, amount_minor=value))
        return expenses, budgets

    def merge(self, prepared):
        # Caller owns the import transaction; existing local edits are preserved.
        added = conflicts = skipped = 0
        expenses, budgets = prepared
        for item in expenses:
            old = self.get(item['id'])
            if old:
                skipped += 1
                conflicts += old != item
            else:
                self.insert(item)
                added += 1
        for row in budgets:
            old = self.conn.execute('SELECT amount_minor FROM expense_budgets WHERE month=?', (row['month'],)).fetchone()
            if old:
                conflicts += old[0] != row['amount_minor']
            else:
                self.conn.execute('INSERT INTO expense_budgets VALUES(?,?)', (row['month'], row['amount_minor']))
        return dict(expenses_imported=added, expenses_skipped=skipped, expense_conflicts=conflicts)

    def export_csv(self, path, month):
        from .preferences import formatted as display_formatted, currency_symbol
        from .i18n import tr
        rows = self.list(month)
        def write(handle):
            writer = csv.writer(handle)
            writer.writerow([tr('التاريخ'), tr('الوصف'), tr('التصنيف'), tr('المبلغ') + ' (' + currency_symbol() + ')', tr('الملاحظات')])
            for row in rows:
                texts = [row['spent_on'], row['title'], tr(row['category']), display_formatted(row['amount_minor']).replace(',', ''), row['notes']]
                writer.writerow(["'" + t if t.startswith(('=', '+', '-', '@', '\t', '\r')) else t for t in texts])
        self.store._write_atomic(path, write)
        return len(rows)
