"""Run directly for an isolated native X11 dashboard smoke test."""
import json
import os
from pathlib import Path
import tempfile
from datetime import date


def main():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    from nawa.ui import NawaApplication
    from nawa.expenses import ExpenseDialog
    with tempfile.TemporaryDirectory(prefix='nawa-expense-ui-') as folder:
        os.environ['NAWA_DB_PATH'] = str(Path(folder)/'isolated.sqlite3')
        app = NawaApplication(); app.set_application_id('org.local.Nawa.ExpensesTest')
        app.register(None); app.activate(); window = app.window
        assert window.store.path == os.environ['NAWA_DB_PATH']
        finance = window.store.finance
        for month, amount in [('2026-05','1700'), ('2026-06','2100'), ('2026-07','1900'), ('2026-08','2400'), ('2026-09','2700')]:
            finance.create('مصروف تجريبي سابق', amount, 'سكن', month+'-01')
        for title, amount, category, day in [('إيجار المنزل','2200','سكن',1), ('مشتريات المنزل','360.75','طعام',3), ('وقود','120','مواصلات',5), ('اشتراك الإنترنت','230','فواتير',8), ('مقهى','28.50','طعام',12), ('أدوات مكتبية','95','تسوق',16), ('نادي رياضي','180','صحة',18), ('عشاء نهاية الأسبوع','145','ترفيه',21)]:
            finance.create(title,amount,category,f'2026-10-{day:02}')
        finance.set_budget('2026-10','5000')
        window.select_view('expenses'); page = window.expenses_page; page.show_month('2026-10')
        dialog = ExpenseDialog(page)
        dialog.title_entry.set_text('اختبار إضافة'); dialog.amount.set_text('١٢٫٥٠'); dialog.category.get_child().set_text('طعام'); dialog.spent_on.set_text('2026-10-22')
        item = dialog.save(); dialog.destroy()
        assert finance.get(item['id'])['amount_minor'] == 1250
        dialog = ExpenseDialog(page, item); dialog.amount.set_text('13.75'); dialog.title_entry.set_text('اختبار تعديل'); dialog.save(); dialog.destroy()
        assert finance.get(item['id'])['amount_minor'] == 1375
        before = finance.summary('2026-10')['total']; page.remove(item); assert finance.summary('2026-10')['total'] == before-1375
        page.undo(); assert finance.summary('2026-10')['total'] == before
        finance.delete(item['id']); page.refresh()
        page.filter('طعام'); assert len(page.ledger.get_children()) == 2; page.reset_filter()
        page.show_month('2026-09'); assert page.values['total'].get_text() == '2,700.00 ر.س'; page.show_month('2026-10')
        # Exercise the actual budget dialog and its saved value.
        def set_budget():
            for dialog in Gtk.Window.list_toplevels():
                if dialog.get_title() == 'ميزانية الشهر · ر.س':
                    for child in dialog.get_content_area().get_children():
                        if isinstance(child, Gtk.Entry): child.set_text('6000')
                    dialog.response(Gtk.ResponseType.OK)
            return False
        GLib.idle_add(set_budget); page.budget_dialog()
        assert finance.summary('2026-10')['budget'] == 600000
        finance.set_budget('2026-10','5000'); page.refresh()
        window.resize(1220, 900)
        loop = GLib.MainLoop(); GLib.timeout_add(350, lambda: (loop.quit(), False)[1]); loop.run()
        assert window.section == 'expenses'
        active = [b._view for b in window.nav.get_children() if b.get_style_context().has_class('selected')]
        assert active == ['expenses'], active
        assert len(page.daily.hits) == 31 and len(page.trend.hits) == 6
        pix = Gdk.pixbuf_get_from_window(window.get_window(),0,0,window.get_allocated_width(),window.get_allocated_height())
        pix.savev(str(Path(__file__).parent/'screenshot-expenses.png'),'png',[],[])
        report = {'isolated_database':True,'add_edit_delete_undo':True,'arabic_amount':True,'month_switch':True,'category_filter':True,'budget_dialog':True,'charts_rendered':True,'total_minor':finance.summary('2026-10')['total']}
        output = Path(__file__).parent/'verification/expenses-ui.json'; output.parent.mkdir(exist_ok=True); output.write_text(json.dumps(report,indent=2))
        window.destroy(); app.quit(); window.store.close()
        print(json.dumps(report,indent=2))


if __name__ == '__main__': main()
