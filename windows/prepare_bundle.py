"""Collect notices and build a portable ZIP after PyInstaller completes."""
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
bundle = root / 'dist' / 'Nawa'
shutil.copy2(root / 'LICENSE', bundle / 'LICENSE')
shutil.copy2(root / 'windows' / 'README.txt', bundle / 'README.txt')
licenses = Path(sys.prefix) / 'share' / 'licenses'
if licenses.is_dir():
    shutil.copytree(licenses, bundle / 'licenses', dirs_exist_ok=True)
packages = subprocess.check_output(['pacman', '-Q'], text=True, encoding='utf-8')
(bundle / 'BUILD-PACKAGES.txt').write_text(packages, encoding='utf-8')
shutil.copy2(root / 'windows' / 'THIRD-PARTY.md', bundle / 'THIRD-PARTY.md')
output = root / 'dist' / 'windows'; output.mkdir(parents=True, exist_ok=True)
shutil.make_archive(str(output / 'Nawa-0.3.1-Windows-x64-Portable'), 'zip', root / 'dist', 'Nawa')
