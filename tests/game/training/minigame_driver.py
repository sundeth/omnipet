# -*- coding: utf-8 -*-
"""Helpers for the minigame outcome tests in this folder (not a test file).

Builds a party from real module pets, opens the training scene through the
headless harness, starts a minigame from the menu the way a button does, and
records what the minigame decided at the moment it applied its result: the
verdict, each pet's grade and every pet's stats just after. The tests then
compare those stats with the rules read straight from each module's own
``module.json`` and ``shop.json`` (``expected_training``), so a wrong table
index or a reward that lands on the wrong outcome shows as a number.

    party = make_party(env, ["DM20", "PEN20", "DMGZ", "IC"])
    run = MinigameRun(env, "dummy")
    run.until_charge()
    run.send("A", 14)
    run.finish()                       # fails if the scene never leaves
    run.result.grades[pet], run.after[pet]["effort"] ...
"""
import json
import os
from types import SimpleNamespace

from harness import quiet
from paths import MODULES

#: Pet fields a training can change, copied before and after.
FIELDS = ("effort", "strength", "weight", "trophies", "gcell_points", "reliability",
          "hunger", "disturbance_penalty", "pengz_trainings", "encounter_rotation", "state")

#: How long any minigame may take before the test calls it a hang, in frames
#: of the harness's fake clock (33 ms): five minutes of play.
HANG_FRAMES = 9000

_JSON = {}


def module_json(name, file="module.json"):
    """A module's own data file, read without the game's loader."""
    key = (name, file)
    if key not in _JSON:
        path = os.path.join(MODULES, name, file)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                _JSON[key] = json.load(fh)
        else:
            _JSON[key] = {}
    return _JSON[key]


def has_modules(*names):
    return all(os.path.isfile(os.path.join(MODULES, n, "module.json")) for n in names)


# ---------------------------------------------------------------- the party

def make_pet(module, stage=3, version=None, name=None, attribute=None, **stats):
    """A GamePet of *module* at *stage* (its first form there, or the one
    named, or the first of *attribute*), with the starting stats the outcome
    tests read from: weight well above the floor, no effort or strength,
    G-Cells away from both limits."""
    from models.game_pet import GamePet
    from utils.module_utils import get_module
    mod = get_module(module)
    forms = [m for m in mod.get_monsters_by_stage(stage)
             if (version is None or m.get("version") == version)
             and (name is None or m.get("name") == name)
             and (attribute is None or (m.get("attribute") or "") == attribute)
             and (m.get("atk_main") or 0) > 0]
    if not forms:
        raise LookupError(f"{module}: no stage {stage} form {name or attribute or ''} v{version}")
    with quiet():
        pet = GamePet(dict(forms[0], module=module))
    pet.hunger = 4
    pet.effort = 0
    pet.strength = 0
    pet.weight = min(99, (pet.min_weight or 5) + 30)
    pet.trophies = 0
    pet.disturbance_penalty = 3
    pet.vital_activities = []
    pet.sick = pet.injury = 0
    pet.state = "idle"
    style = module_json(module).get("gcell_style")
    pet.gcell_points = {"DMGZ": 40, "PENGZ": 10}.get(style, 0)
    for key, value in stats.items():
        setattr(pet, key, value)
    return pet


def make_party(env, modules, **stats):
    """Put a party of one pet per module (a name or a (module, kwargs) pair)
    in the save and select all of it, the way choosing them in the menu does."""
    from utils.pet_utils import refresh_pet_sizes
    pets = []
    for entry in modules:
        if isinstance(entry, tuple):
            module, kwargs = entry
        else:
            module, kwargs = entry, {}
        pets.append(make_pet(module, **dict(stats, **kwargs)))
    env.gg.pet_list = list(pets)
    with quiet():
        refresh_pet_sizes()
    env.rg.selected_pets = list(pets)
    return pets


def snapshot(pet):
    out = {f: getattr(pet, f, None) for f in FIELDS}
    out["vital_activities"] = list(getattr(pet, "vital_activities", []) or [])
    return out


def balance(module, currency):
    from utils.currency_utils import get_balance
    return get_balance(module, currency)


# ---------------------------------------------------------------- the rules

def fight_money_gain(module, level):
    """What *module*'s currencies pay a training at *level*, from shop.json."""
    out = {}
    for currency in module_json(module, "shop.json").get("currency") or []:
        gains = list(currency.get("training_gain") or []) + [0, 0, 0, 0]
        out[currency["name"]] = gains[level]
    return out


def expected_training(module, before, grade, won, phase2=False, anguirus=False):
    """The stats GamePet.finish_training must leave, from module.json:
    the three tables indexed by the outcome (a lost training pays its grade's
    row: Bad for all but Mogera's lost Phase 2, a Good),
    Reliability on a success, the G-Cells in the module's style, the
    disturbance penalty a success forgives."""
    from core import constants
    data = module_json(module)
    level = max(0, min(3, int(grade)))
    exp = dict(before)
    exp["effort"] = before["effort"] + data["training_effort_gain"][level]
    gain = data["training_strength_gain"][level]
    exp["strength"] = (before["strength"] + gain) if gain >= 0 else None   # None: "the meter, filled"
    floor = 1 if data.get("care_allow_below_min_weight") else (before["min_weight"] or 0)
    exp["weight"] = max(floor, before["weight"] - data["training_weight_loss"][level])
    if won:
        exp["reliability"] = max(constants.RELIABILITY_MIN, min(
            constants.RELIABILITY_MAX,
            (before["reliability"] or 0) + data.get("reliability_minigame_success", 0)))
        if before["disturbance_penalty"] >= 2:
            exp["disturbance_penalty"] = before["disturbance_penalty"] - 2
    style = data.get("gcell_style") or ("DMGZ" if data.get("use_gcells") else "Disabled")
    points = 0
    if style == "DMGZ":
        if won:
            points = data.get("gcell_training_success", 0)
        else:
            points = data.get("gcell_training_phase2_failure" if phase2
                              else "gcell_training_phase1_failure", 0)
        cap = 472
    elif style == "PENGZ":
        table = data.get("gcell_training_gain_anguirus" if anguirus else "gcell_training_gain")
        points = table[min(level, len(table) - 1)]
        cap = 14 * data["gcell_points_per_cell"][before["stage"]]
    if style != "Disabled":
        exp["gcell_points"] = max(0, min(cap, (before["gcell_points"] or 0) + points))
    exp["state"] = "happy2" if won else "angry"
    exp["vital_activities"] = list(before["vital_activities"])
    if won and "training" not in exp["vital_activities"]:
        exp["vital_activities"].append("training")
    return exp


# ---------------------------------------------------------------- a run

class MinigameRun:
    """One minigame, started from the training menu and played to its end."""

    def __init__(self, env, key, bonus=False):
        from scenes.scene_training import BONUS_MODES, TRAINING_MODES
        self.env = env
        self.key = key
        env.gg.configuration.sound_volume = 0      # READY timed on the fake clock
        self.game = env.game("training")
        env.frames(self.game, 2)
        self.scene = self.game.scene
        if bonus:
            with quiet():
                self.scene.show_view("bonus")
        self.spec = (BONUS_MODES if bonus else TRAINING_MODES)[key]
        self.take_before()
        with quiet():
            self.scene.select_training(key)
        self.attach()

    def take_before(self):
        """Take the 'before' picture of the whole party (the pets that play
        and the ones that do not)."""
        self.party = list(self.env.rg.selected_pets or self.env.gg.pet_list)
        self.before = {pet: snapshot(pet) for pet in self.party}
        for pet in self.party:
            self.before[pet]["stage"] = pet.stage
            self.before[pet]["min_weight"] = pet.min_weight
        self.result = None
        self.after = None
        self.applied = 0
        self.frames_played = 0

    def attach(self):
        """Hook the minigame the training scene is now playing."""
        self.scene = self.game.scene
        self.mode = getattr(self.scene, "mode", None)
        assert self.mode is not None, f"{self.key} did not start"
        self.pets = list(self.mode.pets)
        self._hook()

    @classmethod
    def on(cls, env, game, key):
        """A run for a minigame the caller starts itself on *game* (by
        tapping its button, say): the party is pictured now, and
        ``attach()`` hooks the minigame once it has started."""
        from scenes.scene_training import BONUS_MODES, TRAINING_MODES
        run = cls.__new__(cls)
        run.env, run.key, run.game = env, key, game
        run.scene = game.scene
        run.spec = BONUS_MODES.get(key) or TRAINING_MODES[key]
        env.gg.configuration.sound_volume = 0
        run.take_before()
        return run

    def _hook(self):
        mode = self.mode
        original = mode.apply_training_results

        def apply():
            verdict = SimpleNamespace(
                won=bool(mode.check_victory()),
                grade=mode.get_attack_count(),
                grades={pet: mode.grade_for(pet) for pet in mode.pets},
                won_for={},
                phase2=bool(getattr(mode, "phase2_reached", False)),
            )
            verdict.won_for = {pet: bool(mode.won_for(pet, verdict.won)) for pet in mode.pets}
            paid = original()
            verdict.paid = list(paid or [])
            self.applied += 1
            self.result = verdict
            self.after = {pet: snapshot(pet) for pet in self.party}
            return paid
        mode.apply_training_results = apply

    # -- driving
    @property
    def phase(self):
        return getattr(self.mode, "phase", None)

    def left(self):
        """Whether the scene has left the training (back to the game)."""
        return type(self.game.scene).__name__ != "SceneTraining"

    def frames(self, n=1):
        self.env.frames(self.game, n)
        self.frames_played += n

    def send(self, action, times=1, data=None):
        for _ in range(times):
            with quiet():
                self.game.scene.handle_event((action, data))

    def until(self, predicate, limit=HANG_FRAMES, what="condition"):
        """Run frames until *predicate()*; AssertionError past *limit*."""
        for _ in range(limit):
            if predicate():
                return
            if self.left():
                raise AssertionError(f"{self.key}: left the scene before {what}")
            self.frames(1)
        raise AssertionError(f"{self.key}: no {what} within {limit} frames")

    def until_charge(self):
        self.until(lambda: self.phase == "charge", what="charge phase")

    def finish(self, limit=HANG_FRAMES, step=None):
        """Play on (calling *step* each frame) until the scene leaves the
        training; AssertionError if it never does -- a hang."""
        for _ in range(limit):
            if self.left():
                return self.frames_played
            if step is not None:
                step()
            self.frames(1)
        raise AssertionError(f"{self.key} never finished: stuck in phase {self.phase!r} "
                             f"after {limit} frames")
