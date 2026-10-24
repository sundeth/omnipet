#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Release audit of module data: the automated part of checklist section MOD.

Read-only. Every finding carries the checklist id it belongs to
(utilities/claude/docs/release-checklist.md), a severity and a subject:

    error  the release rule is broken (a missing sprite, an unreachable form)
    warn   probably wrong, needs a look (a route shadowed by an earlier one)
    info   recorded for the reviewer, not a defect (connection-only unlocks)

    python -B tests/release/module_audit.py [MODULE ...] [--json PATH] [--md PATH] [--quiet]

Sprite lookup is the one audit_module_sprites.py uses (module folder, module
zip, shared folder, shared zip; exact letter case), so both agree on what the
game draws.
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "support"))
from paths import ROOT  # noqa: E402
MODULES = os.path.join(ROOT, "modules")
ASSETS = os.path.join(ROOT, "assets")

import sprites  # noqa: E402  (tests/support/sprites.py)

sys.stdout.reconfigure(encoding="utf-8")

#: Modules shipped with 1.0 (owner, 2026-10-13).
RELEASE_MODULES = ["D-3", "DM20", "DMC", "DMGZ", "DMH", "DMM", "DMOG", "DMRV", "DMX", "DMXW",
                   "DW1", "IC", "PEN20", "PENC", "PENGZ", "PENOG", "PENZ", "VB", "VBE", "VH"]

#: Stages whose records are the device's own and carry no care data: DMH's
#: Egg (Phase I/II) match the firmware (utilities/claude/validate_dmh.py,
#: 0 findings 2026-10-15; owner: "special cases, correct if they agree").
#: DMXW's Baby II (Pickmon, Gaossmon) evolve after 30 minutes and have no
#: sleep time on the device (utilities/claude/dmxw_sources.json).
FIRMWARE_STAGES = {"DMH": {1, 2}, "DMXW": {2}}

EGG_FRAMES = frozenset({0, 1, 2})
RAISABLE_FRAMES = frozenset(range(15))
#: IDLE1, IDLE2, ANGRY, ATK1, ATK2, LOSE (owner, 2026-10-13).
ENEMY_FRAMES = frozenset({0, 1, 3, 6, 7, 14})
#: Mode changes, DigiXros forms and records no battle fights: IDLE1.
TEMP_FRAMES = frozenset({0})
#: What a battle draws for a pet after its temporary evolution (charge,
#: attack motion, shot, defeat); missing ones fall back (FRAME_FALLBACKS).
BATTLE_FRAMES = frozenset({0, 1, 3, 4, 5, 6, 14})
UNRAISABLE = ("Unobtainable", "Friend")
#: Route keys that are not a requirement (they name, flavour or redirect the route).
NON_CRITERIA = {"to", "version", "jogress", "jogress_name", "jogress_version", "jogress_stage",
                "jogress_attribute", "jogress_prefix"}
TIMER_EXEMPT = {"jogress", "item", "at_death", "defeat_tag", "special_encounter"}


DATABASE = os.environ.get("DIGIMON_DB_JSON", r"E:/Digimon Database/output/digimon.json")
#: Database attribute ids: 1 Virus, 2 Data, 3 Vaccine, 4 Free, 5 NO DATA, 6 Unknown, 7 Variable.
DB_ATTR = {1: "Vi", 2: "Da", 3: "Va"}
_db_attrs = None


def database_attributes():
    """{lower-case name: set of module attribute codes}, empty for Free/unknown ones; {} without the DB."""
    global _db_attrs
    if _db_attrs is None:
        _db_attrs = {}
        try:
            with open(DATABASE, encoding="utf-8") as fh:
                rows = json.load(fh).get("digimon", [])
        except (OSError, ValueError):
            rows = []
        for r in rows:
            ids = set(r.get("attributes") or []) | set(r.get("attribute-alts") or [])
            codes = {DB_ATTR[i] for i in ids if i in DB_ATTR}
            if ids - set(DB_ATTR):        # Free, NO DATA, Unknown or Variable: blank is right
                codes = set()
            for n in [r.get("name-english"), r.get("name-dub")] + list(r.get("name-alternatives") or []):
                if n:
                    _db_attrs.setdefault(n.lower(), set()).update(codes) if codes else _db_attrs.setdefault(n.lower(), set())
    return _db_attrs


def load(path, root=None, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if root is None:
        return data
    return data.get(root, default) if isinstance(data, dict) else data


class Module:
    def __init__(self, name):
        self.name = name
        self.dir = os.path.join(MODULES, name)
        self.meta = load(os.path.join(self.dir, "module.json"), default={}) or {}
        self.monsters = load(os.path.join(self.dir, "monster.json"), "monster", []) or []
        self.enemies = load(os.path.join(self.dir, "battle.json"), "enemies", []) or []
        self.items = load(os.path.join(self.dir, "item.json"), "item", []) or []
        self.quests = load(os.path.join(self.dir, "quests.json"), "quests", []) or []
        events = load(os.path.join(self.dir, "events.json"), default={}) or {}
        self.events = events.get("events", []) if isinstance(events, dict) else []
        self.connect_points = events.get("connect_points") if isinstance(events, dict) else None
        self.devices = load(os.path.join(self.dir, "devices.json"), "devices", None)
        shop = load(os.path.join(self.dir, "shop.json"), default={}) or {}
        self.currencies = shop.get("currency", []) if isinstance(shop, dict) else []
        self.shops = shop.get("shop", []) if isinstance(shop, dict) else []
        self.codes = load(os.path.join(self.dir, "codes.json"), "passwords", []) or []
        self.cards = load(os.path.join(self.dir, "cards.json"), default={}) or {}
        self.unlocks = self.meta.get("unlocks") or []
        self.backgrounds = self.meta.get("backgrounds") or []
        self.by_key = {}
        self.by_name = collections.defaultdict(list)
        for m in self.monsters:
            self.by_key.setdefault((m.get("name"), m.get("version")), m)
            self.by_name[m.get("name")].append(m)
        self.item_names = {i.get("name") for i in self.items if i.get("name")}
        self.unlock_names = {u.get("name") for u in self.unlocks if u.get("name")}
        self.visible = {s.strip().lower() for s in (self.meta.get("visible_stats") or "").split(",") if s.strip()}
        #: forms reached only for a battle (temporary-evolution): they fight, they are not raised
        self.temp_targets = collections.defaultdict(set)
        for m in self.monsters:
            for t in m.get("temporary-evolution") or []:
                if t.get("to"):
                    self.temp_targets[(t["to"], m.get("version"))].add(m.get("name"))
        self.temp_names = {k[0] for k in self.temp_targets}
        self.code_pets = {(c.get("pet"), c.get("version")) for c in self.codes if c.get("type") == "pet"}
        self.adventure_areas = sorted({e.get("area") for e in self.enemies
                                       if not e.get("special_encounter") and e.get("area") is not None})


def sname(mod, name):
    return sprites.sprite_name(name, mod.meta.get("name_format"))


def formats(mod):
    primary = mod.meta.get("primary_sprite_format") or "Color"
    return [primary] + (["Color"] if primary == "Dot" else [])


def frames(mod, name, fmt):
    origin, got, case = sprites.resolve(fmt, mod.dir, sname(mod, name))
    return origin, got, case


#: Route criteria the pet itself can only meet by fighting (game_pet's
#: evolution check: `area` is the furthest area *this* pet has won in).
BATTLE_ROUTE_KEYS = ("battles", "win_count", "total_battles", "pvp",
                     "stage-5", "stage-6", "stage-7", "stage-8", "stage-9")
#: ... and by training (effort, trophies).
TRAINING_ROUTE_KEYS = ("training", "trophies")


def _lower(value):
    if isinstance(value, list) and value:
        return value[0] or 0
    return value if isinstance(value, (int, float)) else 0


def route_needs(monster):
    """(battle criteria, training criteria) the monster's evolution routes
    ask of the pet itself. `win_ratio` alone is not one: it is skipped until
    the pet has fought. A target's special_key that another Digimon can earn
    is not one either (owner, 2026-10-14)."""
    battle, training = set(), set()
    for evo in monster.get("evolve") or []:
        for k in BATTLE_ROUTE_KEYS:
            if k in evo and _lower(evo[k]) > 0:
                battle.add(k)
        if evo.get("defeat_tag"):
            battle.add("defeat_tag")
        if evo.get("area"):
            battle.add("area")
        for k in TRAINING_ROUTE_KEYS:
            if k in evo and _lower(evo[k]) > 0:
                training.add(k)
    return sorted(battle), sorted(training)


def is_jogress(evo):
    return bool(evo.get("jogress")) or any(k.startswith("jogress_") for k in evo)


def attack_sprite_exists(mod, atk):
    if not atk:
        return False
    for base in (os.path.join(mod.dir, "atk"), os.path.join(ASSETS, "atk")):
        if os.path.isfile(os.path.join(base, f"{atk}.png")):
            return True
    return False


def bg_files(mod, bg):
    name = bg.get("name")
    folder = os.path.join(mod.dir, "backgrounds")
    slices = ["_day", "_dusk", "_night"] if bg.get("day_night", True) else [""]
    return [(s, os.path.join(folder, f"bg_{name}{s}.png"), os.path.join(folder, f"bg_{name}{s}_high.png"))
            for s in slices]


class Audit:
    def __init__(self, mod):
        self.mod = mod
        self.findings = []

    def add(self, check, severity, subject, detail):
        self.findings.append({"module": self.mod.name, "check": check, "severity": severity,
                              "subject": subject, "detail": detail})

    # ------------------------------------------------------------------ MOD-01
    def module_art(self):
        mod = self.mod
        for f in ("logo.png", "Flag.png"):
            if not os.path.isfile(os.path.join(mod.dir, f)):
                self.add("MOD-01", "error", f, "module art missing")
        if mod.meta.get("adventure_mode") and not os.path.isfile(os.path.join(mod.dir, "BattleIcon.png")):
            self.add("MOD-01", "error", "BattleIcon.png", "adventure_mode is on but the battle icon is missing")
        for d in mod.devices or []:
            sprite = (d.get("sprite") or "").strip()
            if not sprite:
                self.add("MOD-01", "error", f"device {d.get('name')}", "no device sprite named")
                continue
            path = os.path.join(mod.dir, "devices", sprite if sprite.lower().endswith(".png") else sprite + ".png")
            if not os.path.isfile(path):
                self.add("MOD-01", "error", f"device {d.get('name')}", f"device icon devices/{os.path.basename(path)} missing")

    # ------------------------------------------------------------------ MOD-14
    def egg_available(self, m, got):
        """scene_eggselection._get_available_eggs: plain, or special with its key held."""
        if not m.get("special"):
            return True
        key = m.get("special_key") or ""
        return key == "gcell_fragment" or not key or key in got

    def device_has_art(self, d):
        """scene_eggselection._device_has_art: a screen background, or a sprite
        that stands alone (VB, VBE and VH devices are the DIM card itself; owner,
        2026-10-14)."""
        if (d.get("background") or "").strip():
            return True
        sprite = (d.get("sprite") or "").strip()
        if sprite and not sprite.lower().endswith(".png"):
            sprite += ".png"
        return bool(sprite) and os.path.exists(os.path.join(self.mod.dir, "devices", sprite))

    def choosable_eggs(self, got):
        """The eggs the egg screen offers, given the unlocks held.

        Mirrors scene_eggselection: a device is selectable when it has its art
        (see device_has_art) and at least one available egg; when a module has
        any such device only their eggs are offered, otherwise every available
        egg is.
        """
        mod = self.mod
        avail = [m for m in mod.monsters if m.get("stage") == 0 and self.egg_available(m, got)]
        avail_keys = {(m.get("name"), m.get("version")) for m in avail}
        selectable = [d for d in mod.devices or [] if self.device_has_art(d)
                      and any((r.get("name"), r.get("version")) in avail_keys for r in d.get("eggs") or [])]
        if not selectable:
            return avail_keys
        out = set()
        for d in selectable:
            out.update((r.get("name"), r.get("version")) for r in d.get("eggs") or []
                       if (r.get("name"), r.get("version")) in avail_keys)
        return out

    def devices(self):
        mod = self.mod
        if mod.devices is None:
            self.add("MOD-14", "error", "devices.json", "missing: the egg screen lists bare eggs, no device art")
            return
        if not mod.devices:
            self.add("MOD-14", "error", "devices.json", "no devices")
        eggs = {(m.get("name"), m.get("version")) for m in mod.monsters if m.get("stage") == 0}
        on_device = set()
        any_plain = False
        # Re-releases may announce the same version on the wire: PENOG's
        # NSp 1.5 is a 1.0 to a connected device (owner, 2026-10-14). Only a
        # versus unlock by device_version cannot tell them apart.
        versions = collections.Counter(d.get("device_version") for d in mod.devices)
        for v, n in versions.items():
            if n > 1:
                self.add("MOD-14", "info", f"device_version {v}", f"{n} devices share it: they identify alike over DCom")
        bg_names = {b.get("name") for b in mod.backgrounds}
        unfinished = [d.get("name") for d in mod.devices if not self.device_has_art(d)]
        finished = len(mod.devices) - len(unfinished)
        if unfinished and finished:
            self.add("MOD-14", "error", "devices", f"{len(unfinished)} of {len(mod.devices)} devices have no background "
                     f"or sprite and are hidden while the others show: {', '.join(unfinished[:6])}")
        elif unfinished:
            self.add("MOD-14", "warn", "devices", f"no device has a background or sprite ({len(unfinished)}): the egg "
                     "screen skips device selection and lists bare eggs")
        for d in mod.devices:
            label = f"device {d.get('name')}"
            if (d.get("background") or "").strip() and d.get("background") not in bg_names:
                self.add("MOD-14", "error", label, f"background '{d.get('background')}' is not a module background")
            refs = d.get("eggs") or []
            if not refs:
                self.add("MOD-14", "error", label, "no eggs")
            for r in refs:
                key = (r.get("name"), r.get("version"))
                if key not in eggs:
                    self.add("MOD-14", "error", label, f"egg {key[0]} v{key[1]} is not a stage-0 monster")
                    continue
                on_device.add(key)
                if not mod.by_key[key].get("special"):
                    any_plain = True
        if mod.devices and not any_plain:
            self.add("MOD-14", "error", "devices", "no device offers a non-special egg")
        if finished:
            for key in sorted(eggs - on_device, key=str):
                if mod.by_key[key].get("availability") in UNRAISABLE:
                    continue        # kept on purpose: DMRV's Meicoo, a DM20 Ver.E leftover
                self.add("MOD-14", "error", f"egg {key[0]} v{key[1]}", "on no device: it can never be chosen")

    # ------------------------------------------------------------------ unlocks
    def obtainable_unlocks(self, reachable_names, reachable_stages, plain_egg_versions):
        """Names of unlocks a player can earn, to a fixpoint. Also records why not."""
        mod = self.mod
        areas = set(mod.adventure_areas)
        enemy_unlocks = {e.get("unlock") for e in mod.enemies if e.get("unlock")}
        code_unlocks = {c.get("unlock") or c.get("name") for c in mod.codes if c.get("type") == "unlock"}
        card_unlocks = set()
        for c in (mod.cards.get("cards", []) if isinstance(mod.cards, dict) else []):
            for k in ("unlock", "unlocks"):
                v = c.get(k)
                if isinstance(v, str) and v:
                    card_unlocks.add(v)
                elif isinstance(v, list):
                    card_unlocks.update(x.get("name") if isinstance(x, dict) else x for x in v)
        got, why = set(), {}
        for _ in range(10):
            before = len(got)
            for u in mod.unlocks:
                n, t = u.get("name"), u.get("type")
                if n in got:
                    continue
                ok, reason = False, ""
                if n in code_unlocks or n in card_unlocks:
                    ok = True
                elif t == "egg":
                    v = u.get("version")
                    ok = v is None or v in plain_egg_versions
                    reason = f"no obtainable egg of version {v}"
                elif t == "adventure":
                    ok = u.get("area") in areas
                    reason = f"area {u.get('area')} has no adventure enemies"
                elif t == "evolution":
                    to = u.get("to") or []
                    if to:
                        ok = any(x in reachable_names for x in to)
                        reason = f"none of {to} is reachable"
                    elif u.get("stage") is not None:
                        ok = any(s >= u["stage"] for s in reachable_stages)
                        reason = f"no reachable form at stage {u['stage']}+"
                    else:
                        reason = "names neither 'to' nor 'stage'"
                elif t == "group":
                    lst = u.get("list") or []
                    ok = bool(lst) and all(x in got for x in lst)
                    reason = "group members not all obtainable: " + ", ".join(x for x in lst if x not in got)
                elif t == "encounter":
                    ok = n in enemy_unlocks or u.get("amount") is not None
                    reason = "no enemy grants it and no Friend amount"
                elif t in ("digidex", "battle"):
                    ok = True
                elif t in ("versus", "pvp"):
                    ok = True   # connection-only; listed as info
                else:
                    reason = f"unknown unlock type '{t}'"
                if ok:
                    got.add(n)
                    why.pop(n, None)
                else:
                    why[n] = reason
            if len(got) == before:
                break
        return got, why

    # ------------------------------------------------------------------ MOD-03
    def reachability(self):
        """BFS from the eggs a player can choose; returns the reachable (name, version) keys."""
        mod = self.mod
        eggs = [m for m in mod.monsters if m.get("stage") == 0]
        got, why = set(), {}
        reach = set()
        for _ in range(6):           # special keys can open eggs that open more keys
            start = sorted(self.choosable_eggs(got) | {k for k in mod.code_pets if k in mod.by_key}, key=str)
            plain_versions = {k[1] for k in start}
            new = set(start)
            queue = list(start)
            while queue:
                key = queue.pop()
                m = mod.by_key.get(key)
                if not m:
                    continue
                # An `evolve` item turns a form within its stages into its
                # target on the same version (item_effects.evolve_target): the
                # iC's Ouryujin, Platinum, Leo Cap, Chaos-G, Marine Extract.
                stage = m.get("stage", 0) or 0
                item_routes = [{"to": it.get("target")} for it in mod.items
                               if it.get("effect") == "evolve" and it.get("target") and it.get("target") != key[0]
                               and not (it.get("min_stage") and stage < it["min_stage"])
                               and not (it.get("max_stage") and stage > it["max_stage"])]
                for evo in (m.get("evolve") or []) + (m.get("temporary-evolution") or []) + item_routes:
                    to = evo.get("to")
                    tkey = (to, key[1])
                    t = mod.by_key.get(tkey)
                    if t is None and evo.get("version") is not None and not is_jogress(evo):
                        tkey = (to, evo.get("version"))
                        t = mod.by_key.get(tkey)
                    if t is None:
                        continue
                    # A route needing a held unlock opens once the unlock can be earned.
                    if evo.get("unlock") and evo["unlock"] not in got:
                        continue
                    if m.get("stage", 0) > 0 and t.get("special") and t.get("special_key") \
                            and t.get("special_key") not in got:
                        continue
                    if tkey not in new:
                        new.add(tkey)
                        queue.append(tkey)
            names = {k[0] for k in new}
            stages = {mod.by_key[k].get("stage", 0) for k in new if k in mod.by_key}
            got2, why = self.obtainable_unlocks(names, stages, plain_versions)
            if new == reach and got2 == got:
                break
            reach, got = new, got2
        self.reach, self.got_unlocks, self.unlock_why = reach, got, why
        for m in mod.monsters:
            key = (m.get("name"), m.get("version"))
            if m.get("stage", 0) == 0 or m.get("availability") in UNRAISABLE or key in reach:
                continue
            if key in mod.temp_targets:
                self.add("MOD-03", "error", f"{m.get('name')} v{m.get('version')}",
                         "temporary form whose source (" + ", ".join(sorted(mod.temp_targets[key])) + ") is unreachable")
                continue
            reason = ""
            if m.get("special") and m.get("special_key") and m.get("special_key") not in got:
                reason = f" (special_key '{m.get('special_key')}' not obtainable" + \
                         (f": {why.get(m.get('special_key'))}" if why.get(m.get("special_key")) else "") + ")"
            sources = [s.get("name") for s in mod.monsters if s.get("version") == m.get("version")
                       and any(e.get("to") == m.get("name") for e in s.get("evolve") or [])]
            if not sources and not reason:
                self.add("MOD-03", "error", f"{m.get('name')} v{m.get('version')}",
                         "orphan: raisable (no availability flag) but no route, egg or code leads to it; "
                         "add the route or mark it Unobtainable")
                continue
            elif not reason:
                reason = f" (only from unreachable {', '.join(sorted(set(sources))[:4])})"
            self.add("MOD-03", "error", f"{m.get('name')} v{m.get('version')}", "not reachable from any choosable egg" + reason)
        return reach

    # ------------------------------------------------------------------ MOD-03 routes
    def routes(self):
        mod = self.mod
        max_area = max(mod.adventure_areas) if mod.adventure_areas else 0
        for m in mod.monsters:
            label = f"{m.get('name')} v{m.get('version')}"
            evos = m.get("evolve") or []
            for evo in evos:
                to = evo.get("to")
                if not to:
                    self.add("MOD-03", "error", label, "route without a target")
                    continue
                target = mod.by_key.get((to, m.get("version")))
                if target is None and not (evo.get("version") is not None and mod.by_key.get((to, evo["version"]))):
                    where = sorted({x.get("version") for x in mod.by_name.get(to, [])})
                    self.add("MOD-03", "error", label,
                             f"route to '{to}' has no target on v{m.get('version')}" +
                             (f" (exists on {where})" if where else " (no such monster)"))
                if evo.get("area") and evo["area"] > max_area:
                    self.add("MOD-03", "error", label, f"route to {to} needs area {evo['area']}; the last adventure area is {max_area}")
                if evo.get("item") and evo["item"] not in mod.item_names:
                    self.add("MOD-15", "error", label, f"route to {to} needs item '{evo['item']}', not in item.json")
            # A temporary evolution is offered only in a battle its `battle_area`
            # admits (0: outside the adventure areas) and to a pet holding its
            # `xros_cost` in DP (xros_utils).
            for t in m.get("temporary-evolution") or []:
                rng = t.get("battle_area")
                if rng:
                    lo = rng[0] if len(rng) > 0 and rng[0] not in (-1, None) else 0
                    hi = rng[1] if len(rng) > 1 and rng[1] not in (-1, None) else 999999
                    if not any(lo <= a <= hi for a in [0] + list(mod.adventure_areas)):
                        self.add("MOD-03", "error", label,
                                 f"temporary evolution to {t.get('to')} needs battle area {lo}-{hi}; "
                                 f"no battle is fought there (areas {mod.adventure_areas or 'none'}, 0 outside them)")
                cost = t.get("xros_cost") or 0
                if cost and cost > (m.get("energy") or 0):
                    self.add("MOD-03", "error", label,
                             f"temporary evolution to {t.get('to')} costs {cost} DP; the form holds {m.get('energy') or 0}")
            # first match wins: an unconditional timer route hides every later timer route
            if m.get("stage", 0) == 0:
                continue
            timer = [e for e in evos if not (TIMER_EXEMPT & set(e)) and not is_jogress(e)]
            for i, e in enumerate(timer[:-1]):
                crit = set(e) - NON_CRITERIA
                if not crit:
                    dead = [x.get("to") for x in timer[i + 1:]]
                    self.add("MOD-03", "warn", label,
                             f"route to {e.get('to')} has no requirement, so later routes never run: {', '.join(dead)}")
                    break

    # ------------------------------------------------------------------ MOD-02/04/05/11
    def monster_sprites(self, reach):
        mod = self.mod
        fmts = formats(mod)
        enemy_names = {e.get("name") for e in mod.enemies if e.get("name")}
        seen = set()
        for m in mod.monsters:
            name = m.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            stage = m.get("stage", 0)
            versions = [x for x in mod.by_name[name]]
            raisable = any(x.get("availability") not in UNRAISABLE for x in versions) and stage > 0                 and name not in mod.temp_names
            obtainable = any((name, x.get("version")) in reach for x in versions)
            temporary = name in mod.temp_names
            if stage == 0:
                need, check = EGG_FRAMES, "MOD-05"
            elif raisable:
                need, check = RAISABLE_FRAMES, "MOD-04"
            elif temporary or name not in enemy_names:
                # Mode changes and DigiXros forms have only the frames their
                # device's battle shows, and a record no battle fights (DMXW's
                # Friend Evolutions) is only listed: IDLE1 is enough, the
                # battle draws a related frame for the rest
                # (models.animation.FRAME_FALLBACKS; owner, 2026-10-15).
                need, check = TEMP_FRAMES, "MOD-11"
            else:
                need, check = ENEMY_FRAMES, "MOD-11"
            for fmt in fmts:
                origin, got, case = frames(mod, name, fmt)
                if origin is None:
                    what = ("only a different letter case: " + ", ".join(case)) if case else "no sprite set"
                    self.add("MOD-02", "error", f"{name} [{fmt}]", what)
                    continue
                if temporary and BATTLE_FRAMES - got:
                    self.add("MOD-11", "info", f"{name} [{fmt}]",
                             f"battle-only form drawn with fallbacks for {sprites.fmt_frames(sorted(BATTLE_FRAMES - got))}")
                missing = sorted(need - got)
                if missing and (obtainable or stage == 0 or not raisable or check == "MOD-11"):
                    self.add(check, "error", f"{name} [{fmt}]",
                             f"{origin} missing frames {sprites.fmt_frames(missing)}")
                elif missing:
                    self.add(check, "warn", f"{name} [{fmt}]",
                             f"unreachable form; {origin} missing frames {', '.join(str(f) for f in missing)}")
        for name in sorted(enemy_names - seen):
            for fmt in fmts:
                origin, got, case = frames(mod, name, fmt)
                if origin is None:
                    self.add("MOD-02", "error", f"enemy {name} [{fmt}]",
                             ("only a different letter case: " + ", ".join(case)) if case else "no sprite set")
                    continue
                missing = sorted(ENEMY_FRAMES - got)
                if missing:
                    self.add("MOD-11", "error", f"enemy {name} [{fmt}]",
                             f"{origin} missing frames {sprites.fmt_frames(missing)}")

    # ------------------------------------------------------------------ MOD-06/07/04 attack
    def metadata(self, reach):
        mod = self.mod
        tracks_strength = "strength" in mod.visible
        tracks_weight = "weight" in mod.visible and mod.name != "DMH"
        attrs = [m.get("attribute") for m in mod.monsters if m.get("stage", 0) >= 2]
        module_has_attributes = any(a for a in attrs)
        for m in mod.monsters:
            name, stage = m.get("name"), m.get("stage")
            label = f"{name} v{m.get('version')}"
            if m.get("availability") in UNRAISABLE:
                continue
            obtainable = (name, m.get("version")) in reach
            sev = "error" if obtainable else "warn"
            if not name:
                self.add("MOD-07", "error", "(unnamed)", "monster without a name")
                continue
            if stage is None:
                self.add("MOD-07", "error", label, "no stage")
                continue
            if stage == 0:
                if not m.get("evolve"):
                    self.add("MOD-07", "error", label, "egg with no hatch route")
                continue
            if name in mod.temp_names:          # battle-only form: power and attack only
                if not m.get("power"):
                    self.add("MOD-06", sev, label, "temporary form without power")
                elif not attack_sprite_exists(mod, m.get("atk_main")):
                    self.add("MOD-04", sev, label, f"temporary form: attack sprite {m.get('atk_main')} missing")
                continue
            missing = []
            # Power (owner, 2026-10-14): from Child up every form battles.
            # Baby I/II battle or train only on some devices: they need it
            # only when one of their own routes asks for it.
            needs_battle, needs_training = route_needs(m)
            can_battle = stage >= 2 and (m.get("power") or 0) > 0 and bool(m.get("atk_main"))
            if stage >= 3 and not m.get("power"):
                self.add("MOD-06", sev, label, "power not set")
            elif stage == 1 and needs_battle:
                self.add("MOD-06", sev, label, f"a route needs it to battle ({', '.join(needs_battle)}), "
                                               "but the game never lets a Baby I battle")
            elif stage == 2 and needs_battle and not can_battle:
                self.add("MOD-06", sev, label, f"a route needs it to battle ({', '.join(needs_battle)}), "
                                               f"but with power {m.get('power') or 0} and atk_main "
                                               f"{m.get('atk_main') or 0} it can never battle")
            if stage in (1, 2) and needs_training and not m.get("atk_main"):
                self.add("MOD-06", sev, label, f"a route needs training ({', '.join(needs_training)}), "
                                               "but with no atk_main it cannot train")
            evos = [e for e in m.get("evolve") or [] if not is_jogress(e)]
            if evos and not m.get("time"):
                missing.append("time")
            # A password copymon (codes.json pet) is a battle record on the
            # device: no evolutions and no care times are its data (PEN20
            # version 20, BeelStarmon v7; owner, 2026-10-15).
            copymon = (name, m.get("version")) in mod.code_pets
            if stage <= 3 and not m.get("evolve") and not copymon:
                missing.append("evolutions")
            if stage >= 2 and not copymon:
                for k in ("sleeps", "wakes"):
                    if not m.get(k):
                        missing.append(k)
            if stage >= 2 and module_has_attributes and not m.get("attribute"):
                known = database_attributes().get(name.lower())
                if known:
                    self.add("MOD-07", "warn", label, "no attribute; the Database lists " + "/".join(sorted(known)))
            if not m.get("stomach") and "hunger" in mod.visible:
                missing.append("stomach")
            if not m.get("hunger_loss") and "hunger" in mod.visible:
                missing.append("hunger_loss")
            if tracks_strength and not m.get("strength_loss"):
                missing.append("strength_loss")
            # Sickness (owner, 2026-10-14): a form that can battle can get
            # sick, so it needs heal doses; Baby I usually cannot (0 is fine).
            # heal_doses 0 makes a form immune (no sickness, no injury);
            # absent means 1 (GamePet's default).
            if (can_battle or (stage >= 3 and m.get("power"))) and m.get("heal_doses", 1) == 0:
                self.add("MOD-07", sev, label, "heal_doses 0 (immune to sickness) although it can battle")
            if tracks_weight and not m.get("min_weight"):
                missing.append("min_weight")
            if stage in FIRMWARE_STAGES.get(mod.name, ()):
                missing = []
            if missing:
                self.add("MOD-07", sev, label, "unset: " + ", ".join(missing))
            if stage >= 2 and m.get("power"):
                atk = m.get("atk_main")
                if not atk:
                    self.add("MOD-04", sev, label, "power > 0 but no atk_main")
                elif not attack_sprite_exists(mod, atk):
                    self.add("MOD-04", sev, label, f"attack sprite {atk} not in atk/ or assets/atk/")
        # Within one stage of one module, some forms immune to sickness (or
        # able to train) and others not is very likely an error (owner,
        # 2026-10-14): the odd ones out are reported.
        by_stage = collections.defaultdict(list)
        for m in mod.monsters:
            if (m.get("availability") not in UNRAISABLE and m.get("name") not in mod.temp_names
                    and m.get("stage") in (1, 2, 3, 4, 5, 6, 7, 8)):
                by_stage[m.get("stage")].append(m)
        for stage, forms in sorted(by_stage.items()):
            for field, odd, what in (("heal_doses", lambda m: m.get("heal_doses", 1) == 0,
                                      "immune to sickness (heal_doses 0)"),
                                     ("atk_main", lambda m: not m.get("atk_main"),
                                      "cannot train or battle (no atk_main)")):
                flagged = [m for m in forms if odd(m)]
                if flagged and len(flagged) < len(forms):
                    for m in flagged:
                        self.add("MOD-07", "error", f"{m.get('name')} v{m.get('version')}",
                                 f"{what} while {len(forms) - len(flagged)} of the {len(forms)} stage-{stage} "
                                 f"forms are not: very likely an error")
        if not module_has_attributes:
            self.add("MOD-07", "info", "attribute", "no Digimon past Baby I has an attribute; check this is the device's design")
        self.ailment_rules()

    def ailment_rules(self):
        """Sickness (Dots) and injury (Skull) are counted apart since
        2026-10-21 (src/utils/ailments.py): a module names both counts and
        both timers itself, and a kind it can cause has a way to kill."""
        meta = self.mod.meta
        for key in ("death_max_sicknesses", "death_injury_timer", "care_can_battle_while_injured",
                    "care_can_train_while_injured"):
            if key not in meta:
                self.add("MOD-07", "warn", "module.json", f"no {key}: the loader reads its pre-split counterpart")
        causes = {"sick": [], "injury": ["battles"]}
        for field, count_field, default in (("care_poop_sickness_effect", "care_poop_sickness_count", 4),
                                            ("care_99g_effect", None, 1),
                                            ("care_disturbance_sickness_effect", "care_disturbance_sickness_count", 0)):
            count = int(meta.get(count_field, default) or 0) if count_field else 1
            effect = meta.get(field, "Dots" if "disturbance" in field else "Skull")
            kind = {"Dots": "sick", "Skull": "injury"}.get(effect)
            if count > 0 and kind:
                causes[kind].append(field)
        injuries = int(meta.get("death_max_injuries", 0) or 0)
        for kind, count_key, timer_key in (("sick", "death_max_sicknesses", "death_sick_timer"),
                                           ("injury", "death_max_injuries", "death_injury_timer")):
            if not causes[kind] or (kind == "injury" and injuries == 0 and int(meta.get(timer_key, 0) or 0) == 0):
                continue
            if int(meta.get(count_key, 0) or 0) <= 0 and int(meta.get(timer_key, meta.get("death_sick_timer", 0)) or 0) <= 0:
                self.add("MOD-07", "warn", "module.json",
                         f"{', '.join(causes[kind])} cause a {'sickness' if kind == 'sick' else 'injury'}, "
                         f"but neither {count_key} nor {timer_key} can kill")

    # ------------------------------------------------------------------ MOD-09/10
    def enemies(self):
        mod = self.mod
        if mod.meta.get("adventure_mode") and not [e for e in mod.enemies if not e.get("special_encounter")]:
            self.add("BAT-01", "error", "battle.json", "adventure_mode is on but there are no adventure enemies")
        rounds = collections.defaultdict(set)
        for e in mod.enemies:
            if e.get("special_encounter"):
                continue
            rounds[e.get("area")].add(e.get("round"))
        areas = sorted(a for a in rounds if isinstance(a, int))
        if areas:
            gaps = sorted(set(range(areas[0], areas[-1] + 1)) - set(areas))
            if gaps:
                self.add("MOD-09", "warn", "areas", f"area numbers skipped: {gaps}")
        for a in areas:
            r = sorted(x for x in rounds[a] if isinstance(x, int))
            gaps = sorted(set(range(1, r[-1] + 1)) - set(r)) if r else []
            if gaps:
                self.add("MOD-09", "error", f"area {a}", f"rounds missing: {gaps} (has 1..{r[-1]})")
        # per version: does every version reach the same rounds? (another version may stand in)
        seen = set()
        for e in mod.enemies:
            key = (e.get("name"), e.get("power"), e.get("stage"), e.get("atk_main"))
            if key in seen:
                continue
            seen.add(key)
            label = f"enemy {e.get('name')} a{e.get('area')} r{e.get('round')} v{e.get('version')}"
            bad = []
            if not e.get("name"):
                bad.append("name")
            if e.get("stage") is None:
                bad.append("stage")
            if not e.get("power"):
                bad.append("power")
            if not e.get("atk_main"):
                bad.append("atk_main")
            elif not attack_sprite_exists(mod, e.get("atk_main")):
                self.add("MOD-10", "error", label, f"attack sprite {e.get('atk_main')} not in atk/ or assets/atk/")
            if bad:
                self.add("MOD-10", "error", label, "unset: " + ", ".join(bad))
            if e.get("prize") and e["prize"] not in mod.item_names:
                self.add("MOD-15", "error", label, f"prize '{e['prize']}' is not in item.json")
            if e.get("unlock") and e["unlock"] not in mod.unlock_names:
                self.add("MOD-13", "error", label, f"unlock '{e['unlock']}' is not a module unlock")
            if e.get("currency") and e["currency"] not in {c.get("name") for c in mod.currencies}:
                self.add("MOD-15", "error", label, f"currency '{e['currency']}' is not in shop.json")

    # ------------------------------------------------------------------ MOD-12/16
    def backgrounds(self):
        mod = self.mod
        names = {b.get("name") for b in mod.backgrounds}
        for b in mod.backgrounds:
            files = bg_files(mod, b)
            missing = [os.path.basename(p) for _, p, _ in files if not os.path.isfile(p)]
            if missing:
                self.add("UI-08", "error", f"background {b.get('name')}", "missing " + ", ".join(missing))
            highs = [h for _, _, h in files if os.path.isfile(h)]
            if highs and len(highs) != len(files):
                self.add("UI-08", "error", f"background {b.get('name')}",
                         "HD set incomplete: missing " + ", ".join(os.path.basename(h) for _, _, h in files if not os.path.isfile(h)))
            if b.get("name") not in mod.unlock_names:
                self.add("MOD-15", "error", f"background {b.get('name')}", "no unlock of that name: it can never be obtained")
        folder = os.path.join(mod.dir, "backgrounds")
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                mm = re.fullmatch(r"bg_(.+?)(_day|_dusk|_night)?(_high)?\.png", f)
                if mm and mm.group(1) not in names:
                    self.add("UI-08", "info", f"backgrounds/{f}", "file not listed in module.json backgrounds")
        # MOD-12: a default background for every plain egg
        egg_bgs = collections.defaultdict(set)
        for u in mod.unlocks:
            if u.get("type") == "egg" and u.get("name") in names:
                egg_bgs[u.get("version")].add(u.get("name"))
        for m in mod.monsters:
            if m.get("stage") != 0 or m.get("special"):
                continue
            if not (egg_bgs.get(None) or egg_bgs.get(m.get("version"))):
                self.add("MOD-12", "error", f"egg {m.get('name')} v{m.get('version')}",
                         "hatching grants no background (no egg unlock for its version or null naming a background)")

    # ------------------------------------------------------------------ MOD-13/15
    def unlocks(self):
        mod = self.mod
        dup = [n for n, c in collections.Counter(u.get("name") for u in mod.unlocks).items() if c > 1]
        types = {}
        for u in mod.unlocks:
            types.setdefault(u.get("name"), set()).add(u.get("type"))
        for n in dup:
            if len(types[n]) > 1:
                self.add("MOD-13", "warn", f"unlock {n}", f"repeated with different types {sorted(types[n])}")
        egg_versions = {m.get("version") for m in mod.monsters if m.get("stage") == 0}
        all_names = set(mod.by_name)
        for u in mod.unlocks:
            n, t = u.get("name"), u.get("type")
            label = f"unlock {n} ({t})"
            if t not in ("egg", "adventure", "evolution", "digidex", "battle", "group", "pvp", "versus", "encounter"):
                self.add("MOD-13", "error", label, f"unknown type '{t}'")
            if t not in ("egg", "adventure", "evolution", "digidex", "battle", "group", "pvp", "versus", "encounter"):
                self.add("MOD-08", "error", label, f"type '{t}' is not in the editor's unlock combo")
            if t == "egg" and u.get("version") is not None and u["version"] not in egg_versions:
                self.add("MOD-13", "error", label, f"no egg of version {u['version']}")
            if t == "evolution":
                for x in u.get("to") or []:
                    if x not in all_names:
                        self.add("MOD-13", "error", label, f"'to' names missing monster '{x}'")
            if t == "group":
                for x in u.get("list") or []:
                    if x not in mod.unlock_names:
                        self.add("MOD-13", "error", label, f"group member '{x}' is not an unlock")
            if u.get("unlocks_area") is not None and u["unlocks_area"] not in mod.adventure_areas:
                self.add("MOD-13", "error", label, f"unlocks_area {u['unlocks_area']} has no adventure enemies")
            if t == "digidex" and u.get("amount") and u["amount"] > len({m.get('name') for m in mod.monsters if m.get('stage', 0) > 0}):
                self.add("MOD-13", "error", label, f"needs {u['amount']} Digimon; the module has fewer")
            if t in ("versus", "pvp"):
                self.add("MOD-13", "info", label, "obtainable only through a connection battle")
        for n, reason in sorted(getattr(self, "unlock_why", {}).items()):
            self.add("MOD-13", "error", f"unlock {n}", "not obtainable: " + reason)
        for m in mod.monsters:
            k = m.get("special_key")
            if m.get("special") and k and k != "gcell_fragment" and k not in mod.unlock_names:
                self.add("MOD-13", "error", f"{m.get('name')} v{m.get('version')}", f"special_key '{k}' is not an unlock")
            if m.get("special") and not k:
                self.add("MOD-13", "warn", f"{m.get('name')} v{m.get('version')}", "special without a special_key")
            for evo in m.get("evolve") or []:
                if evo.get("unlock") and evo["unlock"] not in mod.unlock_names:
                    self.add("MOD-13", "error", f"{m.get('name')} v{m.get('version')} -> {evo.get('to')}",
                             f"route needs unlock '{evo['unlock']}', which is not a module unlock")

    def references(self):
        mod = self.mod
        items, cur = mod.item_names, {c.get("name") for c in mod.currencies}
        for q in mod.quests:
            if q.get("reward_type") == 0 and q.get("reward_value") and q["reward_value"] not in items:
                self.add("MOD-15", "error", f"quest {q.get('name')}", f"reward item '{q['reward_value']}' not in item.json")
        for e in mod.events:
            if e.get("item") and e["item"] not in items:
                self.add("MOD-15", "error", f"event {e.get('name')}", f"item '{e['item']}' not in item.json")
            for name in e.get("item_pool") or []:
                if name not in items:
                    self.add("MOD-15", "error", f"event {e.get('name')}", f"pool item '{name}' not in item.json")
            if e.get("shop") and e["shop"] not in {s.get("name") for s in mod.shops}:
                self.add("MOD-15", "error", f"event {e.get('name')}", f"shop '{e['shop']}' not in shop.json")
        for r in (mod.connect_points or {}).get("rewards", []) if isinstance(mod.connect_points, dict) else []:
            if r.get("item") and r["item"] not in items:
                self.add("MOD-15", "error", "connect_points", f"reward item '{r['item']}' not in item.json")
        for s in mod.shops:
            if s.get("currency") and s["currency"] not in cur:
                self.add("MOD-15", "error", f"shop {s.get('name')}", f"currency '{s['currency']}' not in shop.json")
            if s.get("unlock") and s["unlock"] not in mod.unlock_names:
                self.add("MOD-15", "error", f"shop {s.get('name')}", f"unlock '{s['unlock']}' is not a module unlock")
            for it in s.get("items") or []:
                if it.get("item") and it["item"] not in items:
                    self.add("MOD-15", "error", f"shop {s.get('name')}", f"item '{it['item']}' not in item.json")
                if it.get("unlock") and it["unlock"] not in mod.unlock_names:
                    self.add("MOD-15", "error", f"shop {s.get('name')}", f"item unlock '{it['unlock']}' is not a module unlock")
        for c in mod.codes:
            if c.get("type") == "pet" and (c.get("pet"), c.get("version")) not in mod.by_key:
                self.add("MOD-15", "error", f"code {c.get('name')}", f"pet {c.get('pet')} v{c.get('version')} does not exist")
            if c.get("type") == "item" and c.get("item") and c["item"] not in items:
                self.add("MOD-15", "error", f"code {c.get('name')}", f"item '{c['item']}' not in item.json")
        # card packs and cards (cards.json) named by enemies, unlocks and shops
        cards = mod.cards if isinstance(mod.cards, dict) else {}
        pack_ids = {p.get("id") for p in cards.get("packs") or []}
        card_ids = {c.get("id") for c in cards.get("cards") or []}
        for p in cards.get("packs") or []:
            for entry in p.get("cards") or []:
                cid = entry.get("id") if isinstance(entry, dict) else entry
                if cid and cid not in card_ids:
                    self.add("MOD-15", "error", f"card pack {p.get('name')}", f"lists card {cid}, not in cards.json")
        refs = [(f"enemy {e.get('name')} a{e.get('area')} r{e.get('round')}", e.get("prize_card_pack"), None)
                for e in mod.enemies]
        refs += [(f"unlock {u.get('name')}", u.get("card_pack"), u.get("card")) for u in mod.unlocks]
        refs += [(f"shop {s.get('name')}", it.get("card_pack"), None)
                 for s in mod.shops for it in s.get("items") or []]
        refs += [(f"shop {s.get('name')} card offer", it.get("card_offer"), None)
                 for s in mod.shops for it in s.get("items") or []]
        # A card offer is priced by its card's rarity (rarity_prices), else
        # at its price: a rarity of its pack with neither is a free card.
        rarity_of = {c.get("id"): c.get("rarity") or "Common" for c in cards.get("cards") or []}
        packs_by_id = {p.get("id"): p for p in cards.get("packs") or []}
        for s in mod.shops:
            for it in s.get("items") or []:
                pack = packs_by_id.get(it.get("card_offer"))
                if not pack:
                    continue
                prices = it.get("rarity_prices") or {}
                rarities = {rarity_of.get(e.get("id") if isinstance(e, dict) else e) for e in pack.get("cards") or []}
                free = sorted(r for r in rarities if r and not prices.get(r) and not it.get("price"))
                if free:
                    self.add("MOD-15", "warn", f"shop {s.get('name')} card offer",
                             f"no price for {', '.join(free)} cards of {pack.get('id')}")
        for label, pack, card in refs:
            if pack and pack not in pack_ids:
                self.add("MOD-15", "error", label, f"card pack {pack} is not in cards.json")
            if card and card not in card_ids:
                self.add("MOD-15", "error", label, f"card {card} is not in cards.json")
        folder = os.path.join(mod.dir, "items")
        for i in mod.items:
            sp = (i.get("sprite_name") or "").strip()
            if not sp:
                self.add("MOD-15", "warn", f"item {i.get('name')}", "no sprite_name")
            elif not (os.path.isfile(os.path.join(folder, sp + ".png")) or os.path.isfile(os.path.join(folder, sp))
                      or os.path.isfile(os.path.join(ASSETS, "items", sp + ".png"))):
                self.add("MOD-15", "error", f"item {i.get('name')}", f"sprite items/{sp}.png missing")

    def run(self):
        self.module_art()
        self.devices()
        reach = self.reachability()
        self.routes()
        self.monster_sprites(reach)
        self.metadata(reach)
        self.enemies()
        self.backgrounds()
        self.unlocks()
        self.references()
        self.files()
        return self.findings

    def files(self):
        """MOD-18: the folder holds only what the game loads (module_files.py)."""
        from module_files import check_module
        for level, path, reason in check_module(self.mod.dir):
            self.add("MOD-18", level, path, reason)


def audit(name):
    if not os.path.isfile(os.path.join(MODULES, name, "module.json")):
        return [{"module": name, "check": "MOD-00", "severity": "error", "subject": "module.json",
                 "detail": "module folder or module.json missing"}]
    try:
        return Audit(Module(name)).run()
    except Exception as exc:  # a broken file must not hide the other modules
        import traceback
        return [{"module": name, "check": "MOD-00", "severity": "error", "subject": "audit",
                 "detail": f"audit crashed: {exc!r}\n{traceback.format_exc()}"}]


def markdown(findings, modules):
    lines = ["# Module audit", ""]
    checks = sorted({f["check"] for f in findings})
    lines += ["| Module | " + " | ".join(checks) + " |", "|---|" + "---|" * len(checks)]
    for m in modules:
        row = []
        for c in checks:
            e = sum(1 for f in findings if f["module"] == m and f["check"] == c and f["severity"] == "error")
            w = sum(1 for f in findings if f["module"] == m and f["check"] == c and f["severity"] == "warn")
            row.append((f"**{e}**" if e else "") + (f" ({w}w)" if w else "") or "·")
        lines.append(f"| {m} | " + " | ".join(row) + " |")
    lines += ["", "Bold: errors; (Nw): warnings; ·: clean.", ""]
    for m in modules:
        fs = [f for f in findings if f["module"] == m and f["severity"] != "info"]
        info = [f for f in findings if f["module"] == m and f["severity"] == "info"]
        lines += [f"## {m}", ""]
        if not fs:
            lines.append("No errors or warnings.")
        for c in sorted({f["check"] for f in fs}):
            group = [f for f in fs if f["check"] == c]
            lines.append(f"### {c} ({len(group)})")
            lines.append("")
            for f in sorted(group, key=lambda f: (f["severity"], f["subject"])):
                lines.append(f"- {'**E**' if f['severity'] == 'error' else 'W'} {f['subject']}: {f['detail']}")
            lines.append("")
        if info:
            lines.append(f"<details><summary>{len(info)} info</summary>")
            lines.append("")
            lines += [f"- {f['check']} {f['subject']}: {f['detail']}" for f in info]
            lines += ["", "</details>"]
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modules", nargs="*")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    modules = args.modules or RELEASE_MODULES
    findings = []
    for m in modules:
        findings += audit(m)
    for m in modules:
        fs = [f for f in findings if f["module"] == m]
        e = sum(f["severity"] == "error" for f in fs)
        w = sum(f["severity"] == "warn" for f in fs)
        by = collections.Counter(f["check"] for f in fs if f["severity"] == "error")
        print(f"{m:6} {e:5} errors {w:5} warnings   " + " ".join(f"{c}:{n}" for c, n in sorted(by.items())))
        if not args.quiet:
            for f in fs:
                if f["severity"] == "error":
                    print(f"         {f['check']} {f['subject']}: {f['detail']}"[:220])
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(findings, fh, indent=1, ensure_ascii=False)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(markdown(findings, modules))
    sys.exit(1 if any(f["severity"] == "error" for f in findings) else 0)


if __name__ == "__main__":
    main()
