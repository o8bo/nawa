# Bundled dependencies

Nawa is MIT licensed. Its Windows distribution includes Python, GTK 3,
PyGObject, Cairo, GLib, Pango and their runtime dependencies from MSYS2 UCRT64.
These components retain their respective licenses; see the `licenses` directory
and `BUILD-PACKAGES.txt` for the exact packages and versions included by the build.
Libraries are distributed as separate dynamically loaded files in `_internal`.

MSYS2 package metadata and source archives:
https://packages.msys2.org/
https://repo.msys2.org/mingw/sources/

Upstream sources:
https://www.python.org/
https://www.gtk.org/
https://pygobject.gnome.org/
https://www.cairographics.org/
https://pyinstaller.org/ (bootloader license includes a distribution exception)

Nawa source and build scripts: https://github.com/o8bo/nawa
