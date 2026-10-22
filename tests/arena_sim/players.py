# -*- coding: utf-8 -*-
"""Simulated arena players that play through the public API.

Each player owns real ``GamePet`` objects (its save), picks a team with the
game's own eligibility rules (``_pet_passes``) and uploads it with the
game's own ``_pet_to_upload``, through its own instance of the game's
``OmninetService``. Between seasons it raises new pets when the season's
rules need them and evolves some of its veterans (``GamePet.evolve_to``),
which is what lets a Digimon come back for another season.

Some players also probe the server's defences once per season: a team
re-using a pet that already fought in that form, an edited species value,
a pet of an unpublished module, a wrong team size, a second team. Each
probe must be refused; the result goes into the report.

The process must have the game booted headless (``harness.Env``) before
any pet is built.
"""
import copy
import random

from simlib import log, player_service

STYLES = ("strong", "random", "loyal", "balanced")

#: Species the server refused as "does not match the server's data": the
#: checkout's module differs from the one the server holds at the same
#: version (an edit not published yet). Players stop raising them, as a
#: player whose pet was refused would pick another. (module, name, version)
DRIFTED = set()


def drifted_from(message, pets):
    """The (module, name, version) of the pets a refusal names, or []."""
    message = str(message)
    marker = " does not match the server's "
    if marker not in message:
        return []
    name = message.split(marker)[0].strip()
    module = message.split(marker)[1].split(" data")[0].strip()
    return [(getattr(p, "module", module), p.name, getattr(p, "version", None))
            for p in pets if p.name == name and getattr(p, "module", None) == module]


def _status_for(pet):
    return {"level": pet.level, "strength": pet.strength, "hunger": pet.hunger,
            "weight": pet.weight, "effort": pet.effort}


class Catalog:
    """Battle-capable species of the modules the server fields."""

    def __init__(self, module_names, unpublished=()):
        from battle.arena import engine
        from utils.module_utils import get_module
        self.modules = list(module_names)
        self.unpublished = [m for m in unpublished if get_module(m)]
        self.entries = []          # (module, monster dict)
        cat = engine.Catalog(_modules_dir())
        for name in self.modules + self.unpublished:
            mod = cat.module(name)
            game_mod = get_module(name)
            if not mod or not game_mod:
                continue
            for (mname, version), monster in mod["monsters"].items():
                if mname is None or version is None:
                    continue
                try:
                    engine.build_entry(cat, {"module_name": name, "name": mname,
                                             "pet_version": version})
                except engine.ArenaError:
                    continue
                if game_mod.get_monster(mname, version) is None:
                    continue
                self.entries.append((name, monster))

    def matching(self, restrictions, unpublished=False):
        from battle.arena.engine import normalize_attribute, ArenaError
        restrictions = restrictions or {}
        out = []
        pool = self.unpublished if unpublished else self.modules
        for module, monster in self.entries:
            if module not in pool:
                continue
            if (module, monster.get("name"), monster.get("version")) in DRIFTED:
                continue
            stages = restrictions.get("allowed_stages")
            if stages and monster.get("stage") not in stages:
                continue
            mods = restrictions.get("allowed_modules")
            if mods and module not in mods:
                continue
            attrs = restrictions.get("allowed_attributes")
            if attrs:
                try:
                    allowed = {normalize_attribute(a) for a in attrs}
                    if normalize_attribute(monster.get("attribute")) not in allowed:
                        continue
                except ArenaError:
                    continue
            out.append((module, monster))
        return out


def _modules_dir():
    import os
    from simlib import ROOT
    return os.path.join(ROOT, "modules")


def make_pet(module, monster, rng):
    """A raised pet of *monster*: random but plausible care."""
    from core import pet_stats
    from models.game_pet import GamePet
    from utils.module_utils import get_module
    from utils import arena_pets
    data = dict(get_module(module).get_monster(monster["name"], monster["version"]), module=module)
    pet = GamePet(data, traited=rng.random() < 0.15)
    stage = int(pet.stage or 0)
    stomach = max(0, int(getattr(pet, "stomach", 4) or 4))
    pet.level = rng.randint(1, max(1, pet_stats.MAX_LEVEL.get(stage, 1)))
    pet.strength = rng.randint(0, stomach)
    pet.hunger = rng.randint(min(1, stomach), stomach)
    min_weight = int(getattr(pet, "min_weight", 0) or 0)
    pet.weight = rng.randint(min_weight, min(99, min_weight + 25))
    pet.effort = rng.randint(0, 30)
    pet.shook = rng.random() < 0.1
    arena_pets.pet_uid(pet)
    return pet


def battle_strength(pet):
    try:
        return int(pet.get_power() or 0) * 2 + int(pet.get_hp() or 0)
    except Exception:  # pylint: disable=broad-except
        return int(getattr(pet, "power", 0) or 0)


class SimPlayer:
    def __init__(self, account, rng, style):
        self.nickname = account["nickname"]
        self.user_id = account["user_id"]
        self.key = account["device_key"]
        self.svc = player_service(self.key)
        self.rng = rng
        self.style = style
        self.pets = []
        self.team = None
        self.history = []          # per season: what happened
        self.kind = "api"

    # ------------------------------------------------------------ roster
    def raise_pets(self, catalog, restrictions, count):
        options = catalog.matching(restrictions)
        added = []
        for _ in range(count):
            if not options:
                break
            module, monster = self.rng.choice(options)
            pet = make_pet(module, monster, self.rng)
            self.pets.append(pet)
            added.append(pet)
        return added

    def eligible(self, season, server_modules):
        from scenes.connect_views.arena_team_creation_view import _pet_passes
        restrictions = season.get("restrictions") or {}
        out = []
        for pet in self.pets:
            if getattr(pet, "arena_pending", None):
                continue                      # still on a team
            ok, _reason = _pet_passes(pet, restrictions, server_modules, season.get("id"))
            if ok:
                out.append(pet)
        return out

    def choose(self, pool, size):
        if self.style == "strong":
            return sorted(pool, key=battle_strength, reverse=True)[:size]
        if self.style == "balanced":
            ranked = sorted(pool, key=battle_strength, reverse=True)
            middle = ranked[len(ranked) // 4:] or ranked
            return middle[:size]
        return self.rng.sample(pool, size)

    def team_size(self, low, high):
        if low == high:
            return low
        # Most players field a full team; a few try smaller ones.
        return high if self.rng.random() < 0.7 else self.rng.randint(low, high)

    # ------------------------------------------------------------ registration
    def upload(self, pets):
        from scenes.connect_views.arena_team_creation_view import _pet_to_upload
        return [_pet_to_upload(p) for p in pets]

    def register(self, season, catalog, server_modules, probes=()):
        """Build and register a team; run the asked *probes* first.

        Returns a dict for the report: team, size, probes (each with
        expected refusal and what the server said).
        """
        from scenes.connect_views.arena_team_creation_view import team_size_range
        from utils import arena_pets
        restrictions = season.get("restrictions") or {}
        low, high = team_size_range(season)
        size = self.team_size(low, high)
        pool = self.eligible(season, server_modules)
        if len(pool) < size + 1:
            self.raise_pets(catalog, restrictions, size + 2 - len(pool))
            pool = self.eligible(season, server_modules)
        record = {"player": self.nickname, "kind": self.kind, "style": self.style,
                  "size": size, "probes": []}
        if len(pool) < size:
            record["error"] = f"only {len(pool)} eligible pets"
            return record
        chosen = self.choose(pool, size)

        for probe in probes:
            if probe != "second_team":
                record["probes"].append(self.probe(probe, season, catalog, chosen, low, high))

        ok, data = self.svc.create_team(self.upload(chosen))
        for _ in range(3):
            drifted = [] if ok else drifted_from(data, chosen)
            if not drifted:
                break
            # The server holds other data for this species at this module
            # version: put the pet away and register with another.
            DRIFTED.update(drifted)
            record.setdefault("drifted", []).extend(f"{m}/{n} v{v}" for m, n, v in drifted)
            self.pets = [p for p in self.pets
                         if (getattr(p, "module", None), p.name, getattr(p, "version", None))
                         not in DRIFTED]
            pool = self.eligible(season, server_modules)
            if len(pool) < size:
                self.raise_pets(catalog, restrictions, size + 1 - len(pool))
                pool = self.eligible(season, server_modules)
            if len(pool) < size:
                break
            chosen = self.choose(pool, size)
            ok, data = self.svc.create_team(self.upload(chosen))
        if not ok:
            record["error"] = str(data)
            return record
        self.team = data
        arena_pets.mark_team(chosen, data)
        for pet in chosen:
            pet.arena_lock = {"team_id": str(data["id"]), "until": 0}
        record.update(team_id=data["id"], pets=[p.name for p in chosen],
                      uids=[arena_pets.pet_uid(p) for p in chosen],
                      daily=data.get("daily_battles_remaining"))
        # A second team in the same season is always refused.
        if "second_team" in probes:
            spare = [p for p in self.eligible(season, server_modules) if p not in chosen]
            if len(spare) < size:
                spare = self.raise_pets(catalog, restrictions, size)
            ok2, data2 = self.svc.create_team(self.upload(spare[:size]))
            answer = str(data2)[:160] if not ok2 else "ACCEPTED"
            record["probes"].append({"probe": "second_team", "refused": not ok2,
                                     "answer": answer, "expected": "per season",
                                     "matches": (not ok2) and "per season" in answer})
        return record

    def probe(self, kind, season, catalog, chosen, low, high):
        """One deliberate abuse; the server must refuse it."""
        from utils import arena_pets
        uploads = self.upload(chosen)
        expect = None
        if kind == "edited_stats":
            uploads[0]["base"] = dict(uploads[0]["base"], power=uploads[0]["base"]["power"] + 40)
            expect = "does not match"
        elif kind == "unpublished":
            options = catalog.matching({}, unpublished=True)
            if not options:
                return {"probe": kind, "skipped": "no unpublished module installed"}
            module, monster = self.rng.choice(options)
            pet = make_pet(module, monster, self.rng)
            uploads[0] = self.upload([pet])[0]
            expect = "not a published module"
        elif kind == "veteran":
            veterans = [p for p in self.pets if arena_pets.fought_form(p, season.get("id"))
                        and not getattr(p, "arena_pending", None)]
            if not veterans:
                return {"probe": kind, "skipped": "no veteran"}
            uploads[0] = self.upload([veterans[0]])[0]
            expect = "already fought"
        elif kind == "wrong_size":
            if high < 3:
                extra = self.raise_pets(catalog, season.get("restrictions") or {}, 1)
                uploads = uploads + self.upload(extra)
                while len(uploads) <= high:
                    uploads = uploads + self.upload(self.raise_pets(
                        catalog, season.get("restrictions") or {}, 1))
            elif low > 1:
                uploads = uploads[:low - 1]
            else:
                return {"probe": kind, "skipped": "every size 1-3 is legal"}
            expect = "Digimon"
        elif kind == "duplicate":
            uploads = [uploads[0], copy.deepcopy(uploads[0])] + uploads[1:2]
            uploads = uploads[:max(2, high)] if high >= 2 else None
            if not uploads:
                return {"probe": kind, "skipped": "solo season"}
            expect = "twice"
        else:
            return {"probe": kind, "skipped": "unknown"}
        ok, data = self.svc.create_team(uploads)
        answer = str(data)[:160]
        return {"probe": kind, "refused": not ok, "answer": answer if not ok else "ACCEPTED",
                "expected": expect, "matches": (not ok) and (expect or "") in answer}

    # ------------------------------------------------------------ battles
    def attack(self):
        ok, data = self.svc.find_battle(self.team["id"])
        if not ok or not isinstance(data, dict):
            return {"ok": False, "message": str(data)}
        if not data.get("battle_found"):
            return {"ok": False, "message": data.get("message"),
                    "remaining": data.get("daily_battles_remaining")}
        return {"ok": True, "battle": data["battle"],
                "remaining": data.get("daily_battles_remaining")}

    # ------------------------------------------------------------ season end
    def apply_results(self, team_detail):
        """The game's own matching and record update, on this player's pets."""
        from utils import arena_pets
        team_id = str(team_detail.get("id"))
        waiting = [p for p in self.pets
                   if str((getattr(p, "arena_pending", None) or {}).get("team_id", "")) == team_id]
        applied = [arena_pets._apply(pet, row, team_detail)
                   for pet, row in arena_pets._match(waiting, team_detail.get("pets") or [])]
        return applied

    def evolve_some(self, chance=0.6):
        """Evolve veterans (a real evolution of the pet object)."""
        from utils.module_utils import get_module
        evolved = []
        for pet in self.pets:
            if getattr(pet, "arena_pending", None) or not getattr(pet, "arena_history", None):
                continue
            if self.rng.random() > chance:
                continue
            module = get_module(pet.module)
            data = module.get_monster(pet.name, pet.version) if module else None
            targets = [e.get("to") for e in (data or {}).get("evolve", []) if e.get("to")]
            targets = [t for t in targets if module.get_monster(t, pet.version)]
            if not targets:
                continue
            before = pet.name
            target = self.rng.choice(targets)
            if pet.evolve_to(target, pet.version, reward=False) is not False:
                pet.level = self.rng.randint(1, 3)
                evolved.append(f"{before}->{pet.name}")
        return evolved
