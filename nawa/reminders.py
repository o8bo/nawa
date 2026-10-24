"""Best-effort desktop reminders while Nawa is running; no background service."""
from .i18n import tr
from gi.repository import Gio, GLib
import sys


class ReminderService:
    def __init__(self, application):
        self.application = application
        self.source = None
        self.error = None
        if not application.lookup_action('show'):
            action = Gio.SimpleAction.new('show', None)
            action.connect('activate', lambda *_: application.activate())
            application.add_action(action)

    def start(self):
        if self.source is None:
            self.source = GLib.timeout_add_seconds(30, self.poll)
            GLib.idle_add(self._poll_once)

    def _poll_once(self):
        if self.source is not None:
            self.poll()
        return False

    def stop(self):
        if self.source is not None:
            GLib.source_remove(self.source)
            self.source = None

    def poll(self):
        window = self.application.window
        if window is None:
            return True
        try:
            for task in window.store.due_reminders():
                note = Gio.Notification.new(tr('موعد مهمة في نواة'))
                note.set_body(task['title'])
                note.set_default_action('app.show')
                note.set_priority(Gio.NotificationPriority.NORMAL)
                if sys.platform == 'win32' and callable(getattr(window, 'show_reminder', None)):
                    window.show_reminder(task)
                else:
                    self.application.send_notification('task-' + str(task['id']), note)
                window.store.mark_reminded(task['id'])
            self.error = None
        except Exception as error:
            self.error = str(error)
        return True
