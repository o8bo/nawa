"""Exercise the packaged executable without touching the user's data."""
import json
import os
from pathlib import Path
import tempfile
import traceback


def run(report_path):
    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'success': False}
    try:
        with tempfile.TemporaryDirectory(prefix='nawa-frozen-test-') as temporary:
            os.environ['NAWA_DB_PATH'] = str(Path(temporary) / 'data.sqlite3')
            os.environ['NAWA_SETTINGS_PATH'] = str(Path(temporary) / 'preferences.json')
            from . import preferences as prefs
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk, GLib
            from .ui import NawaApplication, MainWindow, TaskDialog
            from .expenses import ExpenseDialog
            from .store import Store
            assert Gtk.init_check()[0], 'No GTK display available'
            assets = Path(__file__).resolve().parent.parent / 'assets'
            assert (assets / 'style.css').is_file(), 'CSS is missing from the bundle'
            assert (assets / 'nawa.png').is_file(), 'Window icon is missing from the bundle'
            app = NawaApplication(); app.set_application_id('org.local.Nawa.BundleTest')
            app.register(None)
            for language, currency in [('ar', 'SAR'), ('en', 'USD')]:
                prefs.set_settings(language, currency, '3.75')
                assert prefs.read_settings() == prefs.settings
                Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL if language == 'ar' else Gtk.TextDirection.LTR)
                window = MainWindow(app)
                try:
                    task = window.store.create_task('اختبار Windows · Task')
                    dialog = TaskDialog(window, task)
                    assert dialog.title_entry.get_text() == task['title']
                    dialog.destroy()
                    window.select_view('expenses'); page = window.expenses_page
                    page.show_month('2026-10')
                    dialog = ExpenseDialog(page)
                    dialog.title_entry.set_text('اختبار مصروف · Coffee')
                    dialog.amount.set_text('37.50' if currency == 'SAR' else '10.00')
                    dialog.spent_on.set_text('2026-10-01')
                    saved = dialog.save(); dialog.destroy()
                    assert saved['amount_minor'] == 3750
                    window.store.finance.set_budget('2026-10', '375')
                    page.refresh()
                    assert ('$' if currency == 'USD' else 'ر.س') in page.values['total'].get_text()
                    loop = GLib.MainLoop()
                    GLib.timeout_add(400, lambda: (loop.quit(), False)[1]); loop.run()
                    assert len(page.daily.hits) == 31, 'Daily chart failed to render'
                    assert len(page.trend.hits) == 6, 'Trend chart failed to render'
                    window.show_reminder(task)
                    reminders = [d for d in Gtk.Window.list_toplevels() if isinstance(d, Gtk.MessageDialog)]
                    assert reminders, 'Reminder dialog did not open'
                    for d in reminders: d.destroy()
                    backup = Path(temporary) / 'backup.json'; window.store.export_json(backup)
                    restored = Store(str(Path(temporary) / f'restored-{language}.sqlite3'))
                    try:
                        restored.import_json(backup)
                        assert restored.finance.dump() == window.store.finance.dump()
                    finally: restored.close()
                    window.store.finance.delete(saved['id'])
                    report[language] = {'currency': currency, 'tasks': True, 'expenses': True,
                                        'charts': True, 'reminder': True, 'backup': True}
                finally:
                    window.destroy(); window.store.close()
            report['success'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['success'] else 1
