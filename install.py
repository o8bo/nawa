#!/usr/bin/env python3
"""Install Nawa privately without sudo. User data lives outside the program."""
from pathlib import Path
import ctypes
import os
import shutil
import subprocess
import tempfile
import argparse
from datetime import datetime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--update', action='store_true', help='Update the private install, retaining the previous program copy')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    share = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    target = share / 'nawa-app'
    share.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not args.update):
        raise SystemExit(f'يوجد تثبيت بالفعل في {target}. لن يتم استبداله تلقائيًا.')
    if target.exists() and not (target/'nawa/__init__.py').is_file():
        raise SystemExit('وجهة التثبيت ليست نسخة نواة معروفة.')
    with tempfile.TemporaryDirectory(prefix='.nawa-install-', dir=share) as scratch:
        staged = Path(scratch) / 'app'
        shutil.copytree(source, staged, symlinks=True,
            ignore=shutil.ignore_patterns('.git', '.github', '__pycache__', 'verification', 'test_*.py', 'screenshot*.png', '*.sqlite3*'))
        (staged / 'launch.sh').chmod(0o755)
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        previous = None
        if target.exists():
            previous = share / ('nawa-app.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            os.rename(target, previous)
        try:
            if rename(-100, os.fsencode(staged), -100, os.fsencode(target), 1):
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error))
        except BaseException:
            if previous is not None and not target.exists(): os.rename(previous, target)
            raise
        if previous is not None: print('Previous program retained:', previous)
    entries = share / 'applications'
    entries.mkdir(parents=True, exist_ok=True)
    entry = entries / 'org.local.Nawa.desktop'
    entry.write_text(f'''[Desktop Entry]
Type=Application
Name=Nawa Tasks
Name[ar]=نواة — مهامي
Comment=Tasks, monthly expenses and charts
Comment[ar]=مهام ومصاريف شهرية ورسوم بيانية
Exec="{target / 'launch.sh'}"
Icon={target / 'assets/nawa.svg'}
Terminal=false
Categories=Utility;
StartupNotify=true
StartupWMClass=Nawa
''', encoding='utf-8')
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(entries)], check=False)
    print('Installed:', target)
    print('Launcher:', entry)


if __name__ == '__main__':
    main()
