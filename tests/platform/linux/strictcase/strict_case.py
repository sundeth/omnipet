# -*- coding: utf-8 -*-
"""Letter-case strict file access for runs on a case-insensitive disk.

The checkout lives on E: (exFAT). Windows and WSL's /mnt/e both open
"assets/Monsters/X.png" when the file is "assets/monsters/X.png"; the Pi,
Batocera and Android do not. With this installed, every path under ROOT that
only exists in another letter case behaves as it would on Linux: reading it
raises FileNotFoundError, and stat/exists/isfile/isdir/listdir report it
missing. Each such access is appended to LOG (one JSON line: what was asked,
what exists, which call, the first caller in src/ or tests/) so a test run
yields the list of case bugs together with the code that made them.

Covered: open/io.open, os.stat/lstat, os.path.exists/isfile/isdir/getsize/
getmtime, os.listdir/scandir, and pygame.image.load, pygame.mixer.Sound,
pygame.mixer.music.load and pygame.font.Font (SDL opens those files in C,
past Python's open). Writes are never blocked: on Linux a write in another
case creates a second file, which cannot be imitated here; they are logged.
Not covered: os.open and C extensions other than pygame.

Exempt: tmp/, save/, .git/ and __pycache__ folders (they change while tests
run and are never shipped).

    install(root, log_path)        # what sitecustomize.py does from the environment
"""
import builtins
import errno
import io
import json
import os
import sys
import time
import traceback

EXEMPT_TOP = {"tmp", "save", ".git", "logs"}
_real = {}
_state = {"root": None, "log": None, "cache": {}, "seen": set()}


def _norm_root(root):
    return os.path.abspath(root).rstrip("\\/")


def _parts(path):
    """Path components below ROOT, or None when the path is outside or exempt."""
    root = _state["root"]
    if root is None:
        return None
    try:
        p = os.fspath(path)
    except TypeError:
        return None
    if isinstance(p, bytes):
        try:
            p = os.fsdecode(p)
        except Exception:
            return None
    if not isinstance(p, str) or not p:
        return None
    a = os.path.abspath(p)
    if os.name == "nt":
        a_cmp, r_cmp = a.lower(), root.lower()
    else:
        a_cmp, r_cmp = a, root
    if a_cmp != r_cmp and not a_cmp.startswith(r_cmp + os.sep):
        return None
    rest = a[len(root):].replace("\\", "/").strip("/")
    parts = [x for x in rest.split("/") if x]
    if not parts or parts[0] in EXEMPT_TOP or "__pycache__" in parts:
        return None
    return parts


def _names(folder, refresh=False):
    cache = _state["cache"]
    if refresh or folder not in cache:
        try:
            cache[folder] = set(_real["listdir"](folder))
        except OSError:
            cache[folder] = None
    return cache[folder]


def case_miss(path):
    """(asked, found) relative paths when *path* exists only in another letter
    case below ROOT; None when it matches exactly, is missing, or is not ours."""
    parts = _parts(path)
    if not parts:
        return None
    cur = _state["root"]
    for i, part in enumerate(parts):
        if part in (".", ".."):
            return None
        names = _names(cur)
        if names is None:
            return None
        if part not in names:
            names = _names(cur, refresh=True)          # created since it was listed?
            if names is None:
                return None
            if part not in names:
                lower = {n.lower(): n for n in names}
                hit = lower.get(part.lower())
                if hit is None:
                    return None                         # really missing: the call fails on its own
                asked = "/".join(parts)
                found = "/".join(parts[:i] + [hit] + parts[i + 1:])
                return asked, found
        cur = os.path.join(cur, part)
    return None


def _caller():
    root = _state["root"]
    here = os.path.abspath(__file__)
    for frame in reversed(traceback.extract_stack()[:-3]):
        f = os.path.abspath(frame.filename)
        if f == here or not f.lower().startswith(root.lower()):
            continue
        rel = os.path.relpath(f, root).replace("\\", "/")
        if rel.startswith(("src/", "tests/", "main", "utilities/")) and "strictcase" not in rel:
            return f"{rel}:{frame.lineno}"
    return None


def _record(op, miss, blocked=True):
    asked, found = miss
    caller = _caller()
    key = (op, asked, caller)
    if key in _state["seen"]:
        return
    _state["seen"].add(key)
    log = _state["log"]
    if not log:
        return
    line = json.dumps({"op": op, "asked": asked, "found": found, "caller": caller, "blocked": blocked,
                       "pid": os.getpid(), "test": os.environ.get("PYTEST_CURRENT_TEST"),
                       "time": round(time.time(), 1)})
    try:
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def _missing(path, miss):
    return FileNotFoundError(errno.ENOENT, f"No such file or directory (exists only as {miss[1]!r}; "
                                           f"Linux is case-sensitive)", os.fspath(path) if not isinstance(path, int) else path)


def _check(op, path):
    """Raise as Linux would when *path* only matches in another case."""
    if isinstance(path, int):
        return
    miss = case_miss(path)
    if miss:
        _record(op, miss)
        raise _missing(path, miss)


# ---------------------------------------------------------------- wrappers
class _Call:
    """A plain callable object: unlike a function it never binds as a method,
    so it can stand in for os.stat where a class stores it as an attribute
    (pathlib's accessor does: `stat = os.stat`)."""

    def __init__(self, name, real, kind):
        self.name, self.real, self.kind = name, real, kind
        self.__name__ = getattr(real, "__name__", name)
        self.__doc__ = getattr(real, "__doc__", None)

    def __call__(self, *args, **kwargs):
        if kwargs.get("dir_fd") is not None:
            return self.real(*args, **kwargs)        # relative to a folder fd (rmtree), not to the cwd
        path = args[0] if args else kwargs.get("path", kwargs.get("file", "."))
        if self.kind == "listing" and not args and "path" not in kwargs:
            path = "."
        if not isinstance(path, int):
            miss = case_miss(path)
            if miss:
                if self.kind == "open":
                    mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
                    if any(c in str(mode) for c in "wax+"):
                        _record("open-write", miss, blocked=False)
                        return self.real(*args, **kwargs)
                    _record("open", miss)
                    raise _missing(path, miss)
                _record(self.name, miss)
                if self.kind == "bool":
                    return False
                raise _missing(path, miss)
        return self.real(*args, **kwargs)


def _patch_pygame(pg):
    """Wrap the loaders SDL runs in C (they never pass through Python's open)."""
    try:
        real_load = pg.image.load

        def load(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                _check("pygame.image.load", file)
            return real_load(file, *args, **kwargs)
        pg.image.load = load
    except Exception:
        pass
    try:
        Font = pg.font.Font

        class StrictFont(Font):
            def __init__(self, *args, **kwargs):
                f = args[0] if args else kwargs.get("file", kwargs.get("filename"))
                if isinstance(f, (str, bytes, os.PathLike)):
                    _check("pygame.font.Font", f)
                super().__init__(*args, **kwargs)
        StrictFont.__name__ = "Font"
        StrictFont.__qualname__ = "Font"
        pg.font.Font = StrictFont
    except Exception:
        pass
    try:
        Sound = pg.mixer.Sound

        class StrictSound(Sound):
            def __init__(self, *args, **kwargs):
                f = args[0] if args else kwargs.get("file")
                if isinstance(f, (str, bytes, os.PathLike)):
                    _check("pygame.mixer.Sound", f)
                super().__init__(*args, **kwargs)
        StrictSound.__name__ = "Sound"
        StrictSound.__qualname__ = "Sound"
        pg.mixer.Sound = StrictSound
    except Exception:
        pass
    try:
        real_music = pg.mixer.music.load

        def music_load(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                _check("pygame.mixer.music.load", file)
            return real_music(file, *args, **kwargs)
        pg.mixer.music.load = music_load
    except Exception:
        pass


class _PygameHook:
    """Patch pygame's C loaders right after `import pygame` finishes."""

    def find_spec(self, name, path=None, target=None):
        if name != "pygame":
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        import importlib.util
        spec = importlib.util.find_spec("pygame")
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        real_exec = spec.loader.exec_module

        def exec_module(module):
            real_exec(module)
            _patch_pygame(module)
        spec.loader.exec_module = exec_module
        return spec


def install(root, log_path=None):
    """Make file access under *root* letter-case strict for this process."""
    if _state["root"] is not None:
        return
    _state["root"] = _norm_root(root)
    _state["log"] = log_path
    _real.update(open=builtins.open, listdir=os.listdir, scandir=os.scandir, stat=os.stat, lstat=os.lstat)
    builtins.open = io.open = _Call("open", builtins.open, "open")
    os.stat = _Call("os.stat", os.stat, "raise")
    os.lstat = _Call("os.lstat", os.lstat, "raise")
    os.listdir = _Call("os.listdir", os.listdir, "listing")
    os.scandir = _Call("os.scandir", os.scandir, "listing")
    for name in ("exists", "isfile", "isdir"):
        setattr(os.path, name, _Call("os.path." + name, getattr(os.path, name), "bool"))
    for name in ("getsize", "getmtime"):
        setattr(os.path, name, _Call("os.path." + name, getattr(os.path, name), "raise"))
    if "pygame" in sys.modules:
        _patch_pygame(sys.modules["pygame"])
    else:
        sys.meta_path.insert(0, _PygameHook())


def installed():
    return _state["root"] is not None
