#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Care crawler: lifespan, sickness and injury, as each module declares (MOD-21).

For each release module, pets built from the module's own records live on
the game's own per-minute code (GamePet.update on a virtual clock: the
Android parity harness's Foreground, tests/unit/android/android_parity.py),
with "perfect care" between minutes where a check needs the pet otherwise
untouched: fed, strong, no poop, no ailment, no care mistakes.

Lifespan (utils.lifespan_rules, the module's `lifespan_rule`)
    None           a cared-for pet of the highest raisable stage is alive
                   after 16 days
    Old Age        it dies, unsaved, the minute its life reaches
                   `death_old_age` days
    Activity Time  an Adult that cannot evolve goes near-death two hours
                   after its evolution time and, nobody pressing, dies; an
                   Ultimate at 144 hours; a rescued one is near death again
                   an hour later; a Baby I that evolves lives through its day
    Age 5          Hunger and poop count down twice as fast from 5 days
                   old (Strength not), and 16 care mistakes kill only then
    Evolution Window  from the rule's stage a form left past its evolution
                   time without a route met has failed for good; a form of
                   the stage before keeps waiting

Sickness and injury (utils.ailments)
    causes     the poop pile, 99 G, the Nth disturbance, a won and a lost
               battle (every roll forced to hit) give the kind the module's
               effect fields name; a battle only ever injures
    counts     each kind kills at its own death_max_*, not one before
               (0: never), and the death save gives one back
    timers     an untreated sickness / injury kills after its own
               death_*_timer awake minutes, on the live clock
    gates      battling and training with each kind, as the module allows
    heal       the Heal menu cures in heal_doses doses; the module's cure
               items heal their kind; evolving clears everything

    python -B tests/release/care_crawl.py [MODULE ...] [--out DIR] [--quiet]

Writes <out>/care_crawl.json and care_crawl.md (default
tmp/release-reports/care/). Exit 1 when a check fails.
"""
import argparse
import collections
import json
import os
import sys
import time
import traceback
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.dirname(HERE)
ROOT = os.path.dirname(TESTS)
for _p in (os.path.join(TESTS, "unit", "android"), os.path.join(TESTS, "support"), os.path.join(ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from android_parity import (Clock, Foreground, availability, load_module, local_ts,  # noqa: E402
                            release_modules)
from core import game_globals  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from utils import ailments, lifespan_rules  # noqa: E402

DAY = 24 * 60
#: The virtual morning every life starts on.
MORNING = (2026, 9, 14, 8)
#: Minutes between rounds of perfect care.
CARE_EVERY = 10
HIT = SimpleNamespace(random=lambda: 0.0, randint=lambda a, b: a, choice=lambda s: s[0],
                      uniform=lambda a, b: a, shuffle=lambda s: None, sample=lambda s, k: list(s)[:k])


# ----------------------------------------------------------------------------
# Pets
# ----------------------------------------------------------------------------

def forms(module, stage):
    """Raisable forms of *stage* (Normal, not special), monster.json order."""
    return [dict(m, module=module.name) for m in module.get_all_monsters()
            if m.get("stage") == stage and not m.get("special") and availability(m) == "Normal"]


def fighter(module):
    """A raisable Child, Adult or Perfect that can fall ill and battle."""
    for stage in (3, 4, 5):
        for m in forms(module, stage):
            if int(m.get("heal_doses", 1) or 0) > 0 and m.get("power") and m.get("atk_main"):
                return m
    return None


def full(p):
    return max(1, int(getattr(p, "stomach", 0) or 4))


def care(p, keep_ailment=False):
    """Perfect care: fed and strong, no poop, no care mistakes, no ailment
    (unless *keep_ailment*), weight off 99 G."""
    p.hunger = p.strength = full(p)
    p.hunger_empty_minutes = p.strength_empty_minutes = 0
    p.starvation_counter = p.debilitation_counter = 0
    p.care_food_mistake_timer = p.care_strength_mistake_timer = p.care_sleep_mistake_timer = 0
    p.mistakes = 0
    if getattr(p, "use_condition_hearts", False):
        p.condition_hearts = getattr(p, "condition_hearts_max", 4)
    p.poop_mistake_timers = []
    game_globals.poop_list.clear()
    if p.weight >= 90:
        p.weight = max(int(getattr(p, "min_weight", 1) or 1), 10)
    if not keep_ailment:
        ailments.cure(p)


class Deaths:
    """Records each pet's death: the minute of its life and why."""

    def __init__(self, stack, modules):
        self.log = []
        original = GamePet._die
        deaths = self

        def die(pet, now=None, late=0.0):
            module = modules.get(pet.module)
            deaths.log.append(dict(
                pet=pet.name, stage=pet.stage, life=getattr(pet, "life_minutes", 0),
                evol=pet._evol_minutes, time=pet.time, cause=getattr(pet, "death_cause", "") or "",
                lifespan=lifespan_rules.death_cause(pet, module, pet.can_evolve) if module else "",
                ailment=ailments.death_cause(pet, module) if module else "", mistakes=pet.mistakes))
            return original(pet, now, late)
        stack.enter_context(patch.object(GamePet, "_die", die))


class Life:
    """One Foreground run: a clock at MORNING, a pet, deaths recorded."""

    def __init__(self, crawler):
        self.c = crawler
        self.clock = Clock(local_ts(*MORNING))
        self.start = self.clock.wall()

    def __enter__(self):
        self.stack = ExitStack()
        self.fg = self.stack.enter_context(Foreground({self.c.name: self.c.module}, self.clock))
        self.deaths = Deaths(self.stack, {self.c.name: self.c.module})
        return self

    def __exit__(self, *exc):
        self.stack.close()
        return False

    def pet(self, record, **fields):
        p = self.fg.pet(record, "crawl", elapsed=17)
        p.__dict__.update(fields)
        return p

    def run(self, p, minutes, cared=True, keep_ailment=False, stop=None):
        """*minutes* more of life (from now), cared for every CARE_EVERY
        minutes; *stop(p)* ends it early. The minutes actually run."""
        done = 0
        while done < minutes:
            step = min(CARE_EVERY, minutes - done)
            self.fg.run_until(self.clock.wall() + step * 60)
            done += step
            if p.state == "dead" or p not in game_globals.pet_list:
                break
            if cared:
                care(p, keep_ailment)
            if stop and stop(p):
                break
        return done

    def minutes(self, p, n):
        """Exactly *n* minute ticks, nothing else."""
        self.fg.run_until(self.clock.wall() + n * 60)


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------

class Crawler:
    def __init__(self, name):
        self.name = name
        self.module = load_module(name)
        self.rows = []

    def add(self, area, check, ok, detail, result=None):
        self.rows.append(dict(module=self.name, area=area, check=check,
                              result=result or ("ok" if ok else "fail"), detail=detail))

    def skip(self, area, check, detail):
        self.add(area, check, True, detail, result="skip")

    def guard(self, area, check, fn):
        try:
            fn()
        except Exception as exc:  # one broken check must not stop the crawl
            self.add(area, check, False, f"{exc!r}: {traceback.format_exc()[-800:]}", result="error")

    # -- lifespan -----------------------------------------------------------

    def lifespan(self):
        rule = lifespan_rules.rule(self.module)
        self.add("lifespan", "rule", True, f"lifespan_rule {rule}", result="info")
        checks = {"None": [("lives on", self.lives_on)],
                  "Old Age": [("old age", self.old_age)],
                  "Activity Time": [("adult that cannot evolve", self.activity_adult),
                                    ("ultimate", self.activity_ultimate),
                                    ("rescued, near death again", self.activity_rescue),
                                    ("baby that evolves lives", self.activity_baby)],
                  "Age 5": [("needs from age 5", self.age5_needs), ("16 mistakes from age 5", self.age5_mistakes)]}
        for window in lifespan_rules.WINDOW_STAGES:
            checks[window] = [("the window closes", self.window_closes), ("earlier stages wait", self.window_waits)]
        for check, fn in checks[rule]:
            self.guard("lifespan", check, fn)

    def top_form(self):
        for stage in (8, 7, 6, 5, 4, 3):
            fs = forms(self.module, stage)
            if fs:
                return fs[0]
        return None

    def lives_on(self):
        record = self.top_form()
        with Life(self) as life:
            p = life.pet(record)
            ran = life.run(p, 16 * DAY)
            alive = p.state != "dead" and p in game_globals.pet_list
            self.add("lifespan", "lives on", alive,
                     f"{record['name']} (stage {record['stage']}): {ran // DAY} days, "
                     + ("alive" if alive else f"died: {life.deaths.log[-1:]}"))

    def old_age(self):
        days = int(getattr(self.module, "death_old_age", 0) or 0)
        record = forms(self.module, 1)[0] if forms(self.module, 1) else self.top_form()
        with Life(self) as life:
            p = life.pet(record)
            life.run(p, (days + 1) * DAY, stop=lambda q: q.state == "dead")
            death = life.deaths.log[0] if life.deaths.log else None
            ok = bool(death) and death["life"] == days * DAY and not p.dying
            self.add("lifespan", "old age", ok,
                     f"death_old_age {days}: died at life minute {death and death['life']} "
                     f"(expected {days * DAY}) as {death and death['pet']}" if death else "never died")

    def stuck_adult(self):
        """An Adult that, with no battles won, has no route to take."""
        for record in forms(self.module, 4):
            if not record.get("evolve") or not record.get("time"):
                continue
            with Life(self) as life:
                p = life.pet(record, _evol_minutes=int(record["time"]))
                if not p.can_evolve():
                    return record
        return None

    def activity_adult(self):
        record = self.stuck_adult()
        if record is None:
            return self.skip("lifespan", "adult that cannot evolve", "every Adult has a route met at once")
        with Life(self) as life:
            # Awake throughout: no death check runs while it sleeps.
            p = life.pet(record, sleeps=None, wakes=None)
            deadline = lifespan_rules.activity_deadline(p)
            life.run(p, deadline + 90, stop=lambda q: q.state == "dead")
            death = life.deaths.log[0] if life.deaths.log else None
            # Near death at the deadline; nobody presses, so it dies at the next minute.
            ok = (death is not None and deadline <= death["evol"] <= deadline + 2
                  and death["cause"] in ("", "lifespan") and death["lifespan"] == "lifespan")
            self.add("lifespan", "adult that cannot evolve", ok,
                     f"{record['name']}: time {p.time}, deadline {deadline}; died at evolution minute "
                     f"{death['evol']} ({death['cause'] or death['lifespan']})" if death else
                     f"{record['name']}: time {p.time}, deadline {deadline}; never died")

    def activity_ultimate(self):
        fs = [m for m in forms(self.module, 6) if not m.get("time")]
        if not fs:
            return self.skip("lifespan", "ultimate", "no Ultimate without an evolution time")
        record = fs[0]
        with Life(self) as life:
            p = life.pet(record, sleeps=None, wakes=None)
            life.run(p, lifespan_rules.ACTIVITY_NO_TIME + 60, stop=lambda q: q.state == "dead")
            death = life.deaths.log[0] if life.deaths.log else None
            ok = death is not None and abs(death["evol"] - lifespan_rules.ACTIVITY_NO_TIME) <= 2
            self.add("lifespan", "ultimate", ok,
                     f"{record['name']}: died at evolution minute {death and death['evol']} "
                     f"(144 h = {lifespan_rules.ACTIVITY_NO_TIME})" if death else f"{record['name']}: never died")

    def activity_rescue(self):
        record = self.stuck_adult()
        if record is None:
            return self.skip("lifespan", "rescued, near death again", "no Adult that cannot evolve")
        if self.module.death_save_by == "Nothing":
            return self.skip("lifespan", "rescued, near death again", "no death save")
        with Life(self) as life:
            p = life.pet(record, sleeps=None, wakes=None)
            deadline = lifespan_rules.activity_deadline(p)
            p._evol_minutes = deadline - 1
            life.minutes(p, 1)
            first = p.dying
            p.death_save_b_counter = p.death_save_shake_counter = 0
            with patch("models.game_pet.random", HIT):
                p.update_death_save(1)
            saved = not p.dying and p.state != "dead" and p.death_save_immunity == 60
            life.run(p, 59)
            calm = not p.dying
            again = False
            for _ in range(3):
                life.minutes(p, 1)
                if p.dying:
                    again = True
                    break
            self.add("lifespan", "rescued, near death again", first and saved and calm and again,
                     f"{record['name']}: near death {first}, saved with the hour {saved}, "
                     f"quiet through it {calm}, near death again after it {again}")

    def activity_baby(self):
        """A pet started as the game starts it (its egg charged with the
        device's DigiSoul Plate: utils_unlocks.charge_egg_plates) evolves
        through its first day without dying."""
        from utils.utils_unlocks import charge_egg_plates
        eggs = [m for m in forms(self.module, 0) if m.get("evolve")]
        if not eggs:
            return self.skip("lifespan", "baby that evolves lives", "no egg")
        with Life(self) as life:
            p = life.pet(eggs[0])
            charge_egg_plates(self.name, p)
            life.run(p, DAY)
            alive = p.state != "dead" and p in game_globals.pet_list
            self.add("lifespan", "baby that evolves lives", alive,
                     f"{eggs[0]['name']} (DNA {p.dna if p.stage == 0 else 'fed'}) after a day: {p.name} "
                     f"(stage {p.stage}), " + ("alive" if alive else f"died: {life.deaths.log[-1:]}"))

    def age5_needs(self):
        record = fighter(self.module) or self.top_form()
        with Life(self) as life:
            p = life.pet(record, life_minutes=5 * DAY - 3, sleeps=None, wakes=None, hunger=4,
                         _cd_hunger=1000, _cd_strength=1000, _cd_poop=1000, time=10 ** 9)
            steps = []
            for _ in range(6):
                before = (p._cd_hunger, p._cd_strength, p._cd_poop)
                life.minutes(p, 1)
                steps.append((p.life_minutes, before[0] - p._cd_hunger, before[1] - p._cd_strength,
                              before[2] - p._cd_poop))
            young = [s for s in steps if s[0] <= 5 * DAY - 1]
            old = [s for s in steps if s[0] >= 5 * DAY]
            strength_on = p.tracks_strength()
            ok = (all(s[1] == 1 and s[3] == 1 for s in young) and all(s[1] == 2 and s[3] == 2 for s in old)
                  and all(s[2] == (1 if strength_on else 0) for s in steps))
            self.add("lifespan", "needs from age 5", ok,
                     "per minute (life, hunger, strength, poop): " + ", ".join(map(str, steps)))

    def age5_mistakes(self):
        record = fighter(self.module) or self.top_form()
        with Life(self) as life:
            p = life.pet(record, life_minutes=5 * DAY - 3, mistakes=16, time=10 ** 9, sleeps=None, wakes=None)
            life.minutes(p, 2)
            young_alive = p.state != "dead" and not p.dying
            life.minutes(p, 1)
            old_dead = p.state == "dead" or p.dying
        with Life(self) as life:
            q = life.pet(record, life_minutes=6 * DAY, mistakes=15, time=10 ** 9, sleeps=None, wakes=None)
            life.minutes(q, 2)
            fifteen = q.state != "dead" and not q.dying
        self.add("lifespan", "16 mistakes from age 5", young_alive and old_dead and fifteen,
                 f"16 before 5 days: alive {young_alive}; at 5 days: dying/dead {old_dead}; "
                 f"15 after: alive {fifteen}")

    #: Pets whose routes may all be missed: fresh (level 1, no battles or
    #: training), then with 4 care mistakes (the X's Perfect routes stop at
    #: 3; the 5-mistake death is not reached).
    WINDOW_STATES = ({}, {"mistakes": 4})

    def window_form(self, stage):
        """(form of *stage* with timer routes, the state in which a pet of it
        meets none when its time comes), or None."""
        for state in self.WINDOW_STATES:
            for record in forms(self.module, stage):
                if not record.get("time") or not record.get("evolve"):
                    continue
                with Life(self) as life:
                    p = life.pet(record, _evol_minutes=int(record["time"]), **state)
                    if not p.can_evolve():
                        return record, state
        return None

    def window_run(self, stage):
        """(record, failed, still the same form) for a pet of *stage* left
        past its evolution time without a route met, or None."""
        found = self.window_form(stage)
        if found is None:
            return None
        record, state = found
        with Life(self) as life:
            p = life.pet(record, sleeps=None, wakes=None, _evol_minutes=int(record["time"]) - 2, **state)
            # Cared for (nothing holds the check), but the mistakes stay.
            for _ in range(30):
                mistakes = p.mistakes
                care(p)
                p.mistakes = mistakes
                life.minutes(p, 1)
            return record, p.evolution_failed, p.name == record["name"]

    def window_closes(self):
        first = lifespan_rules.WINDOW_STAGES[lifespan_rules.rule(self.module)]
        result = self.window_run(first)
        if result is None:
            return self.skip("lifespan", "the window closes", f"no Stage {first} form whose routes a fresh pet misses")
        record, failed, same = result
        self.add("lifespan", "the window closes", failed and same,
                 f"{record['name']} (Stage {record['stage']}, time {record['time']}): failed {failed}, "
                 f"still {record['name']} {same}")

    def window_waits(self):
        first = lifespan_rules.WINDOW_STAGES[lifespan_rules.rule(self.module)]
        result = self.window_run(first - 1)
        if result is None:
            return self.skip("lifespan", "earlier stages wait", f"no Stage {first - 1} form whose routes a fresh pet misses")
        record, failed, _same = result
        self.add("lifespan", "earlier stages wait", not failed,
                 f"{record['name']} (Stage {record['stage']}): failed {failed} (it keeps waiting for a route)")

    # -- sickness and injury -------------------------------------------------

    def ailment_checks(self):
        record = fighter(self.module)
        if record is None:
            return self.skip("ailments", "all", "no raisable form that can fall ill and battle")
        self.record = record
        for check, fn in (("causes", self.causes), ("counts", self.counts), ("timers", self.timers),
                          ("gates", self.gates), ("heal", self.heal), ("items", self.items),
                          ("evolution clears", self.evolution_clears)):
            self.guard("ailments", check, fn)

    def fresh(self, life, **fields):
        p = life.pet(self.record, sleeps=None, wakes=None, time=10 ** 9, **fields)
        p.state = "idle"
        care(p)
        return p

    def expected_causes(self):
        m = self.module
        poop = ailments.kind_for_effect(m.care_poop_sickness_effect) if m.care_poop_sickness_count > 0 else None
        disturb = (ailments.kind_for_effect(m.care_disturbance_sickness_effect)
                   if m.care_disturbance_sickness_count > 0 else None)
        species_injury = int(self.record.get("injury_probability", 0) or 0)
        return {"poop pile": poop, "99 G": ailments.kind_for_effect(m.care_99g_effect),
                "disturbance": disturb,
                "battle won": "injury" if m.battle_base_sick_chance_win > 0 else None,
                "battle lost": "injury" if (m.battle_base_sick_chance_lose > 0 or species_injury > 0) else None}

    def causes(self):
        expected = self.expected_causes()
        got = {}
        with Life(self) as life:
            for cause in expected:
                game_globals.pet_list.clear()
                p = self.fresh(life, protein_overdose=0, disturbance_penalty=0)
                if cause == "poop pile":
                    game_globals.poop_list[:] = [object()] * (self.module.care_poop_sickness_count or 1)
                    p.poop_count_flag, p._cd_poop = 0, max(p._cd_poop, 5)
                    p.update_pooping(0)
                elif cause == "99 G":
                    p.weight, p._99g_triggered = 99, False
                    p.update_99g_effect()
                elif cause == "disturbance":
                    p.sleep_disturbances = max(1, self.module.care_disturbance_sickness_count)
                    p._check_disturbance_sickness()
                else:
                    with patch("models.game_pet.random", HIT):
                        p._battle_health(cause == "battle won")
                got[cause] = ailments.kind_of(p)
        self.add("ailments", "causes", got == expected,
                 "; ".join(f"{c}: {got[c] or '-'}" + ("" if got[c] == expected[c] else f" (expected {expected[c] or '-'})")
                           for c in expected))

    def counts(self):
        notes, ok = [], True
        with Life(self) as life:
            for kind in ailments.KINDS:
                limit = ailments.death_max(self.module, kind)
                total = ailments.TOTALS[kind]
                game_globals.pet_list.clear()
                p = self.fresh(life, **{total: max(0, limit - 1) if limit else 99})
                before = p.check_death_conditions() or p.dying
                if not limit:
                    ok &= not before
                    notes.append(f"{kind}: no count death ({'ok' if not before else 'died at 99'})")
                    continue
                setattr(p, total, limit)
                died = p.check_death_conditions()
                dying = p.dying and p.death_cause == ailments.COUNT_CAUSES[kind]
                undone = True
                if dying:
                    with patch.object(GamePet, "set_state"):
                        p._death_saved()
                    undone = getattr(p, total) == limit - 1
                ok &= (not before) and (died or dying) and undone
                notes.append(f"{kind}: {limit} kills ({'unsaved' if died else 'through the save' if dying else 'NOT'})"
                             + ("" if not before else ", but already at one less")
                             + ("" if undone else ", the save did not give one back"))
        self.add("ailments", "counts", ok, "; ".join(notes))

    def timers(self):
        notes, ok = [], True
        for kind in ailments.KINDS:
            limit = ailments.death_timer(self.module, kind)
            if not limit:
                notes.append(f"{kind}: no timer")
                continue
            with Life(self) as life:
                p = self.fresh(life)
                p.add_ailment(kind)
                seen = {}

                def watch(q):
                    if q.dying and "at" not in seen:
                        seen["at"] = getattr(q, ailments.TIMERS[kind])
                    return q.state == "dead"
                life.run(p, limit + 30, keep_ailment=True, stop=watch)
                death = life.deaths.log[0] if life.deaths.log else None
                when = seen.get("at") or (getattr(p, ailments.TIMERS[kind]) if death else None)
                good = death is not None and when is not None and limit < when <= limit + CARE_EVERY
                cause = (death or {}).get("cause") or (death or {}).get("ailment")
                good &= cause in ("", ailments.TIMER_CAUSES[kind])
                ok &= good
                notes.append(f"{kind}: {limit} min untreated, died after {when} ({cause or 'no save'})"
                             if death else f"{kind}: {limit} min untreated, never died")
        self.add("ailments", "timers", ok, "; ".join(notes))

    def gates(self):
        notes, ok = [], True
        with Life(self) as life:
            for kind in ailments.KINDS:
                game_globals.pet_list.clear()
                p = self.fresh(life)
                p.dp = max(int(getattr(p, "dp", 0) or 0), 4)
                base_battle, base_train = p.can_battle(), p.can_train()
                p.add_ailment(kind)
                battle, train = p.can_battle(), p.can_train()
                want_battle = base_battle and ailments.allows_battle(self.module, kind)
                want_train = base_train and ailments.allows_training(self.module, kind)
                good = battle == want_battle and train == want_train
                ok &= good
                notes.append(f"{kind}: battles {battle}, trains {train}"
                             + ("" if good else f" (expected {want_battle}, {want_train})"))
        self.add("ailments", "gates", ok, "; ".join(notes))

    def heal(self):
        from scenes.scene_maingame import SceneMainGame
        notes, ok = [], True
        with Life(self) as life, patch("scenes.scene_maingame.distribute_pets_evenly"):
            for kind in ailments.KINDS:
                game_globals.pet_list.clear()
                p = self.fresh(life)
                p.add_ailment(kind)
                doses = ailments.doses(p, kind)
                scene = SceneMainGame.__new__(SceneMainGame)
                scene.start_scene = lambda *_: None
                presses = 0
                while ailments.ailing(p) and presses < 200:
                    scene.heal_sick_pets()
                    presses += 1
                good = presses == doses == int(p.heal_doses) and not ailments.ailing(p)
                ok &= good
                notes.append(f"{kind}: {doses} doses, healed in {presses}")
        self.add("ailments", "heal", ok, "; ".join(notes))

    def items(self):
        from utils import item_effects
        cures = [i for i in getattr(self.module, "items", []) or [] if getattr(i, "effect", "") in ("cure", "bedding")]
        if not cures:
            return self.skip("ailments", "items", "no cure items")
        notes, ok = [], True
        with Life(self) as life:
            for item in cures:
                for kind in ailments.KINDS:
                    game_globals.pet_list.clear()
                    p = self.fresh(life)
                    p.add_ailment(kind)
                    if item.effect == "bedding":
                        with patch.object(GamePet, "set_state"):
                            item_effects.bedding(p, 10)
                        want = False
                    else:
                        item_effects.cure(p, getattr(item, "status", ""))
                        want = getattr(item, "status", "") not in ("", None, kind)
                    good = ailments.ailing(p) == want
                    ok &= good
                    notes.append(f"{item.name} on {kind}: {'still ' + kind if ailments.ailing(p) else 'healed'}"
                                 + ("" if good else " (wrong)"))
        self.add("ailments", "items", ok, "; ".join(notes))

    def evolution_clears(self):
        with Life(self) as life:
            p = self.fresh(life, sick_total=3, injury_total=4)
            p.add_ailment("injury")
            p.care_injury_mistake_timer = 50
            p.reset_variables()
            left = {k: getattr(p, k) for k in ("sick", "injury", "sick_total", "injury_total",
                                                "care_sick_mistake_timer", "care_injury_mistake_timer")}
            self.add("ailments", "evolution clears", not any(left.values()), str(left))


# ----------------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------------

def crawl(names, quiet=False):
    rows = []
    for name in names:
        started = time.time()
        c = Crawler(name)
        if c.module is None:
            rows.append(dict(module=name, area="-", check="load", result="skip", detail="module not installed"))
            continue
        c.lifespan()
        c.ailment_checks()
        rows += c.rows
        if not quiet:
            tally = collections.Counter(r["result"] for r in c.rows)
            print(f"{name:8} {time.time() - started:5.1f}s  " + "  ".join(f"{k} {v}" for k, v in sorted(tally.items())),
                  flush=True)
    return rows


def markdown(rows, names):
    lines = ["# Care crawl", "", f"{time.strftime('%Y-%m-%d %H:%M')}. Lifespan, sickness and injury on the game's "
             "own per-minute code, per module (tests/release/care_crawl.py, MOD-21).", "",
             "| Module | Lifespan rule | ok | fail | skip |", "|---|---|---|---|---|"]
    for name in names:
        mine = [r for r in rows if r["module"] == name]
        rule = next((r["detail"][len("lifespan_rule "):] for r in mine if r["check"] == "rule"), "-")
        tally = collections.Counter(r["result"] for r in mine)
        lines.append(f"| {name} | {rule} | {tally['ok']} | {tally['fail'] + tally['error']} | {tally['skip']} |")
    for name in names:
        mine = [r for r in rows if r["module"] == name and r["result"] != "info"]
        if not mine:
            continue
        lines += ["", f"## {name}", ""]
        for r in mine:
            lines.append(f"- **{r['result']}** {r['area']} / {r['check']}: {r['detail']}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--out", default=os.path.join(ROOT, "tmp", "release-reports", "care"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    names = args.modules or release_modules()
    rows = crawl(names, args.quiet)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "care_crawl.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(args.out, "care_crawl.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(rows, names))
    tally = collections.Counter(r["result"] for r in rows)
    print("total: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 1 if tally["fail"] or tally["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
