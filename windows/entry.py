"""PyInstaller entry point for the native Windows application."""
import os
from pathlib import Path
import sys
import traceback

# PyInstaller's windowed bootloader has no stdout/stderr streams.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')


def run():
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from nawa.selftest import run as self_test
        return self_test(Path(sys.argv[2]))
    from nawa.__main__ import main
    return main()


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except Exception:
        from nawa.paths import data_directory
        folder = data_directory(); folder.mkdir(parents=True, exist_ok=True)
        log = folder / 'startup.log'; log.write_text(traceback.format_exc(), encoding='utf-8')
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 'Nawa could not start. Details:\n' + str(log), 'Nawa', 0x10)
        raise
