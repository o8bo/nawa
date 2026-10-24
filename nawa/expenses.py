"""Bilingual monthly expense dashboard, using native GTK and Cairo charts."""
from .i18n import tr
import calendar
import hashlib
import math
from datetime import date
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, Pango, PangoCairo
from .finance_store import CATEGORIES, shifted_month
from .preferences import formatted, input_amount, currency_symbol, currency_name, display_minor

MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
def category_key(value):
    # Canonical category names stay stable across language changes.
    return next((name for name in CATEGORIES if value == tr(name)), value)


COLORS = ['#3b7059', '#c38b53', '#718bb2', '#a17b9e', '#80a59a', '#d0af6e', '#b57970', '#7d8a5f', '#9696ad']


def color(category):
    index = CATEGORIES.index(category) if category in CATEGORIES else int(hashlib.sha256(category.encode()).hexdigest()[:8], 16) % len(COLORS)
    return COLORS[index % len(COLORS)]


def rgb(cr, value):
    cr.set_source_rgb(*(int(value[i:i+2], 16) / 255 for i in (1, 3, 5)))


def text(cr, value, x, y, size=10, ink='#7b8981', align='left', width=None, bold=False):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(Pango.FontDescription(f'Noto Sans Arabic {"Bold " if bold else ""}{size}'))
    layout.set_text(str(value), -1)
    if width:
        layout.set_width(int(width * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    w, h = layout.get_pixel_size()
    rgb(cr, ink)
    cr.move_to(x - (w / 2 if align == 'center' else w if align == 'right' else 0), y - h / 2)
    PangoCairo.show_layout(cr, layout)


def label(value, style=None):
    out = Gtk.Label(label=value, xalign=0)
    if style:
        out.get_style_context().add_class(style)
    return out


def button(value, fn, style=None):
    out = Gtk.Button(label=value)
    out.connect('clicked', fn)
    if style:
        out.get_style_context().add_class(style)
    return out


class Chart(Gtk.DrawingArea):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.data = None
        self.set_size_request(280, 190 if kind == 'donut' else 150)
        self.set_hexpand(True)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect('draw', self.draw)
        self.connect('motion-notify-event', self.motion)
        self.hits = []

    def motion(self, _, event):
        tip = None
        for x, y, w, h, content in self.hits:
            if x <= event.x <= x + w and y <= event.y <= y + h:
                tip = content
                break
        self.set_tooltip_text(tip)
        return False

    def draw(self, _, cr):
        if not self.data:
            return False
        w, h = self.get_allocated_width(), self.get_allocated_height()
        self.hits = []
        if self.kind == 'donut':
            cx, cy, radius = w / 2, h / 2, min(w, h) * .32
            cr.set_line_width(radius * .30)
            rgb(cr, '#edf1e9'); cr.arc(cx, cy, radius, 0, math.tau); cr.stroke()
            total = self.data['total']
            angle = -math.pi / 2
            if total:
                for category, amount in self.data['categories']:
                    stop = angle + amount / total * math.tau
                    gap = min(.009, (stop - angle) / 4)
                    rgb(cr, color(category)); cr.arc(cx, cy, radius, angle + gap, stop - gap); cr.stroke()
                    angle = stop
            text(cr, formatted(total), cx, cy - 3, 17, '#263b35', 'center', bold=True)
            text(cr, currency_name(), cx, cy + 25, 10, align='center')
            return False
        values = self.data['daily'] if self.kind == 'daily' else [v for _, v in self.data['trend']]
        left, top, right, bottom = 50, 18, w - 12, h - 30
        maximum = max(values, default=0)
        ceiling = max(maximum * 1.15, 100)
        for i in range(4):
            y = bottom - i * (bottom - top) / 3
            rgb(cr, '#e9eee7'); cr.set_line_width(1); cr.move_to(left, y); cr.line_to(right, y); cr.stroke()
            number = float(display_minor(ceiling * i / 3)) / 100
            caption = f'{number / 1000:.1f}k' if number >= 1000 else f'{number:.0f}'
            text(cr, caption, left - 7, y, 8, align='right')
        cell = (right - left) / len(values)
        for i, value in enumerate(values):
            bw = max(2, cell * (.60 if self.kind == 'daily' else .55))
            x = left + i * cell + (cell - bw) / 2
            height = (bottom - top) * value / ceiling
            rgb(cr, '#3b7059' if self.kind == 'daily' or i == len(values) - 1 else '#b6c9bd')
            cr.rectangle(x, bottom - height, bw, height); cr.fill()
            if self.kind == 'daily':
                caption = str(i + 1)
                if i in (0, 6, 13, 20, len(values) - 1):
                    text(cr, caption, x + bw / 2, bottom + 16, 8, align='center')
                tip = tr('اليوم {day}: {amount} {currency}').format(day=i + 1, amount=formatted(value), currency=currency_symbol())
            else:
                month = self.data['trend'][i][0]
                caption = tr(MONTHS[int(month[5:]) - 1])
                text(cr, caption, x + bw / 2, bottom + 16, 8, align='center')
                tip = f'{month}: {formatted(value)} {currency_symbol()}'
            self.hits.append((left + i * cell, top, cell, bottom - top, tip))
        if maximum == 0:
            text(cr, tr('لا توجد مصاريف مسجلة'), (left + right) / 2, (top + bottom) / 2, 11, align='center')
        return False


class ExpenseDialog(Gtk.Dialog):
    def __init__(self, owner, existing=None):
        super().__init__(title=tr('تعديل المصروف') if existing else tr('إضافة مصروف'), transient_for=owner.controller, modal=True)
        self.owner, self.existing = owner, existing
        self.set_default_size(480, 450)
        self.add_buttons(tr('إلغاء'), Gtk.ResponseType.CANCEL, tr('حفظ المصروف'), Gtk.ResponseType.OK)
        self.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class('suggested-action')
        box = self.get_content_area(); box.set_border_width(24); box.set_spacing(10)
        self.title_entry = Gtk.Entry(text=existing['title'] if existing else '', placeholder_text=tr('مثل: مشتريات المنزل'))
        self.amount = Gtk.Entry(text=formatted(existing['amount_minor']).replace(',', '') if existing else '', placeholder_text='0.00')
        self.amount.set_direction(Gtk.TextDirection.LTR)
        self.category = Gtk.ComboBoxText.new_with_entry()
        for name in CATEGORIES:
            self.category.append(name, tr(name))
        self.category.get_child().set_text(tr(existing['category'] if existing else tr('أخرى')))
        today = date.today().isoformat()
        default_day = today if today[:7] == owner.month else owner.month + '-01'
        self.spent_on = Gtk.Entry(text=existing['spent_on'] if existing else default_day, placeholder_text='YYYY-MM-DD')
        self.spent_on.set_direction(Gtk.TextDirection.LTR)
        dates = Gtk.Box(spacing=8); dates.pack_start(self.spent_on, True, True, 0)
        chooser = Gtk.MenuButton(); chooser.set_image(Gtk.Image.new_from_icon_name('x-office-calendar-symbolic', Gtk.IconSize.BUTTON))
        pop = Gtk.Popover.new(chooser); cal = Gtk.Calendar(); pop.add(cal); chooser.set_popover(pop)
        current = date.fromisoformat(self.spent_on.get_text()); cal.select_month(current.month-1, current.year); cal.select_day(current.day)
        def chosen(_):
            y, m, d = cal.get_date(); self.spent_on.set_text(f'{y:04}-{m+1:02}-{d:02}'); pop.hide()
        cal.connect('day-selected-double-click', chosen); dates.pack_start(chooser, False, False, 0)
        self.notes = Gtk.Entry(text=existing['notes'] if existing else '', placeholder_text=tr('اختياري'))
        for caption, widget in [(tr('الوصف'), self.title_entry), (tr('المبلغ') + ' · ' + currency_name(), self.amount), (tr('التصنيف'), self.category), (tr('تاريخ المصروف'), dates), (tr('ملاحظات'), self.notes)]:
            box.pack_start(label(caption, 'field-label'), False, False, 0); box.pack_start(widget, False, False, 0)
        self.error = label('', 'error'); self.error.set_line_wrap(True); box.pack_start(self.error, False, False, 0)
        self.show_all(); self.title_entry.grab_focus()

    def save(self):
        values = dict(title=self.title_entry.get_text(), amount=input_amount(self.amount.get_text(), self.existing['amount_minor'] if self.existing else None),
            category=category_key(self.category.get_child().get_text()), spent_on=self.spent_on.get_text(), notes=self.notes.get_text())
        if self.existing:
            return self.owner.finance.update(self.existing['id'], **values)
        return self.owner.finance.create(**values)


class ExpensesPage(Gtk.Box):
    def __init__(self, controller):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=26)
        self.controller, self.finance = controller, controller.store.finance
        self.month = date.today().strftime('%Y-%m'); self.filter_category = None; self.last_deleted = None
        header = Gtk.Box(spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        titles.pack_start(label(tr('مصاريفك، بصورة أوضح.'), 'heading'), False, False, 0)
        titles.pack_start(label(tr('سجّل، راجع، وافهم أين تذهب مصاريف الشهر.'), 'muted'), False, False, 0)
        header.pack_start(titles, True, True, 0)
        add = button(tr('＋ مصروف جديد'), lambda _: self.edit(), 'suggested-action'); add.set_valign(Gtk.Align.CENTER)
        header.pack_end(add, False, False, 0)
        self.pack_start(header, False, False, 0)
        controls = Gtk.Box(spacing=8)
        controls.pack_start(button('‹', lambda _: self.change_month(-1)), False, False, 0)
        self.month_combo = Gtk.ComboBoxText()
        for i, name in enumerate(MONTHS, 1): self.month_combo.append(str(i), tr(name))
        self.year = Gtk.SpinButton.new_with_range(1900, 9998, 1); self.year.set_numeric(True); self.year.set_width_chars(4)
        self.month_combo.set_active_id(str(int(self.month[5:]))); self.year.set_value(int(self.month[:4]))
        self.month_combo.connect('changed', self.selected_month); self.year.connect('value-changed', self.selected_month)
        controls.pack_start(self.month_combo, False, False, 0); controls.pack_start(self.year, False, False, 0)
        controls.pack_start(button('›', lambda _: self.change_month(1)), False, False, 0)
        controls.pack_start(button(tr('هذا الشهر'), lambda _: self.show_month(date.today().strftime('%Y-%m')), 'flat'), False, False, 0)
        controls.pack_end(button(tr('تصدير CSV'), self.export), False, False, 0)
        controls.pack_end(button(tr('ميزانية الشهر'), self.budget_dialog), False, False, 0)
        self.pack_start(controls, False, False, 0)
        scroll = Gtk.ScrolledWindow(); scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16); scroll.add(content)
        self.pack_start(scroll, True, True, 0)
        metrics = Gtk.Box(spacing=12); self.values = {}
        for key, caption in [('total', tr('إجمالي المصاريف')), ('remaining', tr('المتبقي من الميزانية')), ('comparison', tr('مقارنة بالشهر السابق'))]:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=0); card.get_style_context().add_class('finance-card'); card.set_hexpand(True)
            card.pack_start(label(caption, 'field-label'), False, False, 0)
            value = label('—', 'metric-value'); card.pack_start(value, False, False, 0); self.values[key] = value
            detail = label('', 'muted'); detail.set_line_wrap(True); card.pack_start(detail, False, False, 0); self.values[key + '_detail'] = detail
            metrics.pack_start(card, True, True, 0)
        content.pack_start(metrics, False, False, 0)
        self.budget_bar = Gtk.ProgressBar(); self.budget_bar.get_style_context().add_class('daily-progress'); content.pack_start(self.budget_bar, False, False, 0)
        charts = Gtk.Box(spacing=16)
        distribution = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); distribution.get_style_context().add_class('finance-card'); distribution.set_hexpand(True)
        distribution.pack_start(label(tr('توزيع المصاريف'), 'card-heading'), False, False, 0)
        self.donut = Chart('donut'); distribution.pack_start(self.donut, False, False, 0)
        self.legend = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); distribution.pack_start(self.legend, False, False, 0)
        charts.pack_start(distribution, True, True, 0)
        series = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12); series.set_hexpand(True)
        self.daily, self.trend = Chart('daily'), Chart('trend')
        for caption, chart in [(tr('المصاريف اليومية') + ' · ' + currency_symbol(), self.daily), (tr('آخر ستة أشهر') + ' · ' + currency_symbol(), self.trend)]:
            frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6); frame.get_style_context().add_class('finance-card')
            frame.pack_start(label(caption, 'card-heading'), False, False, 0); frame.pack_start(chart, True, True, 0); series.pack_start(frame, True, True, 0)
        charts.pack_start(series, True, True, 0); content.pack_start(charts, False, False, 0)
        ledger_header = Gtk.Box(spacing=12)
        ledger_header.pack_start(label(tr('سجل المصاريف'), 'card-heading'), False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text=tr('بحث في الوصف أو التصنيف…')); self.search.set_hexpand(True); self.search.connect('search-changed', lambda _: self.refresh_ledger())
        ledger_header.pack_start(self.search, True, True, 0)
        self.clear_filter = button(tr('إلغاء فلتر التصنيف'), self.reset_filter, 'flat'); ledger_header.pack_end(self.clear_filter, False, False, 0)
        self.clear_filter.set_no_show_all(True)
        content.pack_start(ledger_header, False, False, 0)
        self.ledger = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); content.pack_start(self.ledger, False, False, 0)
        footer = Gtk.Box(spacing=8); self.notice = label(tr('العملة') + ': ' + currency_name(), 'muted'); self.notice.set_line_wrap(True)
        footer.pack_start(self.notice, True, True, 0)
        self.undo_button = button(tr('تراجع عن الحذف'), self.undo, 'flat'); footer.pack_end(self.undo_button, False, False, 0)
        self.undo_button.set_no_show_all(True)
        self.pack_end(footer, False, False, 0)
        self.refresh()

    def selected_month(self, *_):
        if self.month_combo.get_active_id():
            self.month = f'{self.year.get_value_as_int():04}-{int(self.month_combo.get_active_id()):02}'
            self.filter_category = None; self.refresh()

    def show_month(self, month):
        self.month = month
        self.year.set_value(int(month[:4])); self.month_combo.set_active_id(str(int(month[5:])))
        self.filter_category = None; self.refresh()

    def change_month(self, delta):
        target = shifted_month(self.month, delta)
        if 1900 <= int(target[:4]) <= 9998: self.show_month(target)

    def refresh(self):
        data = self.finance.summary(self.month)
        self.values['total'].set_text(formatted(data['total']) + ' ' + currency_symbol())
        self.values['total_detail'].set_text(tr('{count} عملية مسجلة').format(count=data['count']))
        if data['budget'] is None:
            self.values['remaining'].set_text(tr('بدون ميزانية'))
            self.values['remaining_detail'].set_text(tr('حدّد مبلغًا لمتابعة المتبقي'))
            self.budget_bar.set_fraction(0)
        else:
            left = data['budget'] - data['total']
            self.values['remaining'].set_text(formatted(abs(left)) + ' ' + currency_symbol())
            self.values['remaining_detail'].set_text((tr('تجاوز الميزانية') if left < 0 else tr('متاح من')) + ' · ' + formatted(data['budget']) + ' ' + currency_symbol())
            self.budget_bar.set_fraction(min(1, data['total'] / data['budget']) if data['budget'] else (1 if data['total'] else 0))
        change = data['total'] - data['previous']
        if data['previous']:
            self.values['comparison'].set_text(('↑ ' if change > 0 else '↓ ' if change < 0 else '') + f"{abs(change) / data['previous'] * 100:.1f}%")
            self.values['comparison_detail'].set_text(tr('زيادة في المصاريف') if change > 0 else tr('انخفاض في المصاريف') if change < 0 else tr('نفس إجمالي الشهر السابق'))
        else:
            self.values['comparison'].set_text('—')
            self.values['comparison_detail'].set_text(tr('لا يوجد إنفاق مسجل للشهر السابق'))
        for chart in [self.donut, self.daily, self.trend]: chart.data = data; chart.queue_draw()
        for child in self.legend.get_children(): self.legend.remove(child)
        if not data['categories']:
            self.legend.pack_start(label(tr('أضف أول مصروف لتظهر تفاصيل التوزيع.'), 'muted'), False, False, 0)
        for category, amount in data['categories']:
            percent = amount / data['total'] * 100
            row = button(f'●  {tr(category)}     {formatted(amount)} {currency_symbol()}    {percent:.1f}%', lambda _, c=category: self.filter(c), 'legend-row')
            row.get_child().set_ellipsize(Pango.EllipsizeMode.END)
            row.set_tooltip_text(tr('عرض مصاريف هذا التصنيف فقط'))
            provider = Gtk.CssProvider(); provider.load_from_data(f'button {{ color: {color(category)}; }}'.encode())
            row.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            self.legend.pack_start(row, False, False, 0)
        self.legend.show_all(); self.refresh_ledger()
        self.undo_button.set_visible(self.last_deleted is not None)

    def refresh_ledger(self):
        if not hasattr(self, 'ledger'): return
        for child in self.ledger.get_children(): self.ledger.remove(child)
        rows = self.finance.list(self.month, category=self.filter_category)
        needle = self.search.get_text().strip().casefold()
        if needle:
            rows = [r for r in rows if needle in '\n'.join([r['title'], r['category'], tr(r['category']), r['notes']]).casefold()]
        self.clear_filter.set_visible(self.filter_category is not None)
        if not rows:
            empty = label(tr('لا توجد مصاريف تطابق هذا العرض. أضف مصروفًا جديدًا للبدء.'), 'muted'); empty.set_line_wrap(True)
            self.ledger.pack_start(empty, False, False, 18)
        for item in rows:
            row = Gtk.Box(spacing=8); row.get_style_context().add_class('finance-ledger-row')
            entry = button(item['title'] + '\n' + tr(item['category']) + ' · ' + item['spent_on'], lambda _, r=item: self.edit(r), 'ledger-title')
            entry.set_hexpand(True); entry.get_child().set_ellipsize(Pango.EllipsizeMode.END); entry.set_tooltip_text(item['notes'] or item['title'])
            row.pack_start(entry, True, True, 0); row.pack_start(label(formatted(item['amount_minor']) + ' ' + currency_symbol(), 'amount'), False, False, 0)
            remove = Gtk.Button.new_from_icon_name('user-trash-symbolic', Gtk.IconSize.BUTTON); remove.set_tooltip_text(tr('حذف المصروف مع إمكانية التراجع'))
            remove.connect('clicked', lambda _, r=item: self.remove(r)); row.pack_end(remove, False, False, 0)
            self.ledger.pack_start(row, False, False, 0)
        self.ledger.show_all()

    def filter(self, category):
        self.filter_category = category; self.refresh_ledger()

    def reset_filter(self, *_):
        self.filter_category = None; self.refresh_ledger()

    def edit(self, existing=None):
        dialog = ExpenseDialog(self, existing)
        while dialog.run() == Gtk.ResponseType.OK:
            try:
                saved = dialog.save(); self.show_month(saved['spent_on'][:7]); break
            except (ValueError, ArithmeticError) as error:
                dialog.error.set_text(str(error))
        dialog.destroy(); self.refresh()

    def remove(self, item):
        self.finance.delete(item['id']); self.last_deleted = item['id']; self.refresh()
        self.notice.set_text(tr('تم حذف المصروف. يمكنك التراجع عن آخر حذف.'))

    def undo(self, *_):
        if self.last_deleted:
            self.finance.restore(self.last_deleted); self.last_deleted = None; self.refresh()
            self.notice.set_text(tr('تمت استعادة المصروف.'))

    def budget_dialog(self, *_):
        dialog = Gtk.Dialog(title=tr('ميزانية الشهر') + ' · ' + currency_symbol(), transient_for=self.controller, modal=True)
        dialog.add_buttons(tr('إلغاء'), Gtk.ResponseType.CANCEL, tr('حفظ'), Gtk.ResponseType.OK)
        box = dialog.get_content_area(); box.set_border_width(20); box.set_spacing(10)
        current = self.finance.summary(self.month)['budget']
        entry = Gtk.Entry(text=formatted(current).replace(',', '') if current is not None else '', placeholder_text=tr('مثل 5000.00'))
        box.add(label(tr('حدّد سقفًا اختياريًا للشهر. امسح الحقل لإزالته.'), 'muted')); box.add(entry)
        error = label('', 'error'); box.add(error); dialog.show_all()
        while dialog.run() == Gtk.ResponseType.OK:
            try: self.finance.set_budget(self.month, input_amount(entry.get_text(), current) if entry.get_text().strip() else ''); break
            except ValueError as exc: error.set_text(str(exc))
        dialog.destroy(); self.refresh()

    def export(self, *_):
        dialog = Gtk.FileChooserDialog(title=tr('تصدير مصاريف الشهر'), transient_for=self.controller, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(tr('إلغاء'), Gtk.ResponseType.CANCEL, tr('تصدير'), Gtk.ResponseType.OK)
        dialog.set_current_name('nawa-expenses-' + self.month + '.csv'); dialog.set_do_overwrite_confirmation(True)
        response = dialog.run(); path = dialog.get_filename(); dialog.destroy()
        if response == Gtk.ResponseType.OK:
            try:
                count = self.finance.export_csv(path, self.month)
                self.notice.set_text(tr('تم تصدير {count} مصروفًا: {path}').format(count=count, path=path))
            except Exception as error: self.controller.message(tr('تعذّر التصدير'), str(error))
