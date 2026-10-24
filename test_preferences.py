import csv
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nawa import preferences as prefs
from nawa.i18n import tr
from nawa.store import Store


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'preferences.json'
        self.environment = patch.dict(os.environ, {'NAWA_SETTINGS_PATH': str(self.path)})
        self.environment.start()
        self.original = prefs.settings
        prefs.settings = prefs.Preferences()

    def tearDown(self):
        prefs.settings = self.original
        self.environment.stop()
        self.folder.cleanup()

    def test_save_reload_and_language_currency_are_independent(self):
        for language, currency in [('en', 'SAR'), ('ar', 'USD'), ('en', 'USD'), ('ar', 'SAR')]:
            prefs.set_settings(language, currency, '3.75')
            self.assertEqual(prefs.read_settings(), prefs.settings)
            self.assertEqual(tr('الإعدادات'), 'Settings' if language == 'en' else 'الإعدادات')
            self.assertEqual(prefs.currency_symbol(), '$' if currency == 'USD' else 'SAR' if language == 'en' else 'ر.س')

    def test_bad_file_falls_back_and_failed_save_preserves_active_settings(self):
        for content in ['{', 'null', '[]', '{"language":"fr","currency":"EUR","usd_rate":"0"}']:
            self.path.write_text(content)
            self.assertEqual(prefs.read_settings(), prefs.Preferences())
        with patch('nawa.preferences.os.replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError): prefs.set_settings('en', 'USD', '3.75')
        self.assertEqual(prefs.settings, prefs.Preferences())
        remaining = list(self.path.parent.iterdir())
        self.assertEqual(len(remaining), 1)
        self.assertTrue(os.path.samefile(remaining[0], self.path))

    def test_invalid_rates_do_not_overwrite_saved_preferences(self):
        prefs.set_settings('en', 'USD', '٣٫٧٥')
        original = self.path.read_bytes()
        for rate in ['0', '-1', 'NaN', 'Infinity', '1e100', '0.00001', 'abc']:
            with self.assertRaises(ValueError): prefs.set_settings('ar', 'SAR', rate)
            self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(prefs.settings.usd_rate, Decimal('3.75'))

    def test_currency_conversion_and_rounding_do_not_mutate_ledger(self):
        store = Store(str(Path(self.folder.name) / 'data.sqlite3'))
        try:
            item = store.finance.create('Coffee', '37.50', 'طعام', '2026-10-01')
            store.finance.set_budget('2026-10', '375')
            before = store.finance.dump()
            prefs.set_settings('en', 'USD', '3.75')
            self.assertEqual(prefs.formatted(item['amount_minor']), '10.00')
            self.assertEqual(prefs.input_amount('١٠٫٠٠'), '37.5')
            self.assertEqual(prefs.input_amount('0.01'), '0.04')
            self.assertEqual(prefs.formatted(37500), '100.00')
            self.assertEqual(store.finance.dump(), before)
            prefs.set_settings('ar', 'SAR', '3.75')
            self.assertEqual(prefs.formatted(item['amount_minor']), '37.50')
            self.assertEqual(store.finance.dump(), before)
        finally: store.close()

    def test_unchanged_dollar_edit_preserves_every_halalah(self):
        prefs.set_settings('en', 'USD', '3.75')
        for minor in [1, 2, 3, 4, 5, 1234, 999999999999]:
            original = prefs.formatted(minor).replace(',', '')
            self.assertEqual(Decimal(prefs.input_amount(original, minor)) * 100, minor)
        self.assertEqual(prefs.input_amount('12.00', 1234), '45')

    def test_csv_uses_selected_language_currency_and_preserves_user_text(self):
        store = Store(str(Path(self.folder.name) / 'data.sqlite3'))
        try:
            store.finance.create('اليوم', '37.50', 'طعام', '2026-10-01', '=formula')
            prefs.set_settings('en', 'USD', '3.75')
            path = Path(self.folder.name) / 'expenses.csv'
            store.finance.export_csv(path, '2026-10')
            with path.open(encoding='utf-8-sig', newline='') as handle: rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ['Date', 'Description', 'Category', 'Amount ($)', 'Notes'])
            self.assertEqual(rows[1], ['2026-10-01', 'اليوم', 'Food', '10.00', "'=formula"])
            payload = Path(self.folder.name) / 'backup.json'
            store.export_json(payload)
            other = Store(str(Path(self.folder.name) / 'restored.sqlite3'))
            try:
                other.import_json(payload)
                self.assertEqual(other.finance.dump(), store.finance.dump())
            finally: other.close()
        finally: store.close()


if __name__ == '__main__': unittest.main()
