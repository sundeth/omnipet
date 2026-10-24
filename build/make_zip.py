#!/usr/bin/env python
"""Zip a release folder so every platform extracts it correctly.

    python make_zip.py <folder> <zip>

The build scripts used .NET's ZipFile.CreateFromDirectory, which under
Windows PowerShell 5.1 writes entry names with backslashes and no Unix
permissions: Linux unzip warns and exits 1, Python's zipfile extracts
thousands of loose files named "assets\\x.png", and after unzip the folders
are not writable and launch.sh/setup.sh are not executable (an upgrade
with ``unzip -o`` also strips an installed launch.sh). Here every entry uses
forward slashes, folders (empty ones too: modules/, save/) are 755, files
644, and scripts (*.sh, or anything starting with "#!") 755. The folder's
contents go at the top of the zip, as before.
"""
import os
import stat
import sys
import time
import zipfile

DIR_MODE = 0o755
FILE_MODE = 0o644
EXEC_MODE = 0o755
UNIX = 3


def is_script(path):
    if path.lower().endswith(".sh"):
        return True
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def entry(name, mode, kind, mtime):
    info = zipfile.ZipInfo(name, time.localtime(max(mtime, 315532800))[:6])
    info.create_system = UNIX
    info.external_attr = ((kind | mode) << 16) | (0x10 if kind == stat.S_IFDIR else 0)
    info.compress_type = zipfile.ZIP_STORED if kind == stat.S_IFDIR else zipfile.ZIP_DEFLATED
    return info


def make_zip(folder, target):
    folder = os.path.abspath(folder)
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            rel_root = os.path.relpath(root, folder).replace(os.sep, "/")
            if rel_root != ".":
                zf.writestr(entry(rel_root + "/", DIR_MODE, stat.S_IFDIR, os.path.getmtime(root)), b"")
            for name in sorted(files):
                path = os.path.join(root, name)
                arc = name if rel_root == "." else rel_root + "/" + name
                info = entry(arc, EXEC_MODE if is_script(path) else FILE_MODE, stat.S_IFREG,
                             os.path.getmtime(path))
                with open(path, "rb") as fh:
                    zf.writestr(info, fh.read())
                count += 1
    return count


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    folder, target = sys.argv[1], sys.argv[2]
    if not os.path.isdir(folder):
        sys.exit("not a folder: %s" % folder)
    if os.path.exists(target):
        os.remove(target)
    count = make_zip(folder, target)
    print("make_zip: %d files -> %s" % (count, target))


if __name__ == "__main__":
    main()
