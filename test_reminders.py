"""Reminder delivery behavior without sending desktop notifications in tests."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from nawa.reminders import ReminderService


class FakeStore:
    def __init__(self):
        self.tasks = [{'id': 'one', 'title': 'مراجعة الخطة'}]
        self.marked = []
    def due_reminders(self):
        return [t for t in self.tasks if t['id'] not in self.marked]
    def mark_reminded(self, task_id):
        self.marked.append(task_id)


class FakeApp:
    def __init__(self):
        self.window = SimpleNamespace(store=FakeStore())
        self.actions = {}
        self.sent = []
        self.fail = False
    def lookup_action(self, name):
        return self.actions.get(name)
    def add_action(self, action):
        self.actions[action.get_name()] = action
    def send_notification(self, task_id, notification):
        if self.fail:
            raise RuntimeError('Notification backend unavailable')
        self.sent.append((task_id, notification))


class ReminderTests(unittest.TestCase):
    def test_initial_idle_callback_is_one_shot(self):
        service = ReminderService(FakeApp())
        with patch('nawa.reminders.GLib.timeout_add_seconds', return_value=12), patch('nawa.reminders.GLib.idle_add') as idle:
            service.start()
            callback = idle.call_args.args[0]
            self.assertIs(callback(), False)
        with patch('nawa.reminders.GLib.source_remove'):
            service.stop()

    def test_sends_once_and_registers_show_action(self):
        app = FakeApp()
        service = ReminderService(app)
        service.poll()
        service.poll()
        self.assertEqual(len(app.sent), 1)
        self.assertEqual(app.sent[0][0], 'task-one')
        self.assertIn('show', app.actions)
        self.assertEqual(app.window.store.marked, ['one'])

    def test_failed_delivery_remains_eligible_for_retry(self):
        app = FakeApp()
        service = ReminderService(app)
        app.fail = True
        service.poll()
        self.assertEqual(app.window.store.marked, [])
        self.assertIn('unavailable', service.error)
        app.fail = False
        service.poll()
        self.assertEqual(len(app.sent), 1)
        self.assertIsNone(service.error)


if __name__ == '__main__':
    unittest.main()
