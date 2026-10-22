# -*- coding: utf-8 -*-
"""Shared pieces of the arena season simulation (see README.md).

- ``Server``: a local Omninet (uvicorn) started with the simulation's
  settings against the configured database.
- ``Dev``: the server's development tools (seasons, clock, accounts).
- ``player_service``: an ``OmninetService`` of the game logged in as one
  simulated player (the singleton is bypassed so many players share a
  process).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")
SUPPORT = os.path.join(ROOT, "tests", "support")
ONLINE = os.path.join(ROOT, "tests", "game", "online")
TMP = os.path.join(ROOT, "tmp", "arena_sim")

for _p in (SRC, ROOT, SUPPORT, ONLINE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PORT = int(os.environ.get("ARENA_SIM_PORT", "8765"))
#: The server the players use: the local simulation server by default, or a
#: deployed one (``--url``, e.g. https://dev.omnipet.app.br), which is then
#: never started or stopped here.
URL = os.environ.get("ARENA_SIM_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
DEV_TOKEN = os.environ.get("ARENA_SIM_DEV_TOKEN", "sim-dev-token")
#: An admin account's device key for a server whose dev tools have no token
#: (the deployed dev server); sent as X-Device-Key instead of X-Dev-Token.
ADMIN_KEY = os.environ.get("ARENA_SIM_ADMIN_KEY", "")


def is_local(url=None):
    from urllib.parse import urlparse
    return (urlparse(url or URL).hostname or "") in ("127.0.0.1", "localhost", "::1")


def network_mode():
    """What a headless game may reach (harness.Env): this machine only, or
    anything when the server is a deployed one."""
    return "local" if is_local() else True
OMNINET_DIR = os.environ.get("OMNINET_DIR", "E:/Omninet")
#: Python 3.11+ with Omninet's requirements (the server's interpreter).
OMNINET_PYTHON = os.environ.get("OMNINET_PYTHON", "")
#: Arena store of the simulation server (runtimes, update drop folder).
ARENA_STORAGE = os.environ.get("ARENA_SIM_STORAGE", "./storage/arena_local")


def utcnow():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def log(*parts):
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}]", *parts, flush=True)


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------

class Server:
    """A local Omninet for the simulation.

    Shop sync and automatic seasons are off (the simulation opens its own
    seasons); SQL logging is off; the dev tools answer ``DEV_TOKEN``; the
    season clock ticks every 5 seconds.
    """

    def __init__(self, log_path, python=None, port=PORT, extra_env=None):
        self.log_path = log_path
        self.python = python or OMNINET_PYTHON or sys.executable
        self.port = port
        self.extra_env = extra_env or {}
        self.proc = None

    def env(self):
        env = dict(os.environ)
        env.update({
            "ENVIRONMENT": "dev",
            "DATABASE_ECHO": "false",
            "SHOP_SYNC_ENABLED": "false",
            "ARENA_STORAGE_PATH": ARENA_STORAGE,
            "ARENA_DEV_TOKEN": DEV_TOKEN,
            "ARENA_AUTO_SEASONS": "false",
            "ARENA_TICK_SECONDS": "5",
            "ARENA_DEV_BOTS": "false",
            "ARENA_ENGINE_TIMEOUT_SECONDS": "60",
            "PYTHONIOENCODING": "utf-8",
        })
        env.update(self.extra_env)
        return env

    def healthy(self):
        try:
            return requests.get(f"{URL}/health", timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def start(self, timeout=60):
        if self.healthy():
            log("server already running at", URL)
            return self
        if not is_local():
            raise RuntimeError(f"{URL} does not answer /health")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        out = open(self.log_path, "a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [self.python, "-m", "uvicorn", "omninet.main:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=OMNINET_DIR, env=self.env(), stdout=out, stderr=subprocess.STDOUT)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Omninet exited ({self.proc.returncode}); see {self.log_path}")
            if self.healthy():
                log("server up at", URL, "pid", self.proc.pid)
                return self
            time.sleep(0.5)
        raise RuntimeError("Omninet did not come up in time")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


# ---------------------------------------------------------------------------
# Development tools
# ---------------------------------------------------------------------------

class DevError(RuntimeError):
    pass


class Dev:
    """``/api/v1/dev/arena/...`` with the dev token."""

    def __init__(self, url=None, token=DEV_TOKEN, admin_key=None):
        self.url = (url or URL).rstrip("/")
        admin_key = ADMIN_KEY if admin_key is None else admin_key
        self.headers = {"X-Device-Key": admin_key} if admin_key else {"X-Dev-Token": token}

    def _call(self, method, path, body=None, timeout=120):
        r = requests.request(method, f"{self.url}/api/v1{path}", json=body,
                             headers=self.headers, timeout=timeout)
        if r.status_code >= 400:
            raise DevError(f"{method} {path}: {r.status_code} {r.text[:400]}")
        return r.json()

    def status(self):
        return self._call("GET", "/dev/arena/status")

    def start_season(self, name, length_minutes, restrictions=None, config=None,
                     reward_multiplier=1.0):
        body = {"length_hours": length_minutes / 60.0, "name": name,
                "restrictions": restrictions or None, "config": config or None,
                "reward_multiplier": reward_multiplier, "end_current": True}
        return self._call("POST", "/dev/arena/season/start", body)

    def end_season(self, start_next=False):
        return self._call("POST", "/dev/arena/season/end", {"start_next": start_next})

    def tick(self):
        return self._call("POST", "/dev/arena/tick", {})

    def accounts(self, count, prefix, start=1, coins=None):
        return self._call("POST", "/dev/arena/accounts",
                          {"count": count, "prefix": prefix, "start": start,
                           "coins": coins})["accounts"]

    # Public reads used by the checks
    def get(self, path, headers=None):
        r = requests.get(f"{self.url}/api/v1{path}", headers=headers or {}, timeout=60)
        return r.status_code, (r.json() if r.content else None)


# ---------------------------------------------------------------------------
# A player's game client
# ---------------------------------------------------------------------------

def player_service(device_key, timeout=60):
    """The game's Omninet client, logged in as one simulated player.

    ``OmninetService`` is a singleton; this builds a separate instance with
    its own device key so every simulated player in the process uses the
    game's own request code. ``OMNIPET_OMNINET_URL`` points it at the
    simulation server.
    """
    os.environ["OMNIPET_OMNINET_URL"] = URL
    from services.omninet_service import OmninetService
    svc = object.__new__(OmninetService)
    svc._initialized = True
    svc._device_key = device_key
    svc._device_id = None
    svc._player_id = None
    svc._user_info = None
    svc._timeout = timeout
    svc._credentials_path = os.path.join(TMP, "unused_credentials.json")
    return svc


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)
