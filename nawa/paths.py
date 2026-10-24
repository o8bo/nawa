"""Application directories for Linux and native Windows builds."""
import os
from pathlib import Path
import sys


def data_directory():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'Nawa'
    base = os.environ.get('XDG_DATA_HOME')
    return (Path(base).expanduser() if base and Path(base).is_absolute() else Path.home() / '.local/share') / 'nawa'


def config_directory():
    if sys.platform == 'win32':
        return data_directory()
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'nawa'
