"""Nawa's native GTK desktop interface. All changes go through Store."""
from .i18n import tr
from pathlib import Path
import os
from datetime import date, datetime
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from .store import Store

VIEWS = [('all', 'كل المهام', 'view-list-symbolic'), ('today', 'اليوم', 'weather-clear-symbolic'), ('upcoming', 'القادمة', 'x-office-calendar-symbolic'), ('done', 'المكتملة', 'emblem-ok-symbolic'), ('trash', 'المحذوفات', 'user-trash-symbolic')]
PRIORITIES = ['بلا أولوية', 'منخفضة', 'متوسطة', 'عالية']

def label(text='', css=None):
    item = Gtk.Label(label=text, xalign=0)
    if css:
        item.get_style_context().add_class(css)
    return item

def button(text, callback, css=None):
    item = Gtk.Button(label=text)
    item.connect('clicked', callback)
    if css:
        item.get_style_context().add_class(css)
    return item

class TaskDialog(Gtk.Dialog):
    def __init__(self, parent, task):
        super().__init__(title=tr('تفاصيل المهمة'), transient_for=parent, modal=True)
        self.set_default_size(600, 660)
        self.task = task
        self.store = parent.store
        self.subtasks = [dict(s) for s in task.get('subtasks', [])]
        self.add_button(tr('إلغاء'), Gtk.ResponseType.CANCEL)
        self.add_button(tr('حفظ التغييرات'), Gtk.ResponseType.OK).get_style_context().add_class('suggested-action')
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.get_content_area().pack_start(scroll, True, True, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=22)
        scroll.add(box)
        self.title_entry = Gtk.Entry(text=task['title'])
        self.title_entry.get_style_context().add_class('detail-title')
        self.title_entry.connect('changed', lambda e: self.set_response_sensitive(Gtk.ResponseType.OK, bool(e.get_text().strip())))
        box.pack_start(label(tr('عنوان المهمة'), 'field-label'), False, False, 0)
        box.pack_start(self.title_entry, False, False, 0)
        self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.notes.set_size_request(-1, 95)
        self.notes.get_buffer().set_text(task.get('notes') or '')
        box.pack_start(label(tr('ملاحظات'), 'field-label'), False, False, 0)
        frame = Gtk.Frame(); frame.add(self.notes); box.pack_start(frame, False, False, 0)
        grid = Gtk.Grid(column_spacing=14, row_spacing=10)
        box.pack_start(grid, False, False, 0)
        def combo(values, active):
            c = Gtk.ComboBoxText()
            for key, value in values:
                c.append(str(key), value)
            c.set_active_id(str(active)); c.set_hexpand(True)
            return c
        self.status = combo([('todo', tr('لم تبدأ')), ('doing', tr('قيد التنفيذ')), ('done', tr('مكتملة'))], task['status'])
        self.priority = combo([(i, tr(p)) for i, p in enumerate(PRIORITIES)], task.get('priority', 0))
        self.list_combo = combo([('', tr('دون قائمة'))] + [(str(x['id']), x['name']) for x in self.store.list_lists()], task.get('list_id') or '')
        self.repeat = combo([('none', tr('دون تكرار')), ('daily', tr('يوميًا')), ('weekly', tr('أسبوعيًا')), ('monthly', tr('شهريًا'))], task.get('repeat', 'none'))
        self.due = Gtk.Entry(text=task.get('due_date') or '', placeholder_text='YYYY-MM-DD')
        self.due.set_direction(Gtk.TextDirection.LTR)
        due_box = Gtk.Box(spacing=4); due_box.pack_start(self.due, True, True, 0)
        date_btn = Gtk.MenuButton(); date_btn.set_image(Gtk.Image.new_from_icon_name('x-office-calendar-symbolic', Gtk.IconSize.BUTTON))
        pop = Gtk.Popover.new(date_btn); cal = Gtk.Calendar(); pop.add(cal); date_btn.set_popover(pop)
        if task.get('due_date'):
            day = date.fromisoformat(task['due_date']); cal.select_month(day.month - 1, day.year); cal.select_day(day.day)
        def selected(_):
            y, m, d = cal.get_date(); self.due.set_text(f'{y:04}-{m+1:02}-{d:02}'); pop.hide()
        cal.connect('day-selected-double-click', selected)
        cal.connect('day-selected', lambda _: None)
        due_box.pack_start(date_btn, False, False, 0)
        self.reminder = Gtk.Entry(text=(task.get('reminder_at') or '').replace('T', ' '), placeholder_text='YYYY-MM-DD HH:MM')
        self.reminder.set_direction(Gtk.TextDirection.LTR)
        for row, (name, widget) in enumerate([(tr('الحالة'), self.status), (tr('الأولوية'), self.priority), (tr('القائمة'), self.list_combo), (tr('تاريخ الاستحقاق'), due_box), (tr('التكرار'), self.repeat), (tr('موعد التذكير'), self.reminder)]):
            grid.attach(label(name, 'field-label'), 0, row, 1, 1); grid.attach(widget, 1, row, 1, 1)
        box.pack_start(label(tr('اختر اليوم بالنقر المزدوج في التقويم. امسح الحقل لإزالة الموعد.'), 'muted'), False, False, 0)
        self.tags = Gtk.Entry(text='، '.join(task.get('tags', [])), placeholder_text=tr('وسوم، مفصولة، بفاصلة'))
        box.pack_start(label(tr('الوسوم'), 'field-label'), False, False, 0); box.pack_start(self.tags, False, False, 0)
        box.pack_start(label(tr('خطوات المهمة'), 'field-label'), False, False, 0)
        self.subbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        box.pack_start(self.subbox, False, False, 0)
        self.subentry = Gtk.Entry(placeholder_text=tr('خطوة جديدة… اضغط Enter'))
        self.subentry.connect('activate', self.add_step)
        box.pack_start(self.subentry, False, False, 0)
        self.error = label('', 'error'); self.error.set_line_wrap(True); box.pack_start(self.error, False, False, 0)
        self.draw_steps(); self.show_all()

    def add_step(self, entry):
        title = entry.get_text().strip()
        if title:
            self.subtasks.append({'id': None, 'title': title, 'done': False}); entry.set_text(''); self.draw_steps()

    def draw_steps(self):
        for child in self.subbox.get_children(): self.subbox.remove(child)
        for step in self.subtasks:
            row = Gtk.Box(spacing=6)
            check = Gtk.CheckButton(label=step['title']); check.set_active(step['done'])
            check.connect('toggled', lambda cb, s=step: s.update(done=cb.get_active()))
            row.pack_start(check, True, True, 0)
            row.pack_start(button('×', lambda _, s=step: self.remove_step(s), 'flat'), False, False, 0)
            self.subbox.pack_start(row, False, False, 0)
        self.subbox.show_all()

    def remove_step(self, step):
        self.subtasks.remove(step); self.draw_steps()

    def save(self):
        title = self.title_entry.get_text().strip()
        if not title: raise ValueError(tr('اكتب عنوانًا للمهمة.'))
        due = self.due.get_text().strip() or None
        reminder = self.reminder.get_text().strip().replace(' ', 'T') or None
        try:
            if due: date.fromisoformat(due)
            if reminder: datetime.strptime(reminder, '%Y-%m-%dT%H:%M')
        except ValueError:
            raise ValueError(tr('تحقق من التاريخ YYYY-MM-DD وموعد التذكير YYYY-MM-DD HH:MM.'))
        if reminder and datetime.fromisoformat(reminder) <= datetime.now() and reminder != self.task.get('reminder_at'):
            raise ValueError(tr('اختر موعد تذكير قادمًا.'))
        buf = self.notes.get_buffer()
        fields = dict(title=title, notes=buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True), due_date=due, reminder_at=reminder, priority=int(self.priority.get_active_id()), status=self.status.get_active_id(), list_id=self.list_combo.get_active_id() or None, repeat=self.repeat.get_active_id(), tags=[x.strip() for x in self.tags.get_text().replace('،', ',').split(',') if x.strip()])
        if self.subentry.get_text().strip(): self.add_step(self.subentry)
        self.store.save_task_details(self.task['id'], fields, self.subtasks)

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application, store=None):
        super().__init__(application=application, title=tr('نواة — مهامك ومصاريفك'))
        self.store = store or Store(os.environ.get("NAWA_DB_PATH"))
        self.view = 'all'; self.list_id = None; self.section = 'tasks'
        self.set_default_size(1180, 820); self.set_size_request(960, 620)
        self.set_icon_name('org.local.Nawa')
        self.connect('key-press-event', self.keypress)
        self.build_ui()

    def build_ui(self):
        application = self.get_application()
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL); self.add(root)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=0)
        sidebar.get_style_context().add_class('sidebar'); sidebar.set_size_request(220, -1)
        root.pack_start(sidebar, False, False, 0)
        brand = label(tr('◈  نواة'), 'brand'); brand.set_margin_top(30); brand.set_margin_bottom(3); sidebar.pack_start(brand, False, False, 0)
        sidebar.pack_start(label(tr('مساحة هادئة لإنجاز يومك'), 'muted'), False, False, 0)
        self.nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5); self.nav.set_margin_top(28)
        sidebar.pack_start(self.nav, False, False, 0)
        for key, title, icon in VIEWS:
            b = button(tr(title), lambda _, v=key: self.select_view(v), 'nav-button'); b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)); b.set_always_show_image(True)
            b._view = key; self.nav.pack_start(b, False, False, 0)
        expense_nav = button(tr('المصاريف الشهرية'), lambda _: self.select_view('expenses'), 'nav-button')
        expense_nav.set_image(Gtk.Image.new_from_icon_name('view-statistics-symbolic', Gtk.IconSize.BUTTON)); expense_nav.set_always_show_image(True)
        expense_nav._view = 'expenses'; self.nav.pack_start(expense_nav, False, False, 12)
        sideheading = Gtk.Box(); sideheading.set_margin_top(25)
        sideheading.pack_start(label(tr('قوائمي'), 'field-label'), True, True, 0)
        sideheading.pack_start(button('+', self.add_list, 'flat'), False, False, 0)
        sidebar.pack_start(sideheading, False, False, 0)
        lists_scroll = Gtk.ScrolledWindow(); lists_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.lists_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); lists_scroll.add(self.lists_box)
        sidebar.pack_start(lists_scroll, True, True, 0)
        sidebar.pack_end(button(tr('الإعدادات'), self.preferences, 'flat'), False, False, 8)
        footer = label(tr('مهامك ومصاريفك، بوضوح'), 'muted'); footer.set_margin_top(14); footer.set_margin_bottom(22); sidebar.pack_end(footer, False, False, 0)
        self.content_stack = Gtk.Stack()
        root.pack_start(self.content_stack, True, True, 0)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin=30)
        self.content_stack.add_named(main, 'tasks')
        top = Gtk.Box(spacing=12); main.pack_start(top, False, False, 0)
        today = datetime.now().strftime('%Y/%m/%d'); top.pack_start(label(tr('يومك، على مهل  ·  ') + today, 'eyebrow'), True, True, 0)
        menu_btn = Gtk.MenuButton(); menu_btn.set_image(Gtk.Image.new_from_icon_name('open-menu-symbolic', Gtk.IconSize.BUTTON)); top.pack_end(menu_btn, False, False, 0)
        menu = Gtk.Menu()
        for title, callback in [(tr('تصدير JSON…'), lambda _: self.transfer('export_json', True, 'json')), (tr('تصدير CSV…'), lambda _: self.transfer('export_csv', True, 'csv')), (tr('استيراد JSON…'), lambda _: self.transfer('import_json', False, 'json')), (tr('استيراد CSV…'), lambda _: self.transfer('import_csv', False, 'csv')), (tr('نسخة احتياطية…'), lambda _: self.transfer('backup', True, 'sqlite3')), (tr('الإعدادات'), self.preferences), (tr('عن نواة واختصاراتها'), self.about), (tr('خروج'), lambda _: application.quit())]:
            i = Gtk.MenuItem(label=title); i.connect('activate', callback); menu.append(i)
        menu.show_all(); menu_btn.set_popup(menu)
        self.heading = label(tr('كل المهام'), 'heading'); main.pack_start(self.heading, False, False, 0)
        self.summary = label('', 'muted'); main.pack_start(self.summary, False, False, 0)
        self.progress = Gtk.ProgressBar(); self.progress.get_style_context().add_class('daily-progress'); main.pack_start(self.progress, False, False, 0)
        quick = Gtk.Box(spacing=10)
        self.entry = Gtk.Entry(placeholder_text=tr('ما الذي تريد إنجازه؟')); self.entry.set_hexpand(True); self.entry.connect('activate', self.create_task)
        quick.pack_start(self.entry, True, True, 0); quick.pack_start(button(tr('＋ إضافة مهمة'), self.create_task, 'suggested-action'), False, False, 0); main.pack_start(quick, False, False, 0)
        self.quick = quick
        controls = Gtk.Box(spacing=10)
        self.search = Gtk.SearchEntry(placeholder_text=tr('ابحث في مهامك…')); self.search.set_hexpand(True); self.search.connect('search-changed', lambda _: self.refresh_tasks())
        controls.pack_start(self.search, True, True, 0)
        self.sort = Gtk.ComboBoxText()
        for key, name in [('smart', tr('الترتيب الذكي')), ('due', tr('تاريخ الاستحقاق')), ('priority', tr('الأولوية')), ('title', tr('العنوان')), ('created', tr('الأحدث'))]: self.sort.append(key, name)
        self.sort.set_active_id('smart'); self.sort.connect('changed', lambda _: self.refresh_tasks()); controls.pack_end(self.sort, False, False, 0)
        main.pack_start(controls, False, False, 0)
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); main.pack_start(scroll, True, True, 0)
        self.taskbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); scroll.add(self.taskbox)
        bottom = Gtk.Box(spacing=10); self.status = label(tr('تُحفظ تغييراتك تلقائيًا'), 'muted'); self.status.set_line_wrap(True); bottom.pack_start(self.status, True, True, 0)
        self.empty_trash = button(tr('إفراغ المحذوفات'), self.purge, 'flat'); bottom.pack_end(self.empty_trash, False, False, 0); main.pack_end(bottom, False, False, 0)
        from .expenses import ExpensesPage
        self.expenses_page = ExpensesPage(self)
        self.content_stack.add_named(self.expenses_page, 'expenses')
        self.content_stack.set_visible_child_name('tasks')
        self.refresh(); self.show_all(); self.empty_trash.set_visible(False)
        self.expenses_page.refresh()

    def preferences(self, *_):
        from .preferences import settings, set_settings
        dialog = Gtk.Dialog(title=tr('الإعدادات'), transient_for=self, modal=True)
        dialog.add_buttons(tr('إلغاء'), Gtk.ResponseType.CANCEL, tr('حفظ'), Gtk.ResponseType.OK)
        box = dialog.get_content_area(); box.set_border_width(24); box.set_spacing(12)
        language = Gtk.ComboBoxText()
        language.append('ar', 'العربية'); language.append('en', 'English')
        language.set_active_id(settings.language)
        currency = Gtk.ComboBoxText()
        currency.append('SAR', tr('ريال سعودي')); currency.append('USD', tr('دولار أمريكي'))
        currency.set_active_id(settings.currency)
        rate = Gtk.Entry(text=str(settings.usd_rate))
        rate.set_direction(Gtk.TextDirection.LTR)
        for caption, widget in [(tr('اللغة'), language), (tr('العملة'), currency), (tr('ريال لكل دولار'), rate)]:
            box.add(label(tr(caption), 'field-label')); box.add(widget)
        hint = label(tr('يُستخدم هذا السعر للعرض والإدخال بالدولار. يمكنك تعديله؛ لا يتحدث تلقائيًا.'), 'muted')
        hint.set_line_wrap(True); hint.set_max_width_chars(46); box.add(hint)
        error = label('', 'error'); box.add(error); dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                set_settings(language.get_active_id(), currency.get_active_id(), rate.get_text())
                break
            except (ValueError, OSError) as exc: error.set_text(tr(str(exc)))
        else:
            dialog.destroy(); return
        dialog.destroy()
        from .preferences import settings
        state = (self.section, self.view, self.list_id, self.heading.get_text(), self.entry.get_text(),
                 self.search.get_text(), self.sort.get_active_id(), self.expenses_page.month,
                 self.expenses_page.last_deleted, self.expenses_page.search.get_text(), self.expenses_page.filter_category)
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL if settings.language == 'ar' else Gtk.TextDirection.LTR)
        self.set_direction(Gtk.TextDirection.RTL if settings.language == 'ar' else Gtk.TextDirection.LTR)
        self.set_title(tr('نواة — مهامك ومصاريفك'))
        self.get_child().destroy(); self.build_ui()
        section, view, list_id, heading, entry, search, sort, month, deleted, expense_search, category = state
        self.entry.set_text(entry); self.search.set_text(search); self.sort.set_active_id(sort)
        self.expenses_page.show_month(month); self.expenses_page.last_deleted = deleted
        self.expenses_page.search.set_text(expense_search); self.expenses_page.filter_category = category
        self.select_view('expenses' if section == 'expenses' else view, list_id, heading if list_id else None)
        if hasattr(self.get_application(), 'setup_tray'): self.get_application().setup_tray()

    def keypress(self, widget, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if self.section == 'expenses':
                if event.keyval in (Gdk.KEY_n, Gdk.KEY_N): self.expenses_page.edit(); return True
                if event.keyval in (Gdk.KEY_f, Gdk.KEY_F): self.expenses_page.search.grab_focus(); return True
            if event.keyval in (Gdk.KEY_n, Gdk.KEY_N): self.entry.grab_focus(); return True
            if event.keyval in (Gdk.KEY_f, Gdk.KEY_F): self.search.grab_focus(); return True
        return False

    def select_view(self, view, list_id=None, name=None):
        if view == 'expenses':
            self.section = 'expenses'
            self.content_stack.set_visible_child_name('expenses')
            self.refresh()
            return
        self.section = 'tasks'
        self.content_stack.set_visible_child_name('tasks')
        self.view = view; self.list_id = list_id
        self.heading.set_text(name or tr(dict((v, n) for v, n, _ in VIEWS).get(view, tr('مهامي'))))
        self.refresh()

    def refresh(self):
        for child in self.lists_box.get_children(): self.lists_box.remove(child)
        for item in self.store.list_lists():
            row = Gtk.Box(spacing=3)
            b = button(item['name'], lambda _, t=item: self.select_view('all', t['id'], t['name']), 'nav-button'); b.set_hexpand(True)
            if self.section == 'tasks' and self.list_id == item['id']: b.get_style_context().add_class('selected')
            row.pack_start(b, True, True, 0); row.pack_start(button('×', lambda _, t=item: self.delete_list(t), 'flat'), False, False, 0); self.lists_box.pack_start(row, False, False, 0)
        self.lists_box.show_all()
        for b in self.nav.get_children():
            c = b.get_style_context(); c.remove_class('selected')
            if (self.section == 'expenses' and b._view == 'expenses') or (self.section == 'tasks' and not self.list_id and b._view == self.view): c.add_class('selected')
        self.refresh_tasks()
        if self.section == 'expenses': self.expenses_page.refresh()

    def refresh_tasks(self):
        if not hasattr(self, 'taskbox'): return
        for child in self.taskbox.get_children(): self.taskbox.remove(child)
        tasks = self.store.list_tasks(view=self.view, list_id=self.list_id, search=self.search.get_text(), sort=self.sort.get_active_id() or 'smart')
        for task in tasks: self.taskbox.pack_start(self.task_row(task), False, False, 0)
        if not tasks:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=65, margin_bottom=65)
            empty.pack_start(label('✧', 'empty-icon'), False, False, 0)
            empty.pack_start(label(tr('مساحة لبداية جديدة') if self.view == 'all' and not self.search.get_text() else tr('لا توجد مهام هنا'), 'empty-title'), False, False, 0)
            empty.pack_start(label(tr('أضف مهمة صغيرة وخذ الخطوة الأولى.') if self.view == 'all' else tr('مهامك ستظهر هنا عندما تناسب هذا العرض.'), 'muted'), False, False, 0)
            for l in empty.get_children(): l.set_xalign(.5)
            self.taskbox.pack_start(empty, True, True, 0)
        active = self.store.list_tasks('all', list_id=self.list_id)
        done = self.store.list_tasks('done', list_id=self.list_id)
        total = len(active) + len(done)
        self.summary.set_text(tr('{count} مهمة في هذا العرض  ·  أنجزت {done} من {total} مهمة').format(count=len(tasks), done=len(done), total=total))
        self.progress.set_fraction(len(done) / total if total else 0)
        self.taskbox.show_all(); self.empty_trash.set_visible(self.view == 'trash'); self.quick.set_sensitive(self.view != 'trash')

    def task_row(self, task):
        row = Gtk.Box(spacing=12, margin=0); row.get_style_context().add_class('task-card')
        check = Gtk.CheckButton(); check.set_active(task['status'] == 'done'); check.set_sensitive(self.view != 'trash')
        check.connect('toggled', lambda cb: self.act(lambda: self.store.complete_task(task['id'], cb.get_active())))
        row.pack_start(check, False, False, 0)
        edit = Gtk.Button(); edit.set_relief(Gtk.ReliefStyle.NONE); edit.set_hexpand(True)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = label(task['title'], 'task-title'); title.set_ellipsize(3)
        if task['status'] == 'done': title.get_style_context().add_class('completed')
        text.pack_start(title, False, False, 0)
        meta = []
        if task['status'] == 'doing': meta.append(tr('قيد التنفيذ'))
        if task.get('priority'): meta.append('● ' + tr('الأولوية') + ' ' + tr(PRIORITIES[task['priority']]))
        if task.get('due_date'): meta.append('◷ ' + task['due_date'])
        steps = task.get('subtasks', [])
        if steps: meta.append(tr('{done}/{total} خطوات').format(done=sum(bool(s['done']) for s in steps), total=len(steps)))
        if task.get('repeat') not in (None, 'none'): meta.append(tr('↻ متكررة'))
        if task.get('reminder_at'): meta.append(tr('تذكير'))
        meta.extend('#' + tag for tag in task.get('tags', []))
        if meta:
            subtitle = label('  ·  '.join(meta), 'task-meta'); subtitle.set_ellipsize(3)
            if task.get('due_date') and task['due_date'] < date.today().isoformat() and task['status'] != 'done': subtitle.get_style_context().add_class('overdue')
            text.pack_start(subtitle, False, False, 0)
        edit.add(text); edit.connect('clicked', lambda _: self.edit_task(task)); row.pack_start(edit, True, True, 0)
        if self.view == 'trash': row.pack_end(button(tr('استعادة'), lambda _: self.act(lambda: self.store.restore_task(task['id'])), 'flat'), False, False, 0)
        else:
            trash = Gtk.Button.new_from_icon_name('user-trash-symbolic', Gtk.IconSize.BUTTON); trash.set_relief(Gtk.ReliefStyle.NONE); trash.set_tooltip_text(tr('نقل إلى المحذوفات')); trash.connect('clicked', lambda _: self.act(lambda: self.store.trash_task(task['id']))); row.pack_end(trash, False, False, 0)
        return row

    def act(self, fn):
        try: fn(); self.refresh()
        except Exception as exc: self.message(tr('تعذّر تنفيذ العملية'), str(exc))

    def create_task(self, _):
        title = self.entry.get_text().strip()
        if not title: self.entry.grab_focus(); return
        def create():
            self.store.create_task(title, list_id=self.list_id, due_date=date.today().isoformat() if self.view == 'today' else None)
            self.entry.set_text('')
        self.act(create)
        self.entry.grab_focus()

    def edit_task(self, task):
        if self.view == 'trash': return
        dialog = TaskDialog(self, self.store.get_task(task['id']))
        while dialog.run() == Gtk.ResponseType.OK:
            try: dialog.save(); break
            except Exception as exc: dialog.error.set_text(str(exc))
        dialog.destroy(); self.refresh()

    def add_list(self, _):
        d = Gtk.Dialog(title=tr('قائمة جديدة'), transient_for=self, modal=True); d.add_button(tr('إلغاء'), Gtk.ResponseType.CANCEL); d.add_button(tr('إضافة'), Gtk.ResponseType.OK)
        entry = Gtk.Entry(placeholder_text=tr('اسم القائمة'), margin=18); entry.set_activates_default(True); d.set_default_response(Gtk.ResponseType.OK); d.get_content_area().add(entry); d.show_all()
        if d.run() == Gtk.ResponseType.OK and entry.get_text().strip(): self.act(lambda: self.store.create_list(entry.get_text().strip()))
        d.destroy()

    def delete_list(self, item):
        if self.confirm(tr('حذف القائمة «') + item['name'] + tr('»؟'), tr('تبقى المهام محفوظة دون قائمة.')):
            self.store.delete_list(item['id'])
            if self.list_id == item['id']: self.select_view('all')
            else: self.refresh()

    def purge(self, _):
        if self.confirm(tr('إفراغ المحذوفات نهائيًا؟'), tr('لا يمكن التراجع عن حذف هذه المهام.')):
            self.act(self.store.purge_trash)

    def confirm(self, title, detail):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=title)
        d.format_secondary_text(detail); d.add_button(tr('إلغاء'), Gtk.ResponseType.CANCEL); d.add_button(tr('تأكيد'), Gtk.ResponseType.OK)
        result = d.run() == Gtk.ResponseType.OK; d.destroy(); return result

    def message(self, title, detail):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, text=title); d.format_secondary_text(detail); d.run(); d.destroy()

    def transfer(self, method, save, ext):
        action = Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
        d = Gtk.FileChooserDialog(title=tr('حفظ ملف') if save else tr('اختيار ملف للاستيراد'), transient_for=self, action=action)
        d.add_buttons(tr('إلغاء'), Gtk.ResponseType.CANCEL, tr('حفظ') if save else tr('استيراد'), Gtk.ResponseType.OK)
        if save: d.set_current_name('nawa-' + date.today().isoformat() + '.' + ext); d.set_do_overwrite_confirmation(True)
        f = Gtk.FileFilter(); f.set_name(ext.upper()); f.add_pattern('*.' + ext); d.add_filter(f)
        response = d.run(); path = d.get_filename(); d.destroy()
        if response != Gtk.ResponseType.OK: return
        try:
            result = getattr(self.store, method)(path)
            self.refresh()
            if save: self.status.set_text(tr('تم حفظ الملف: ') + path)
            else: self.message(tr('اكتمل الاستيراد'), tr('مهام مستوردة: {tasks}\nمصاريف مستوردة: {expenses}\nمهام متخطاة: {skipped}\nتعارضات: {conflicts}').format(tasks=result.get('imported', 0), expenses=result.get('expenses_imported', 0), skipped=result.get('skipped', 0), conflicts=result.get('conflicts', 0) + result.get('expense_conflicts', 0)))
        except Exception as exc: self.message(tr('تعذّر التعامل مع الملف'), str(exc))

    def about(self, _):
        self.message(tr('نواة · مهامك بوضوح'), tr('نواة لتنظيم المهام ومتابعة المصاريف الشهرية.\n\nCtrl+N: إضافة مهمة\nCtrl+F: البحث\n\nاضغط المهمة لتعديلها وإضافة خطوات أو موعد أو تكرار.\nالتذكيرات تعمل ما دام التطبيق مفتوحًا.\nتصدير JSON يحفظ جميع التفاصيل؛ CSV مناسب للجداول.\nليس منتجًا تابعًا لـ Notion.'))

class NawaApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.local.Nawa', flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        from .preferences import settings
        Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL if settings.language == 'ar' else Gtk.TextDirection.LTR)
        provider = Gtk.CssProvider()
        candidates = [Path(__file__).resolve().parent.parent / 'assets' / 'style.css', Path(__file__).resolve().parent / 'assets' / 'style.css']
        for path in candidates:
            if path.exists(): provider.load_from_path(str(path)); break
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.window is None: self.window = MainWindow(self)
        self.window.present()
