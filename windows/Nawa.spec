# Run on Windows inside an MSYS2 UCRT64 environment.
from pathlib import Path

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'windows' / 'entry.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'assets'), 'assets'), (str(root / 'LICENSE'), '.')],
    hiddenimports=['gi.repository.Gtk', 'gi.repository.Gdk', 'gi.repository.Gio',
                   'gi.repository.GLib', 'gi.repository.Pango', 'gi.repository.PangoCairo',
                   'gi.repository.GdkPixbuf', 'cairo', 'gi._gi_cairo'],
    hookspath=[],
    hooksconfig={'gi': {'versions': {'Gtk': '3.0', 'Gdk': '3.0'},
                        'languages': ['ar', 'en'],
                        'icons': ['Adwaita', 'hicolor'], 'themes': ['Default']}},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pytest'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='Nawa',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(root / 'assets' / 'nawa.ico'))
collect = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='Nawa')
