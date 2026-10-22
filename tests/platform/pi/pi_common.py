# -*- coding: utf-8 -*-
"""Shared set-up for the Raspberry Pi scripts (perf_scenes, smoke, input_check).

Copied to the Pi together with the scripts; needs nothing from tests/.

Sandbox    the game runs from a throw-away folder: symlinks to everything in
           the game folder except save/ (an empty folder, or a COPY of the
           player's save for input_check), so any write the game makes to a
           relative "save/..." path lands in the throw-away folder. Where
           symlinks are impossible (an exFAT disk under WSL) the game runs in
           place with the save folder redirected.
guard      Python-level writes (open for writing, makedirs, remove, rename)
           that resolve into the real game folder raise PermissionError and
           are listed in the report. The player's save, modules and assets
           cannot be changed by a test.
network    every connection to anything but this machine is refused (and
           listed), as tests/support/harness.py does: nothing reaches
           Omninet, Discord or a WiFiCom broker. DNS lookups are refused too,
           so an offline Pi does not stall on them.
"""
import atexit
import builtins
import contextlib
import glob
import io
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PARTY = [("DMC", 1), ("PENC", 1), ("IC", 1), ("VB", 1)]
#: Console lines that mean an exception was caught and logged (harness.ERROR_MARKERS).
ERROR_MARKERS = ("Traceback", "Exception", "Error ", "ERROR", "[!]", "failed", "Failed")
#: Fallback scene list: tests/release/scene_sweep.py SCENES (2026-10-13). The
#: live list is used when scene_sweep.py is found (next to this file, in
#: ../../release/ or in the game folder's tests/release/).
SCENES_FALLBACK = {
    "boot": ("scenes.scene_boot", "SceneBoot"),
    "setup": ("scenes.scene_setup", "SceneSetup"),
    "login": ("scenes.scene_login", "SceneLogin"),
    "egg": ("scenes.scene_eggselection", "SceneEggSelection"),
    "game": ("scenes.scene_maingame", "SceneMainGame"),
    "settings": ("scenes.scene_settingsmenu", "SceneSettingsMenu"),
    "tutorial": ("scenes.scene_tutorial", "SceneTutorial"),
    "error": ("scenes.scene_error", "SceneError"),
    "status": ("scenes.scene_status", "SceneStatus"),
    "feeding": ("scenes.scene_inventory", "SceneInventory"),
    "training": ("scenes.scene_training", "SceneTraining"),
    "sleepmenu": ("scenes.scene_sleep", "SceneSleep"),
    "healing": ("scenes.scene_healing", "SceneHealing"),
    "battle": ("scenes.scene_battle", "SceneBattle"),
    "battle_pvp": ("scenes.scene_battle_pvp", "SceneBattlePvP"),
    "connect": ("scenes.scene_connect", "SceneConnect"),
    "digidex": ("scenes.scene_digidex", "SceneDigidex"),
    "freezer": ("scenes.scene_freezerbox", "SceneFreezerBox"),
    "library": ("scenes.scene_library", "SceneLibrary"),
    "collection": ("scenes.scene_collection", "SceneCollection"),
    "debug": ("scenes.scene_debug", "SceneDebug"),
}
#: Not entered on purpose (scene_sweep: only reachable from an unused demo, UI-10).
SCENES_SKIPPED = {"evolution"}


def _is_game(folder):
    return os.path.isfile(os.path.join(folder, "main.py")) and os.path.isfile(os.path.join(folder, "src", "vpet.py"))


def find_game(path):
    """--game, else $OMNIPET_DIR, else the game folder these scripts sit in
    (<game>/tests/platform/pi), else ~/Games/Omnipet, else ~/Omnipet."""
    given = path or os.environ.get("OMNIPET_DIR")
    if given:
        candidates = [given]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [os.path.join(here, "..", "..", ".."), "~/Games/Omnipet", "~/Omnipet"]
    for candidate in candidates:
        game = os.path.realpath(os.path.expanduser(candidate))
        if _is_game(game):
            return game
    raise SystemExit(f"Omnipet not found in {', '.join(candidates)} (main.py and src/vpet.py); pass --game DIR")


# ---------------------------------------------------------------- sandbox
class Sandbox:
    SKIP = {"save", "tmp", "logs", "Documentation", "tests", ".git", "__pycache__"}

    def __init__(self, game, tmp_root=None, copy_save=False, keep=False, links=True):
        self.game = os.path.realpath(game)
        base = os.path.abspath(os.path.expanduser(tmp_root)) if tmp_root else tempfile.gettempdir()
        os.makedirs(base, exist_ok=True)
        self.dir = tempfile.mkdtemp(prefix="omnipet_pi_", dir=base)
        self.save = os.path.join(self.dir, "save")
        self.keep = keep
        self.linked = self._link() if links else False
        self.root = self.dir if self.linked else self.game
        if copy_save and os.path.isdir(os.path.join(self.game, "save")):
            shutil.copytree(os.path.join(self.game, "save"), self.save,
                            ignore=shutil.ignore_patterns("*.tmp", "__pycache__"))
        os.makedirs(self.save, exist_ok=True)
        atexit.register(self.cleanup)

    def _link(self):
        probe = os.path.join(self.dir, ".probe")
        try:
            os.symlink(self.game, probe)
            os.unlink(probe)
        except (OSError, NotImplementedError, AttributeError):
            return False
        for name in os.listdir(self.game):
            if name in self.SKIP:
                continue
            src = os.path.join(self.game, name)
            if name == "main.py":
                shutil.copy2(src, os.path.join(self.dir, name))     # its folder is the root it uses
            else:
                os.symlink(src, os.path.join(self.dir, name))
        return True

    def cleanup(self):
        if self.keep or not os.path.isdir(self.dir):
            return
        for name in os.listdir(self.dir):
            p = os.path.join(self.dir, name)
            if os.path.islink(p):
                os.unlink(p)                                   # never follow into the game folder
        shutil.rmtree(self.dir, ignore_errors=True)

    def describe(self):
        if self.linked:
            return f"sandbox {self.dir} (symlinks to {self.game}; empty save/)"
        return f"in place in {self.game} (no symlink sandbox); save redirected to {self.save}"


# ---------------------------------------------------------------- write guard
class _Guarded:
    """Callable stand-in (never binds as a method, so pathlib can keep it)."""

    def __init__(self, real, check):
        self.real, self.check = real, check
        self.__name__ = getattr(real, "__name__", "guarded")

    def __call__(self, *args, **kwargs):
        self.check(args, kwargs)
        return self.real(*args, **kwargs)


class WriteGuard:
    def __init__(self, protected, allowed):
        self.protected = os.path.realpath(protected)
        self.allowed = [os.path.realpath(a) for a in allowed]
        self.blocked = []

    def _inside(self, path, base):
        return path == base or path.startswith(base.rstrip(os.sep) + os.sep)

    def _deny(self, target, op):
        if isinstance(target, int):
            return
        try:
            raw = os.fspath(target)
            if isinstance(raw, bytes):
                raw = os.fsdecode(raw)
            if op in ("remove", "unlink", "rename", "replace"):
                # these act on the link itself, not on what it points to
                parent, name = os.path.split(os.path.abspath(raw))
                p = os.path.join(os.path.realpath(parent), name)
            else:
                p = os.path.realpath(raw)
        except TypeError:
            return
        if self._inside(p, self.protected) and not any(self._inside(p, a) for a in self.allowed):
            where = _first_game_frame()
            self.blocked.append(f"{op} {p}" + (f" ({where})" if where else ""))
            raise PermissionError(f"test guard: {op} into the game folder blocked: {p}")

    def install(self):
        def open_check(args, kwargs):
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            if any(c in str(mode) for c in "wax+"):
                self._deny(args[0] if args else kwargs.get("file"), "write")

        def path_check(op):
            def check(args, kwargs):
                if kwargs.get("dir_fd") is not None or kwargs.get("src_dir_fd") is not None:
                    return                        # rmtree's fd walk below a tree already checked
                if op in ("makedirs", "mkdir") and args and os.path.isdir(args[0]):
                    return                        # exist_ok on a folder that is there: no change
                if args:
                    self._deny(args[0], op)
                if op in ("rename", "replace") and len(args) > 1:
                    self._deny(args[1], op)
            return check
        builtins.open = io.open = _Guarded(builtins.open, open_check)
        for op in ("makedirs", "mkdir", "remove", "unlink", "rename", "replace", "rmdir"):
            setattr(os, op, _Guarded(getattr(os, op), path_check(op)))
        shutil.rmtree = _Guarded(shutil.rmtree, path_check("rmtree"))
        return self


def _first_game_frame():
    import traceback
    for frame in reversed(traceback.extract_stack()[:-3]):
        f = frame.filename.replace("\\", "/")
        if "/src/" in f and "pi_common" not in f:
            return f"{f.split('/src/', 1)[1]}:{frame.lineno}"
    return None


# ---------------------------------------------------------------- network
class NetworkGuard:
    LOCAL = ("127.0.0.1", "localhost", "::1")

    def __init__(self):
        self.refused = []

    def install(self):
        real_create, real_connect, real_gai = socket.create_connection, socket.socket.connect, socket.getaddrinfo
        guard = self

        def host_of(address):
            return address[0] if isinstance(address, tuple) else address

        def refuse(address):
            host = host_of(address)
            if host in guard.LOCAL:
                return False
            guard.refused.append(str(address))
            return True

        def create_connection(address, *a, **k):
            if refuse(address):
                raise OSError(f"network disabled by the Pi test ({address})")
            return real_create(address, *a, **k)

        def connect(self, address, *a, **k):
            if not isinstance(address, (str, bytes)) and refuse(address):
                raise OSError(f"network disabled by the Pi test ({address})")
            return real_connect(self, address, *a, **k)

        def getaddrinfo(host, *a, **k):
            if host not in guard.LOCAL and host not in (None, "") and refuse((host, a[0] if a else None)):
                raise socket.gaierror(socket.EAI_NONAME, "network disabled by the Pi test")
            return real_gai(host, *a, **k)
        socket.create_connection = create_connection
        socket.socket.connect = connect
        socket.getaddrinfo = getaddrinfo
        return self

    def summary(self):
        hosts = {}
        for a in self.refused:
            hosts[a] = hosts.get(a, 0) + 1
        return ", ".join(f"{h} x{n}" for h, n in sorted(hosts.items(), key=lambda x: -x[1])[:8])


# ---------------------------------------------------------------- display
def choose_display(driver=None, dummy=False, audio=True):
    """Pick the SDL video driver before pygame starts; returns a description."""
    if not audio or dummy:
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    if dummy:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        return "dummy (headless)"
    if driver:
        os.environ["SDL_VIDEODRIVER"] = driver
        return f"{driver} (--driver)"
    if os.environ.get("SDL_VIDEODRIVER"):
        return f"{os.environ['SDL_VIDEODRIVER']} (SDL_VIDEODRIVER)"
    found = []
    if not os.environ.get("DISPLAY") and os.path.exists("/tmp/.X11-unix/X0"):
        os.environ["DISPLAY"] = ":0"
        xauth = os.path.expanduser("~/.Xauthority")
        if not os.environ.get("XAUTHORITY") and os.path.isfile(xauth):
            os.environ["XAUTHORITY"] = xauth
        found.append("X11 :0")
    if not os.environ.get("WAYLAND_DISPLAY") and hasattr(os, "getuid"):
        run = f"/run/user/{os.getuid()}"
        sockets = sorted(glob.glob(os.path.join(run, "wayland-[0-9]")))
        if sockets:
            os.environ.setdefault("XDG_RUNTIME_DIR", run)
            os.environ["WAYLAND_DISPLAY"] = os.path.basename(sockets[0])
            found.append(f"Wayland {os.environ['WAYLAND_DISPLAY']}")
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return "the game's own choice (x11, wayland, fbcon) with " + \
            (", ".join(found) or f"DISPLAY={os.environ.get('DISPLAY')} WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')}")
    # No desktop session: the game's list (x11, wayland, fbcon) cannot open a
    # window on SDL2, so try the console's KMS/DRM driver.
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    return "kmsdrm (no X11/Wayland session found; use --driver to change)"


# ---------------------------------------------------------------- environment
def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip().strip("\x00")
    except OSError:
        return None


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None


def system_lines(game):
    out = [f"device   {read('/proc/device-tree/model') or platform.machine()}",
           f"os       {platform.platform()}",
           f"python   {sys.version.split()[0]} ({sys.executable})"]
    if sys.version_info < (3, 10):
        out.append("WARNING  the game needs Python 3.10 or newer (it uses `str | None` annotations)")
    temp = read("/sys/class/thermal/thermal_zone0/temp")
    if temp and temp.isdigit():
        out.append(f"cpu      {int(temp) / 1000:.1f} C, governor {read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')}, "
                   f"{(int(read('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq') or 0) // 1000)} MHz")
    thr = run(["vcgencmd", "get_throttled"])
    if thr:
        out.append(f"power    {thr} (0x0 = never throttled or under-voltage)")
    rev = run(["git", "-C", game, "log", "-1", "--format=%h %cd", "--date=short"])
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', read(os.path.join(game, "src", "core", "version.py"))
                  or read(os.path.join(game, "main.py")) or "", re.M)
    out.append(f"game     {game} version {m.group(1) if m else '?'}" + (f" (git {rev})" if rev else ""))
    return out


def scene_list():
    """(scenes dict, source) from scene_sweep.py when found, else the fallback."""
    import importlib.util
    for cand in (os.path.join(HERE, "scene_sweep.py"),
                 os.path.join(HERE, "..", "..", "release", "scene_sweep.py")):
        if os.path.isfile(cand):
            try:
                spec = importlib.util.spec_from_file_location("omnipet_scene_sweep", cand)
                mod = importlib.util.module_from_spec(spec)
                with contextlib.redirect_stdout(io.StringIO()):
                    spec.loader.exec_module(mod)
                return dict(mod.SCENES), os.path.relpath(cand, HERE)
            except Exception:
                continue
    return dict(SCENES_FALLBACK), "built-in copy of scene_sweep.SCENES"


def unlisted_scenes(game, scenes):
    """Scenes in vpet.change_scene's map that the list does not cover."""
    text = read(os.path.join(game, "src", "vpet.py")) or ""
    m = re.search(r"scene_mapping\s*=\s*\{(.*?)\}", text, re.S)
    keys = re.findall(r'"(\w+)"\s*:', m.group(1)) if m else []
    return [k for k in keys if k not in scenes and k not in SCENES_SKIPPED]


# ---------------------------------------------------------------- boot
def patch_save_dir(save, free_mode=True):
    """Point the game's save folder at *save*. Import-time singletons
    (OmninetService's credentials path) read it while `main` is imported, so
    this runs first, on core.game_globals alone."""
    from core import game_globals
    game_globals._get_base_save_dir = lambda: save
    if free_mode:
        game_globals._can_access_save_dir = lambda: True
        game_globals.game_mode = game_globals.GAME_MODE_FREE
    return game_globals


class Game:
    """The game imported from a sandbox, with a temp save and a party."""

    def __init__(self, sandbox, res=(240, 240), fullscreen=True, party=PARTY, quiet=True, log=None):
        self.sandbox = sandbox
        os.chdir(sandbox.root)
        for p in (os.path.join(sandbox.root, "src"), sandbox.root):
            if p not in sys.path:
                sys.path.insert(0, p)
        sink = log if log is not None else io.StringIO()
        ctx = contextlib.redirect_stdout(sink) if quiet else contextlib.nullcontext()
        with ctx:
            import pygame
            patch_save_dir(sandbox.save)     # before `import main`: services bind save paths at import
            import main
            from core import game_globals, runtime_globals
            self.pygame, self.main, self.gg, self.rg = pygame, main, game_globals, runtime_globals
            cfg = game_globals.configuration
            self.default_frame_rate = cfg.frame_rate
            cfg.fullscreen = fullscreen
            cfg.screen_width, cfg.screen_height = res
            cfg.window_width, cfg.window_height = res
            t = time.perf_counter()
            main.setup_pygame()
            main.setup_display()
            self.display_s = time.perf_counter() - t
            from utils.pygame_utils import load_misc_sprites
            from utils.module_utils import load_modules
            t = time.perf_counter()
            runtime_globals.misc_sprites = load_misc_sprites()
            load_modules()
            self.modules_s = time.perf_counter() - t
            self.modules = sorted(runtime_globals.game_modules)
            self.party = self._party(party)
            game_globals.show_tutorial = False
            game_globals.setup_input = game_globals.setup_graphics = False
            game_globals.save_game_mode_preference()
            game_globals.save()

    def _party(self, party):
        from models.game_pet import GamePet
        from utils.module_utils import get_module
        gg = self.gg
        gg.pet_list = []
        wanted = list(party)
        if not any(get_module(m) for m, _ in wanted):     # none of the usual four: any child-stage pets
            wanted = [(m, None) for m in self.modules[:4]]
        for mod_name, version in wanted:
            mod = get_module(mod_name)
            if not mod:
                continue
            child = next((m for m in mod.get_monsters_by_stage(3)
                          if version is None or m.get("version") == version), None)
            if child:
                pet = GamePet(dict(child, module=mod_name))
                pet.hunger = pet.strength = 4
                gg.pet_list.append(pet)
        from utils.pet_utils import refresh_pet_sizes
        refresh_pet_sizes()
        first = get_module("DMC") or (get_module(self.modules[0]) if self.modules else None)
        if first is not None:
            bgs = getattr(first, "backgrounds", None) or []
            gg.game_background = (bgs[0].get("name") if bgs else None) or "ver1"
            gg.background_module_name = first.name
        return [f"{p.name} ({p.module})" for p in gg.pet_list]

    def canvas(self):
        surf = self.rg.render_surface
        disp = self.pygame.display.get_surface()
        return surf.get_size(), (disp.get_size() if disp else None)

    def driver(self):
        try:
            return self.pygame.display.get_driver()
        except Exception:
            return os.environ.get("SDL_VIDEODRIVER", "?")


def error_lines(text, limit=40):
    """Tracebacks (whole) and other error-looking console lines from a log."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines) and len(out) < limit:
        line = lines[i]
        if line.startswith("Traceback"):
            block = [line]
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
            out.append("\n".join(block))
        elif any(m in line for m in ERROR_MARKERS):
            out.append(line)
        i += 1
    return out
