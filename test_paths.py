"""Default data locations must follow the host platform and explicit overrides."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nawa import paths
from nawa.preferences import settings_path
from nawa.store import Store


class PathsTests(unittest.TestCase):
    def test_windows_data_and_preferences_share_local_appdata(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('nawa.paths.sys.platform', 'win32'), patch.dict(os.environ, {'LOCALAPPDATA': folder}, clear=True):
                expected = Path(folder) / 'Nawa'
                self.assertEqual(paths.data_directory(), expected)
                self.assertEqual(settings_path(), expected / 'preferences.json')
                store = Store()
                try: self.assertEqual(Path(store.path), expected / 'tasks.sqlite3')
                finally: store.close()

    def test_windows_fallback_when_localappdata_is_absent(self):
        with patch('nawa.paths.sys.platform', 'win32'), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(paths.data_directory(), Path.home() / 'AppData/Local/Nawa')

    def test_linux_paths_still_respect_xdg(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('nawa.paths.sys.platform', 'linux'), patch.dict(os.environ, {'XDG_DATA_HOME': folder + '/data', 'XDG_CONFIG_HOME': folder + '/config'}, clear=True):
                self.assertEqual(paths.data_directory(), Path(folder) / 'data/nawa')
                self.assertEqual(paths.config_directory(), Path(folder) / 'config/nawa')

    def test_explicit_paths_win_on_both_platforms(self):
        for platform in ['win32', 'linux']:
            with tempfile.TemporaryDirectory() as folder:
                db = Path(folder) / 'custom.sqlite3'
                config = Path(folder) / 'settings.json'
                with patch('nawa.paths.sys.platform', platform), patch.dict(os.environ, {'NAWA_DB_PATH': str(db), 'NAWA_SETTINGS_PATH': str(config)}, clear=True):
                    self.assertEqual(settings_path(), config)
                    store = Store()
                    try: self.assertEqual(Path(store.path), db)
                    finally: store.close()


if __name__ == '__main__': unittest.main()
