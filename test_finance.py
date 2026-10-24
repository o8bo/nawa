import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from nawa.store import Store
from nawa.finance_store import money, formatted


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data.sqlite3')
        self.finance = self.store.finance

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def test_exact_money_arabic_digits_and_validation(self):
        self.assertEqual(money('١٬٢٥٠٫٧٥'), 125075)
        self.assertEqual(formatted(125075), '1,250.75')
        for value in ['NaN', 'Infinity', '-1', '0', '1.005', '1,25', '', None, True, 0.1]:
            with self.subTest(value=value), self.assertRaises(ValueError): money(value)
        self.finance.create('a', '0.10', spent_on='2026-10-01')
        self.finance.create('b', '0.20', spent_on='2026-10-01')
        self.assertEqual(self.finance.summary('2026-10')['total'], 30)

    def test_month_boundaries_categories_daily_and_trend(self):
        self.finance.create('السابق', '5', 'طعام', '2025-12-31')
        self.finance.create('طعام', '10.25', 'طعام', '2026-01-01')
        self.finance.create('تنقل', '20.50', 'مواصلات', '2026-01-31')
        self.finance.create('شهر آخر', '100', 'طعام', '2026-02-01')
        s = self.finance.summary('2026-01')
        self.assertEqual((s['total'], s['count'], s['previous']), (3075, 2, 500))
        self.assertEqual((s['daily'][0], s['daily'][-1], len(s['daily'])), (1025, 2050, 31))
        self.assertEqual(sum(v for _, v in s['categories']), s['total'])
        self.assertEqual(s['trend'][-2:], [('2025-12', 500), ('2026-01', 3075)])
        self.assertEqual(len(self.finance.summary('2028-02')['daily']), 29)

    def test_edit_move_month_delete_and_restore(self):
        item = self.finance.create('قهوة', '12.50', 'طعام', '2026-10-02')
        self.finance.update(item['id'], 'قهوة معدلة', '15', 'طعام', '2026-11-01', 'تعديل')
        self.assertEqual(self.finance.summary('2026-10')['total'], 0)
        self.assertEqual(self.finance.summary('2026-11')['total'], 1500)
        self.finance.delete(item['id'])
        self.assertEqual(self.finance.summary('2026-11')['count'], 0)
        self.finance.restore(item['id'])
        self.assertEqual(self.finance.summary('2026-11')['total'], 1500)
        with self.assertRaises(ValueError):
            self.finance.update(item['id'], '', '20', 'طعام', '2026-11-01')
        self.assertEqual(self.finance.get(item['id'])['amount_minor'], 1500)

    def test_budget_per_month_persistence_and_clear(self):
        self.finance.set_budget('2026-10', '5000')
        self.finance.set_budget('2026-11', '0')
        self.assertEqual(self.finance.summary('2026-10')['budget'], 500000)
        self.assertEqual(self.finance.summary('2026-11')['budget'], 0)
        self.store.close(); self.store = Store(self.root/'data.sqlite3'); self.finance = self.store.finance
        self.assertEqual(self.finance.summary('2026-10')['budget'], 500000)
        self.finance.set_budget('2026-10', '')
        self.assertIsNone(self.finance.summary('2026-10')['budget'])

    def test_full_json_roundtrip_and_preserve_local_edits(self):
        item = self.finance.create('سكن', '2500', 'سكن', '2026-10-01')
        removed = self.finance.create('خطأ', '10', spent_on='2026-10-02'); self.finance.delete(removed['id'])
        self.finance.set_budget('2026-10', '6000'); self.store.create_task('تظل المهام محفوظة')
        target = self.root/'backup.json'; self.store.export_json(target)
        other = Store(self.root/'other.sqlite3')
        try:
            result = other.import_json(target)
            self.assertEqual((result['imported'], result['expenses_imported']), (1, 2))
            self.assertEqual(other.finance.summary('2026-10')['total'], 250000)
            self.assertEqual(other.finance.summary('2026-10')['budget'], 600000)
            self.assertEqual(other.import_json(target)['expenses_skipped'], 2)
            other.finance.update(item['id'], 'محلي', '2400', 'سكن', '2026-10-01')
            self.assertEqual(other.import_json(target)['expense_conflicts'], 1)
            self.assertEqual(other.finance.get(item['id'])['title'], 'محلي')
        finally: other.close()

    def test_invalid_finance_rolls_back_task_import(self):
        self.store.create_task('موجودة'); path = self.root/'bad.json'; self.store.export_json(path)
        payload = json.loads(path.read_text(encoding='utf-8')); task = copy.deepcopy(payload['tasks'][0]); task.update(id='new-task', title='يجب التراجع')
        payload['tasks'].append(task)
        payload['finance']['expenses'] = [dict(id='bad', title='x', amount_minor=-1)]
        path.write_text(json.dumps(payload))
        with self.assertRaises(ValueError): self.store.import_json(path)
        self.assertIsNone(self.store.get_task('new-task'))
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_v1_database_migration_and_old_json(self):
        task = self.store.create_task('قديمة')
        path = self.root/'old.json'; self.store.export_json(path)
        payload = json.loads(path.read_text(encoding='utf-8')); payload['schema_version'] = 1; payload.pop('finance'); path.write_text(json.dumps(payload))
        with self.store.conn:
            self.store.conn.execute('DROP TABLE expenses'); self.store.conn.execute('DROP TABLE expense_budgets')
            self.store.conn.execute('PRAGMA user_version=1')
        self.store.close(); self.store = Store(self.root/'data.sqlite3'); self.finance = self.store.finance
        self.assertEqual(self.store.get_task(task['id'])['title'], 'قديمة')
        self.assertEqual(self.finance.summary('2026-10')['total'], 0)
        self.assertEqual(self.store.import_json(path)['skipped'], 1)
        self.assertEqual(self.store.conn.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_search_export_month_and_live_database_guard(self):
        self.finance.create('=FORMULA', '5.25', 'طعام', '2026-10-02', 'فاتورة عربية')
        self.finance.create('أخرى', '3', 'سكن', '2026-11-02')
        self.assertEqual(len(self.finance.list('2026-10', search='فاتورة')), 1)
        path = self.root/'expenses.csv'; self.assertEqual(self.finance.export_csv(path, '2026-10'), 1)
        with path.open(encoding='utf-8', newline='') as f: rows = list(csv.reader(f))
        self.assertEqual(rows[1][1], "'=FORMULA"); self.assertEqual(rows[1][3], '5.25')
        with self.assertRaises(ValueError): self.finance.export_csv(self.store.path, '2026-10')
        self.assertEqual(self.finance.summary('2026-10')['total'], 525)


if __name__ == '__main__': unittest.main()
