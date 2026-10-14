# -*- coding: utf-8 -*-
"""Shared drivers for the battle-mode game tests (checklist BAT-03, BAT-04).

Not a test file (run_tests.py collects ``test_*.py`` only). The tests next to
it import it by name:

    battle_pet(module, stage=3)   a battle-ready GamePet of a module's roster
    run_round(env, encounter)     one adventure round played to its result
    force_outcome(encounter, win) HP that settles a round before it is fought
    FakeAdapter / fake_device()   a DCom adapter that answers as a device
    cell_center(...)              where to tap a grid cell or a party slot

Everything runs on the harness's fake clock (``env.clock_ms``): a frame is
33 ms, and the DCom view's own ``time.time()`` is pointed at the same clock.
"""
import ast
import copy
import os
import random
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SUPPORT = os.path.join(REPO_ROOT, "tests", "support")
if SUPPORT not in sys.path:
    sys.path.insert(0, SUPPORT)
MODULES = os.path.join(REPO_ROOT, "modules")

#: modules/DW1 is being built by another agent (owner, 2026-10-13).
SKIP_MODULES = frozenset({"DW1"})

#: What a player presses during each charge minigame. The battle encounter
#: reads A/LCLICK for the bar and roll minigames and Y/SHAKE for the shake
#: ones (BattleEncounter.handle_event, phase "charge").
CHARGE_PRESS = {
    "Dummy Bar": "A", "Count Bar": "A", "RPM": "A",
    "Xai Roll+Bar": "A", "Xai Bar": "A",
    "Count Match Color": "Y", "Count Match Classic": "Y", "Count Match Z": "Y",
    "Punch": "Y", "Mogera": "Y",
}
#: Frames between two presses: about five a second, a steady mash.
PRESS_EVERY = 6


def release_modules():
    """tests/release/module_audit.py's RELEASE_MODULES, read without importing
    it (the audit reconfigures stdout when imported)."""
    path = os.path.join(REPO_ROOT, "tests", "release", "module_audit.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "RELEASE_MODULES" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise AssertionError("RELEASE_MODULES not found in module_audit.py")


def adventure_modules():
    """Release modules with adventure_mode, installed, DW1 left out.

    Read from each module.json, so it can be called at import time, before
    the game (and its module registry) is loaded.
    """
    import json
    out = []
    for name in release_modules():
        path = os.path.join(MODULES, name, "module.json")
        if name in SKIP_MODULES or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8-sig") as fh:
            if json.load(fh).get("adventure_mode"):
                out.append(name)
    return out


def method_name(module_name):
    """A test method name for a module ("D-3" -> "D_3")."""
    return module_name.replace("-", "_")


def fresh(env, seed=0, pets=(), input_mode=None):
    """env.reset() plus what every battle test wants on top of the fixture.

    The sound is muted after the reset (the save's configuration comes back
    with it): READY then lasts its own frame count instead of waiting on the
    mixer, which keeps the run on the fake clock. ``env.sounds`` still
    records every sound the game asks for.
    """
    env.reset(seed=seed, input_mode=input_mode)
    env.gg.configuration.sound_volume = 0
    env.rg.game_state_update = False
    if pets:
        set_party(env, pets)


#: Log lines that are known asset gaps rather than battle failures: the
#: module-selection view and the HP bar log a missing BattleIcon.png
#: (MOD-01: PENGZ has none; DW1 is in construction). The module audit owns
#: that check.
KNOWN_ASSET_LOGS = ("BattleIcon",)


def battle_errors(env, since=0):
    """Console lines that mean something failed, known asset gaps left out."""
    return [line for line in env.error_logs(since)
            if not any(known in line for known in KNOWN_ASSET_LOGS)]


def installed(module_name):
    """The loaded GameModule, or None (utils.module_utils.get_module raises)."""
    from core import runtime_globals
    return runtime_globals.game_modules.get(module_name)


# ---------------------------------------------------------------- pets
def battle_pet(module_name, stage=3, version=None, name=None, skip=()):
    """A GamePet of *module_name* that may battle: fed, with DP, never asleep.

    The roster's first Digimon of *stage* (and *version*, when given) with a
    power and an attack. ``sleeps``/``wakes`` are cleared so the test does not
    depend on the wall clock (GamePet.should_sleep reads datetime.now()).
    """
    from models.game_pet import GamePet
    from utils.module_utils import get_module
    module = get_module(module_name)
    records = [m for m in module.get_monsters_by_stage(stage)
               if (m.get("power") or 0) > 0 and (m.get("atk_main") or 0) > 0
               and m.get("name") not in skip]
    if name is not None:
        records = [m for m in records if m.get("name") == name] or records
    if version is not None:
        records = [m for m in records if m.get("version") == version] or records
    if not records:
        raise AssertionError(f"{module_name} has no stage-{stage} Digimon that can battle")
    pet = GamePet(dict(records[0], module=module_name))
    pet.hunger = pet.strength = 4
    pet.dp = 4
    pet.sleeps = pet.wakes = None
    return pet


def ensure_battle_record(pet):
    """Give *pet* the battle record a fresh pet of a counts-keeping module
    lacks (findings/battle.md, BAT-F1). Only used where a test says so."""
    for attr in ("battles", "win"):
        if not hasattr(pet, attr):
            setattr(pet, attr, 0)
    return pet


def set_party(env, pets):
    """Make *pets* the whole party and the selection."""
    env.gg.pet_list = list(pets)
    env.rg.selected_pets = list(pets)
    from utils.pet_utils import refresh_pet_sizes
    refresh_pet_sizes()


# ---------------------------------------------------------------- adventure
class RecordingSimulator:
    """Wraps GlobalBattleSimulator to keep the arguments each battle used."""

    def __init__(self):
        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        self.real = GlobalBattleSimulator
        self.calls = []
        recorder = self

        class Recording(GlobalBattleSimulator):
            def __init__(self, *args, **kwargs):
                recorder.calls.append(dict(kwargs))
                super().__init__(*args, **kwargs)

        self.cls = Recording


def force_outcome(encounter, win):
    """Settle the round before it is fought: 99 HP against 1.

    Applied as the charge begins, so the real simulator still fights the
    battle (patterns, hit rates, the log the animation plays) -- it simply
    cannot end the other way: no line here deals 98 damage in twelve turns.
    """
    bp = encounter.battle_player
    strong, weak = 99, 1
    for i in range(len(bp.team1)):
        bp.team1_hp[i] = bp.team1_max_hp[i] = strong if win else weak
    for i in range(len(bp.team2)):
        bp.team2_hp[i] = bp.team2_max_hp[i] = weak if win else strong
    bp.team1_total_hp = bp.team1_max_total_hp = sum(bp.team1_hp[:len(bp.team1)])
    bp.team2_total_hp = bp.team2_max_total_hp = sum(bp.team2_hp[:len(bp.team2)])
    encounter.hp_bar.set_totals(bp.team2_total_hp, bp.team1_total_hp)
    encounter.hp_bar.set_values(bp.team2_total_hp, bp.team1_total_hp)


def run_round(env, encounter, draw_every=1, max_frames=6000, win=None,
              skip_battle=False, on_charge=None):
    """Play one round of an adventure encounter until its result is dealt with.

    The player mashes the module's charge minigame (CHARGE_PRESS) and
    otherwise waits. *win* True/False settles the round (force_outcome);
    None leaves it to the battle. *skip_battle* presses B once the battle
    animation starts, as a player may.

    Returns a dict:
        victory   "Victory"/"Defeat" as the encounter decided it (None if never)
        outcome   "scene" (the encounter asked for another scene), or the phase
                  it moved on to ("level" for the next round, "feeding",
                  "retire_check", "retire_animation"), or "timeout"
        phases    every phase in order
        frames    frames played
        charge    the minigame instance seen during the charge, or None
    """
    from harness import quiet
    rg = env.rg
    surface = rg.render_surface
    minigame = getattr(encounter.module, "battle_minigame", "Dummy Bar")
    press = CHARGE_PRESS.get(minigame)
    phases = [encounter.phase]
    victory = None
    snapshot = None
    charge = None
    outcome = "timeout"
    frame = 0
    with quiet():
        for frame in range(1, max_frames + 1):
            phase = encounter.phase
            if phase == "charge":
                if press and frame % PRESS_EVERY == 0:
                    encounter.handle_event((press, None))
                charge = charge or _charge_instance(encounter, minigame)
            if phase == "battle" and skip_battle:
                encounter.handle_event(("B", None))
            encounter.update()
            if draw_every and (frame % draw_every == 0 or encounter.phase != phase):
                surface.fill((0, 0, 0))
                encounter.draw(surface)
            env.clock_ms += 33
            new = encounter.phase
            if new != phase:
                phases.append(new)
                if new == "charge":
                    if win is not None:
                        force_outcome(encounter, win)
                    if on_charge:
                        on_charge(encounter)
            if victory is None and encounter.victory_status in ("Victory", "Defeat"):
                victory = encounter.victory_status
                snapshot = _snapshot(encounter)
            if rg.game_state_update:
                outcome = "scene"
                break
            if victory is not None and new not in ("battle", "clear", "result"):
                outcome = new
                break
    return {"victory": victory, "outcome": outcome, "phases": phases,
            "frames": frame, "charge": charge, "snapshot": snapshot}


def _snapshot(encounter):
    """What the round decided, taken the moment it was decided -- a
    sequential module rebuilds the encounter for its next round straight
    after the result."""
    bp = encounter.battle_player
    return {
        "area": encounter.area, "round": encounter.round, "boss": encounter.boss,
        "xp": bp.xp, "bonus": bp.bonus,
        "prize_item": getattr(encounter, "prize_item", None),
        "prize_pack": getattr(encounter, "prize_pack", None),
        "currency_reward": getattr(encounter, "currency_reward", None),
        "enemies": [e for e in bp.team2],
        "team1_max_hp": list(bp.team1_max_hp[:len(bp.team1)]),
        "strength": encounter.strength,
    }


def _charge_instance(encounter, minigame):
    attribute = {
        "Dummy Bar": "dummy_charge", "Count Bar": "count_bar", "RPM": "rpm_meter",
        "Count Match Color": "count_match", "Count Match Classic": "count_match_classic",
        "Count Match Z": "count_match_z", "Punch": "shake_punch", "Mogera": "shake_punch",
        "Xai Roll+Bar": "xai_roll", "Xai Bar": "xai_bar",
    }.get(minigame)
    return getattr(encounter, attribute, None) if attribute else None


class ProxyRandom(types.SimpleNamespace):
    """A module's ``random`` with ``random()`` fixed and everything else real."""

    def __init__(self, value, seed=0):
        rng = random.Random(seed)
        super().__init__(random=lambda: value, choice=rng.choice, randint=rng.randint,
                         uniform=rng.uniform, shuffle=rng.shuffle, sample=rng.sample,
                         randrange=rng.randrange, Random=random.Random)


# ---------------------------------------------------------------- taps
def selector_cell_center(selector, line):
    """Screen centre of *line*'s box in a ProtocolSelector (as _index_at reads it)."""
    import pygame
    keys = [key for key, _, _ in selector.entries]
    index = keys.index(line)
    col, row = selector.cells[index]
    x, y = selector._cell_origin(col, row)
    scale = selector._scale()
    box = pygame.Rect(selector.rect.x + x * scale, selector.rect.y + y * scale,
                      selector.CELL * scale, selector.CELL * scale)
    return box.center


def pet_cell_center(selector, index):
    """Screen centre of party slot *index* in a PetSelector."""
    if selector.needs_layout_update:
        selector.update_layout()
    base_x, base_y = selector.cell_positions[index]
    scale = selector.manager.scale_value if selector.manager else (lambda v: v)
    return (selector.rect.x + scale(base_x), selector.rect.y + scale(base_y))


# ---------------------------------------------------------------- DCom
class FakeClock:
    """``time`` for the DCom view, reading the harness's fake clock."""

    def __init__(self, env):
        self.env = env

    def time(self):
        return 1_000_000.0 + self.env.clock_ms / 1000.0

    monotonic = time

    @staticmethod
    def sleep(_seconds):
        raise AssertionError("the DCom view slept on the wall clock")


class FakeSerialPort:
    """What the DCom view reads: lines queued by the fake adapter."""

    def __init__(self):
        self.lines = []
        self.is_open = True
        self.written = []

    @property
    def in_waiting(self):
        return sum(len(line) + 1 for line in self.lines)

    def readline(self):
        return (self.lines.pop(0) + "\n").encode("utf-8") if self.lines else b""

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        self.lines.clear()

    reset_output_buffer = flush


class FakeDevice:
    """A toy on the far side of the cable: answers like a device of its line.

    It is Omnipet's own responder (PacketExchange, the same code a WiFiCom or
    second Omnipet answers with) fed the Digimon a device of that line sends,
    so the reply packets are the line's real layout, checksums and EOLs.
    """

    def __init__(self, battle_format, digimon):
        self.battle_format = battle_format
        self.digimon = digimon
        self.exchanges = []

    def answer(self, command):
        """The adapter's report line for one *command*, as dmcomm prints it."""
        from battle.sim.exchange import PacketExchange
        from wificom.digirom import parse_command
        rom = parse_command(command)
        we_open = rom.turn == 1
        device = PacketExchange(self.battle_format, copy.deepcopy(self.digimon),
                                opens=not we_open)
        sent, received = [], []
        tokens = []
        for index, template in enumerate(rom.packets):
            if not we_open:
                packet = device.next_packet()
                received.append(packet)
                tokens.append("r:" + packet.hex().upper())
            # The adapter resolves its own @/^ operators against what the
            # device sent, exactly as the stock firmware does.
            context = types.SimpleNamespace(sent=received, received=sent)
            ours = bytes.fromhex(PacketExchange._resolve_incoming(context, template.upper(), index))
            sent.append(ours)
            device.receive(ours)
            tokens.append("s:" + ours.hex().upper())
            if we_open:
                packet = device.next_packet()
                received.append(packet)
                tokens.append("r:" + packet.hex().upper())
        self.exchanges.append({"command": command, "sent": sent, "received": received,
                               "device": device})
        return " ".join(tokens)


class FakeAdapter:
    """Stands in for DComController: one adapter on port FAKE0, no serial at all."""

    #: Set by the test: the device the adapter is held against.
    device = None
    #: Every adapter made, for the test to inspect.
    made = []

    def __init__(self):
        self.serial_port = None
        self.device_info = "dmcomm-python 2.1.0 (test double)"
        self.commands = []
        self.connected = False
        FakeAdapter.made.append(self)

    @staticmethod
    def list_all_ports():
        return [("FAKE0", "Test DCom adapter")]

    def find_dcom_devices(self):
        return [("FAKE0", "Test DCom adapter")]

    def connect(self, port, baud=None):
        self.serial_port = FakeSerialPort()
        self.connected = True
        return True

    def disconnect(self):
        if self.serial_port:
            self.serial_port.close()
        self.serial_port = None
        self.connected = False

    def _send_raw(self, data):
        command = data.strip()
        self.commands.append(command)
        if self.serial_port is None:
            raise OSError("adapter not connected")
        # The firmware echoes what it accepted, then reports the exchange --
        # or reports nothing more, with no device held to the adapter.
        self.serial_port.lines.append(f"{command} -[{len(command.split('-')) - 1} packets]")
        if self.device is not None:
            self.serial_port.lines.append(self.device.answer(command))

    def _read_line(self):
        if self.serial_port and self.serial_port.lines:
            return self.serial_port.lines.pop(0)
        return None


def no_real_serial():
    """Patches that make any real serial access fail loudly."""
    from unittest.mock import patch

    def refuse(*_a, **_k):
        raise AssertionError("a test tried to open a real serial port")
    patches = [patch("serial.Serial", refuse)]
    try:
        import serial.tools.list_ports  # noqa: F401
        patches.append(patch("serial.tools.list_ports.comports", lambda *a, **k: []))
    except ImportError:
        pass
    return patches


def native_modules_of(battle_format):
    """Installed release modules that declare *battle_format* (DW1 left out)."""
    from battle.sim import protocol_constants
    from utils.module_utils import get_module
    out = []
    for name in release_modules():
        if name in SKIP_MODULES:
            continue
        module = get_module(name)
        if module is None:
            continue
        declared = protocol_constants.canonical_format(getattr(module, "battle_protocol", "") or "")
        if declared == battle_format or name in protocol_constants.native_modules(battle_format):
            out.append(name)
    return out
