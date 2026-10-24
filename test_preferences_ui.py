"""Native GTK integration checks; skipped when no display is available."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from nawa import preferences as prefs
from nawa.ui import NawaApplication, MainWindow, TaskDialog
from nawa.expenses import ExpenseDialog


@unittest.skipUnless(Gtk.init_check()[0], 'GTK display unavailable')
class PreferencesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = NawaApplication()
        cls.app.set_application_id('org.local.Nawa.PreferencesTest')
        cls.app.register(None)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = prefs.settings
        self.env = patch.dict(os.environ, {'NAWA_DB_PATH': str(Path(self.folder.name) / 'data.sqlite3'), 'NAWA_SETTINGS_PATH': str(Path(self.folder.name) / 'preferences.json')})
        self.env.start(); prefs.settings = prefs.Preferences()
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
        self.window = MainWindow(self.app)

    def tearDown(self):
        self.window.destroy(); self.window.store.close()
        prefs.settings = self.original; self.env.stop(); self.folder.cleanup()

    def choose(self, language, currency):
        errors = []
        def respond():
            try:
                dialog = next(w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.Dialog) and w.get_visible())
                combos = [w for w in dialog.get_content_area().get_children() if isinstance(w, Gtk.ComboBoxText)]
                combos[0].set_active_id(language); combos[1].set_active_id(currency)
                dialog.response(Gtk.ResponseType.OK)
            except Exception as exc:
                errors.append(exc)
                for w in Gtk.Window.list_toplevels():
                    if isinstance(w, Gtk.Dialog): w.response(Gtk.ResponseType.CANCEL)
            return False
        GLib.idle_add(respond); self.window.preferences()
        if errors: raise errors[0]

    def test_live_switch_preserves_drafts_filters_navigation_and_data(self):
        w = self.window
        item = w.store.create_task('اليوم')
        listing = w.store.create_list('اليوم')
        w.entry.set_text('مسودة مهمة')
        w.search.set_text('اليوم'); w.sort.set_active_id('title')
        expense = w.store.finance.create('Coffee', '37.50', 'طعام', '2026-10-01')
        w.store.finance.set_budget('2026-10', '375')
        w.select_view('expenses'); w.expenses_page.show_month('2026-10')
        w.expenses_page.remove(expense)
        self.choose('en', 'USD')
        self.assertEqual(w.get_direction(), Gtk.TextDirection.LTR)
        self.assertEqual(w.get_title(), 'Nawa — Tasks and expenses')
        self.assertEqual(w.entry.get_text(), 'مسودة مهمة')
        self.assertEqual(w.search.get_text(), 'اليوم')
        self.assertEqual(w.sort.get_active_id(), 'title')
        self.assertEqual(w.section, 'expenses')
        self.assertEqual(w.expenses_page.month, '2026-10')
        self.assertEqual(w.expenses_page.last_deleted, expense['id'])
        w.expenses_page.undo()
        self.assertEqual(w.expenses_page.values['total'].get_text(), '10.00 $')
        self.assertIn('100.00 $', w.expenses_page.values['remaining_detail'].get_text())
        w.expenses_page.search.set_text('Food'); w.expenses_page.refresh_ledger()
        self.assertEqual(len(w.expenses_page.ledger.get_children()), 1)
        dialog = ExpenseDialog(w.expenses_page, expense)
        self.assertEqual(dialog.amount.get_text(), '10.00')
        self.assertEqual(dialog.category.get_child().get_text(), 'Food')
        dialog.save(); dialog.destroy()
        self.assertEqual(w.store.finance.get(expense['id'])['amount_minor'], 3750)
        self.assertEqual(w.store.finance.get(expense['id'])['category'], 'طعام')
        w.select_view('all', listing['id'], listing['name'])
        self.assertEqual(w.heading.get_text(), 'اليوم')
        self.choose('ar', 'SAR')
        self.assertEqual(w.get_direction(), Gtk.TextDirection.RTL)
        self.assertEqual(w.store.get_task(item['id'])['title'], 'اليوم')
        self.assertEqual(w.expenses_page.values['total'].get_text(), '37.50 ر.س')
        self.assertEqual(prefs.read_settings().language, 'ar')

    def test_english_task_dialog_and_dollar_expense_creation(self):
        self.choose('en', 'USD')
        w = self.window
        task = w.store.create_task('اليوم')
        dialog = TaskDialog(w, task)
        self.assertEqual(dialog.get_title(), 'Task details')
        self.assertEqual(dialog.title_entry.get_text(), 'اليوم')
        self.assertEqual(dialog.priority.get_active_text(), 'No priority')
        self.assertEqual(dialog.status.get_active_text(), 'To do')
        dialog.destroy()
        page = w.expenses_page; page.show_month('2026-10')
        dialog = ExpenseDialog(page)
        dialog.title_entry.set_text('Coffee'); dialog.amount.set_text('12.50')
        dialog.category.set_active_id('طعام')
        record = dialog.save(); dialog.destroy()
        self.assertEqual(record['amount_minor'], 4688)
        self.assertEqual(record['category'], 'طعام')
        page.refresh()
        self.assertEqual(page.values['total'].get_text(), '12.50 $')


if __name__ == '__main__': unittest.main()
