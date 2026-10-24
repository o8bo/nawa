from .i18n import tr
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description=tr('نواة — مهامك ومصاريفك، ببساطة'))
    parser.add_argument('--data', help=tr('مسار قاعدة SQLite بديلة'))
    parser.add_argument('--add', help=tr('إضافة مهمة من الطرفية'))
    parser.add_argument('--list', action='store_true', help=tr('عرض المهام بصيغة JSON'))
    parser.add_argument('--export', help=tr('تصدير نسخة JSON'))
    parser.add_argument('--import-json', help=tr('استيراد نسخة JSON'))
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--expenses', action='store_true', help=tr('فتح لوحة المصاريف الشهرية'))
    args = parser.parse_args()
    if args.data:
        import os
        os.environ['NAWA_DB_PATH'] = args.data
        from . import preferences
        preferences.settings = preferences.read_settings()
    from .store import Store
    if args.add or args.list or args.export or args.import_json:
        store = Store(args.data)
        try:
            if args.add:
                print(json.dumps(store.create_task(args.add), ensure_ascii=False, indent=2))
            if args.list:
                print(json.dumps(store.list_tasks(), ensure_ascii=False, indent=2))
            if args.export:
                print(store.export_json(args.export))
            if args.import_json:
                print(json.dumps(store.import_json(args.import_json), ensure_ascii=False))
        finally:
            if hasattr(store, 'close'):
                store.close()
        return 0
    from .ui import NawaApplication
    from .reminders import ReminderService
    from gi.repository import GLib, Gdk
    Gdk.set_program_class('Nawa')
    class DesktopApplication(NawaApplication):
        def setup_tray(self):
            try:
                import gi
                gi.require_version('AyatanaAppIndicator3', '0.1')
                from gi.repository import AyatanaAppIndicator3 as Indicator, Gtk
                from pathlib import Path
                tray = Indicator.Indicator.new('nawa', 'nawa', Indicator.IndicatorCategory.APPLICATION_STATUS)
                tray.set_icon_full(str(Path(__file__).resolve().parent.parent / 'assets' / 'nawa.svg'), tr('نواة'))
                menu = Gtk.Menu()
                for text, callback in [(tr('فتح نواة'), lambda *_: self.activate()), (tr('خروج من نواة'), lambda *_: self.quit())]:
                    item = Gtk.MenuItem(label=text)
                    item.connect('activate', callback)
                    menu.append(item)
                menu.show_all()
                tray.set_menu(menu)
                tray.set_status(Indicator.IndicatorStatus.ACTIVE)
                self.window.tray = tray
                def hide_window(*_):
                    self.window.hide()
                    return True
                if not getattr(self.window, '_tray_hide_connected', False):
                    self.window.connect('delete-event', hide_window)
                    self.window._tray_hide_connected = True
            except (ValueError, ImportError):
                self.window.tray = None

        def do_activate(self):
            super().do_activate()
            if not hasattr(self, 'reminders'):
                self.setup_tray()
                self.reminders = ReminderService(self)
                self.reminders.start()
                self.connect('shutdown', lambda *_: self.reminders.stop())
                self.connect('shutdown', lambda *_: self.window.store.close())
                if args.background and getattr(self.window, 'tray', None):
                    GLib.idle_add(self.window.hide)
            if args.expenses:
                self.window.select_view('expenses')
    return DesktopApplication().run([sys.argv[0]])


if __name__ == '__main__':
    raise SystemExit(main())
