# -*- coding: utf-8 -*-
"""What an adventure round pays, and what it costs, on each module's rules.

Checklist BAT-03 (each module's adventure follows its own rules) and BAT-04
(adventure mode works). For every release module with ``adventure_mode``
(DW1 left out while it is being built), a Child of the module's own roster
fights area 1 headless, the round's outcome settled in advance
(battle_flow.force_outcome: the real simulator still fights it) and the
random rolls fixed (battle_flow.ProxyRandom on the encounter's and the pet's
``random``), so every rule is checked against the module's own data:

win    the pet's win count, experience, the enemy's ``prize`` (an item with
       ``prize_chance`` unset is certain; one under 100 drops only on a roll
       under it -- the iC's 10% card pack), the module's ``currency_reward``
       (the iC's Fight Money), and progress -- the next round of the area,
       the next area when the round was the area's last, a sequential
       module going straight on to its next round;
boss   beating area 1's last round opens area 2 and grants the module's
       ``adventure`` unlocks for area 1 -- those of the pet's own version
       (module-rules: ``version`` selects unlocks) -- on Area Selection modules;
loss   nothing is paid and the player is sent back to round 1;
cost   ``battle_cost_type`` (DP or Hunger) is charged once, won or lost;
sick   ``battle_base_sick_chance_win/_lose`` and the species'
       ``injury_probability`` are honoured: a roll under the chance makes
       the pet sick, a roll over it does not.

Known bugs are written as the correct expectation and marked
expectedFailure (tests/findings/battle.md): BAT-F1 (a fresh DMM pet has no
battle record), BAT-F3 (``injury_probability`` is never loaded), BAT-F4
(a win that spends the last of the battle cost records no progress) and
BAT-F9 (adventure unlocks ignore their version).
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import battle_flow as bf  # noqa: E402

MODULE_NAMES = bf.adventure_modules() if os.path.isdir(bf.MODULES) else []
#: A roll no chance below 99.9% passes, and one every chance above 0 does.
NEVER, ALWAYS = 0.999, 0.0


@unittest.skipUnless(MODULE_NAMES, "modules folder not present")
class AdventureRewards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    # ------------------------------------------------------------ helpers
    def fight(self, module_name, area, round_num, win, roll, make_pet=None, seed=1,
              give_record=True):
        """One settled round with every random() in the encounter and the pet
        returning *roll*. *make_pet* builds the pet after the reset (default:
        the module's first Child). Returns (result, pet, before, after)."""
        import battle.battle_encounter as encounter_module
        import models.game_pet as pet_module
        from battle.battle_encounter import BattleEncounter
        from harness import quiet
        env = self.env
        bf.fresh(env, seed=seed)
        pet = (make_pet or (lambda: bf.battle_pet(module_name)))()
        if give_record:
            bf.ensure_battle_record(pet)   # BAT-F1; see test_a_fresh_pet_can_battle
        bf.set_party(env, [pet])
        before = self.state(module_name, pet)
        with patch.object(encounter_module, "random", bf.ProxyRandom(roll, seed)), \
                patch.object(pet_module, "random", bf.ProxyRandom(roll, seed)):
            with quiet():
                encounter = BattleEncounter(module_name, area, round_num, 1)
            result = bf.run_round(env, encounter, draw_every=0, win=win, skip_battle=True)
        result["encounter"] = encounter
        self.assertEqual(result["victory"], "Victory" if win else "Defeat", result["phases"])
        self.assertNotEqual(result["outcome"], "timeout", result["phases"])
        self.assertEqual(bf.battle_errors(env), [])
        return result, pet, before, self.state(module_name, pet)

    def state(self, module_name, pet):
        from utils import currency_utils
        from utils.utils_unlocks import is_unlocked
        gg = self.env.gg
        module = self.module(module_name)
        currencies = {c.get("name"): currency_utils.get_balance(module_name, c.get("name"))
                      for c in (getattr(module, "currencies", None) or [])}
        unlocked = {u.get("name") for u in getattr(module, "unlocks", None) or []
                    if u.get("type") == "adventure" and is_unlocked(module_name, "adventure", u.get("name"))}
        return {"battles": getattr(pet, "battles", None), "win": getattr(pet, "win", None),
                "dp": pet.dp, "hunger": pet.hunger, "sick": pet.sick,
                "area": gg.battle_area.get(module_name, 1), "round": gg.battle_round.get(module_name, 1),
                "victories": gg.total_victories.get(module_name, 0),
                "inventory": dict(gg.inventory), "currencies": currencies, "unlocked": unlocked}

    @staticmethod
    def module(module_name):
        from utils.module_utils import get_module
        return get_module(module_name)

    def assert_cost_charged_once(self, module_name, before, after):
        module = self.module(module_name)
        cost_type = getattr(module, "battle_cost_type", "DP")
        cost = getattr(module, "battle_cost_amount", 1.0)
        self.assertEqual(after["battles"], before["battles"] + 1)
        if cost_type == "DP":
            self.assertEqual((after["dp"], after["hunger"]), (max(0, before["dp"] - cost), before["hunger"]))
        elif cost_type == "Hunger":
            self.assertEqual((after["dp"], after["hunger"]), (before["dp"], max(0, before["hunger"] - cost)))
        else:
            self.assertEqual((after["dp"], after["hunger"]), (before["dp"], before["hunger"]))

    def assert_prize(self, snapshot, roll, before, after):
        """The prize a won round pays, read off the round's own enemies."""
        enemies = [e for e in snapshot["enemies"] if e is not None]
        items = [e for e in enemies if getattr(e, "prize", None)]
        packs = [e for e in enemies if getattr(e, "prize_card_pack", None)]
        if len(items) + len(packs) > 1:
            return      # one prize is drawn at random among several: no fixed expectation
        for enemy in items + packs:
            chance = getattr(enemy, "prize_chance", None)
            chance = 100 if chance is None else chance
            drops = roll * 100 < chance
            if enemy in packs:
                self.assertEqual(bool(snapshot["prize_pack"]), drops,
                                 f"card pack at {chance}% with a roll of {roll}")
                continue
            prize = snapshot["prize_item"]
            if not drops:
                self.assertIsNone(prize, f"{enemy.prize} dropped at {chance}%")
                self.assertEqual(after["inventory"], before["inventory"])
                continue
            self.assertIsNotNone(prize, f"{enemy.prize} ({chance}%) did not drop")
            self.assertEqual(prize.name, enemy.prize)
            self.assertEqual(after["inventory"].get(prize.id, 0), before["inventory"].get(prize.id, 0) + 1)
        if not items:
            self.assertIsNone(snapshot["prize_item"], "an item came from an enemy that carries none")
            self.assertEqual(after["inventory"], before["inventory"])

    def assert_currency(self, snapshot, before, after, won):
        enemies = [e for e in snapshot["enemies"] if e is not None]
        paid = {}
        if won and enemies:
            best = max(enemies, key=lambda e: int(getattr(e, "currency_reward", 0) or 0))
            amount = int(getattr(best, "currency_reward", 0) or 0)
            if amount and getattr(best, "currency", ""):
                paid[best.currency] = amount
        for name, balance in before["currencies"].items():
            self.assertEqual(after["currencies"][name], balance + paid.get(name, 0),
                             f"{name}: expected +{paid.get(name, 0)}")

    def expected_next(self, module_name, area, round_num, version):
        """(area, round) the player is on after winning *area*/*round_num*."""
        module = self.module(module_name)
        rounds = module.get_area_round_counts()[area]
        if round_num < rounds:
            return area, round_num + 1
        if module.area_exists(area + 1) and module.is_area_unlocked(area + 1, version):
            return area + 1, 1
        return area, round_num

    # ------------------------------------------------------------ the rules
    def win_pays_and_progresses(self, module_name):
        """a win pays its experience, prize and currency and moves the player on"""
        module = self.module(module_name)
        result, pet, before, after = self.fight(module_name, 1, 1, True, NEVER)
        snapshot = result["snapshot"]
        self.assertEqual(after["win"], before["win"] + 1)
        self.assertGreater(snapshot["xp"], 0, "a win paid no experience")
        self.assert_cost_charged_once(module_name, before, after)
        self.assert_prize(snapshot, NEVER, before, after)
        self.assert_currency(snapshot, before, after, won=True)
        self.assertEqual(after["sick"], 0, "sick from a roll above every chance")

        area, round_num = self.expected_next(module_name, 1, 1, pet.version)
        self.assertEqual((after["area"], after["round"]), (area, round_num), "progress after the win")
        if round_num > 1 and module.battle_sequential_rounds:
            self.assertEqual(result["outcome"], "level", "a sequential module did not go on")
            self.assertEqual(result["encounter"].round, 2)
        else:
            self.assertEqual(result["outcome"], "scene")
            self.assertEqual(after["victories"], before["victories"] + 1)

    def boss_win_opens_the_next_area(self, module_name):
        """beating area 1's last round opens area 2 and grants its own version's unlocks"""
        module = self.module(module_name)
        last = module.get_area_round_counts()[1]
        result, pet, before, after = self.fight(module_name, 1, last, True, ALWAYS)
        snapshot = result["snapshot"]
        self.assertTrue(snapshot["boss"], f"area 1 round {last} is not a boss")
        self.assertEqual(result["outcome"], "scene")
        self.assertEqual((after["area"], after["round"]), self.expected_next(module_name, 1, last, pet.version))
        self.assertEqual(after["victories"], before["victories"] + 1)
        self.assert_prize(snapshot, ALWAYS, before, after)
        self.assert_currency(snapshot, before, after, won=True)
        keys = {getattr(e, "unlock", None) for e in snapshot["enemies"] if e is not None}
        versions = {m.get("version") for m in module.get_all_monsters()}
        for unlock in getattr(module, "unlocks", None) or []:
            name = unlock.get("name")
            if unlock.get("type") != "adventure" or name in before["unlocked"]:
                continue
            if not (unlock.get("area") == 1 or (unlock.get("area") is None and name in keys)):
                continue
            # No version is every version. So is 0 on a module that has no
            # version-0 Digimon (D-3's backgrounds): it can scope nothing.
            version = unlock.get("version")
            unscoped = version is None or (version == 0 and 0 not in versions)
            own_version = unscoped or version == pet.version
            self.assertEqual(name in after["unlocked"], own_version,
                             f"adventure unlock {name} (version {unlock.get('version')}) "
                             f"after a version-{pet.version} pet cleared area 1")

    def loss_pays_nothing(self, module_name):
        """a loss pays nothing, costs the battle and resets the round"""
        result, pet, before, after = self.fight(module_name, 1, 1, False, NEVER)
        snapshot = result["snapshot"]
        self.assertEqual(result["outcome"], "scene")
        self.assertEqual(after["win"], before["win"])
        self.assertEqual(snapshot["xp"], 0)
        self.assertIsNone(getattr(result["encounter"], "prize_item", None))
        self.assertEqual(after["inventory"], before["inventory"])
        self.assert_currency(snapshot, before, after, won=False)
        self.assertEqual((after["area"], after["round"]), (before["area"], 1))
        self.assertEqual(after["victories"], before["victories"])
        self.assertEqual(after["unlocked"], before["unlocked"])
        self.assert_cost_charged_once(module_name, before, after)
        self.assertEqual(after["sick"], 0, "sick from a roll above every chance")

    def sickness_chances(self, module_name):
        """the module's sick chances and the species' injury chance are honoured"""
        module = self.module(module_name)
        for win, chance in ((True, module.battle_base_sick_chance_win),
                            (False, module.battle_base_sick_chance_lose)):
            with self.subTest(win=win):
                _, pet, _, after = self.fight(module_name, 1, 1, win, ALWAYS)
                injury = int(self.species(module_name, pet.name).get("injury_probability", 0) or 0)
                expected = chance > 0 or (not win and injury > 0)
                self.assertEqual(after["sick"] > 0, expected,
                                 f"{'win' if win else 'loss'}: sick chance {chance}%, "
                                 f"injury {injury}%, every roll 0")

    def species(self, module_name, name):
        return next(m for m in self.module(module_name).get_all_monsters() if m.get("name") == name)

    # ------------------------------------------------------------ single cases
    def test_a_prize_chance_below_certain_can_miss(self):
        """An enemy whose ``prize_chance`` is under 100 drops its prize on a
        roll under the chance and not on one over it (the first such enemy
        among the release modules' adventure rounds: the iC's 10% card pack)."""
        found = None
        for module_name in MODULE_NAMES:
            module = self.module(module_name)
            for entry in module._parse_battle_json(os.path.join(module.folder_path, "battle.json")):
                chance = entry.get("prize_chance")
                if (not entry.get("special_encounter") and chance is not None and 0 < chance < 100
                        and (entry.get("prize") or entry.get("prize_card_pack"))
                        and module.get_enemy_versions(entry["area"], entry["round"]) == [entry["version"]]):
                    found = (module_name, entry)
                    break
            if found:
                break
        if not found:
            self.skipTest("no adventure enemy has a prize_chance under 100")
        module_name, entry = found
        for roll in (NEVER, ALWAYS):
            with self.subTest(module=module_name, enemy=entry["name"], chance=entry["prize_chance"], roll=roll):
                result, pet, before, after = self.fight(
                    module_name, entry["area"], entry["round"], True, roll,
                    make_pet=lambda: bf.battle_pet(module_name, version=entry["version"]))
                self.assertEqual([e.name for e in result["snapshot"]["enemies"]], [entry["name"]])
                self.assert_prize(result["snapshot"], roll, before, after)

    # Fixed 2026-10-13; kept as a regression test.
    def test_the_species_injury_chance_is_honoured(self):
        """A loss injures at the species' own ``injury_probability``: a roll
        between the module's sick chance and the species' injury chance
        makes the pet sick (DMM: 0% sick, 10% injury; iC: per species)."""
        checked = 0
        for module_name in ("DMM", "IC"):
            if module_name not in MODULE_NAMES:
                continue
            module = self.module(module_name)
            sick = module.battle_base_sick_chance_lose
            records = [m for m in module.get_all_monsters()
                       if (m.get("stage") or 0) >= 3 and (m.get("power") or 0) > 0
                       and (m.get("atk_main") or 0) > 0
                       and int(m.get("injury_probability", 0) or 0) > sick]
            if not records:
                continue
            record = max(records, key=lambda m: int(m["injury_probability"]))
            injury = int(record["injury_probability"])
            roll = (sick + injury) / 200.0
            with self.subTest(module=module_name, species=record["name"], injury=injury):
                _, pet, before, after = self.fight(
                    module_name, 1, 1, False, roll,
                    make_pet=lambda: bf.battle_pet(module_name, stage=record["stage"], name=record["name"]))
                self.assertGreater(after["sick"], 0, f"a roll of {roll:.3f} under {injury}% did not injure")
                checked += 1
        if not checked:
            self.skipTest("no installed module gives a species injury chance")

    # Fixed 2026-10-13; kept as a regression test.
    def test_a_win_with_the_last_dp_still_counts(self):
        """Winning with the battle cost's last DP still clears the round: on a
        module that fights one battle at a time (not sequential), the area
        won is the player's even though the pet must rest before the next."""
        cases = [m for m in MODULE_NAMES
                 if not self.module(m).battle_sequential_rounds
                 and getattr(self.module(m), "battle_cost_type", "DP") == "DP"]
        if not cases:
            self.skipTest("no non-sequential DP module installed")
        for module_name in cases:
            with self.subTest(module=module_name):
                def last_dp(name=module_name):
                    pet = bf.battle_pet(name)
                    pet.dp = self.module(name).battle_cost_amount
                    return pet
                result, pet, before, after = self.fight(module_name, 1, 1, True, NEVER, make_pet=last_dp)
                self.assertEqual(after["dp"], 0)
                self.assertEqual((after["area"], after["round"]),
                                 self.expected_next(module_name, 1, 1, pet.version))
                self.assertEqual(after["victories"], before["victories"] + 1)

    # Fixed 2026-10-13; kept as a regression test.
    def test_a_fresh_pet_can_battle(self):
        """A pet straight from its module's roster, never given a battle
        record by hand, fights its first adventure battle -- including on
        DMM, whose module keeps the battle counts across evolutions."""
        keeping = [m for m in MODULE_NAMES
                   if getattr(self.module(m), "battle_keep_counts_on_evolution", False)]
        if not keeping:
            self.skipTest("no installed release module keeps its battle counts")
        for module_name in keeping:
            with self.subTest(module=module_name):
                self.assertEqual(
                    tuple(getattr(bf.battle_pet(module_name), a, None) for a in ("battles", "win")), (0, 0))
                self.fight(module_name, 1, 1, True, NEVER, give_record=False)


#: Known bugs: (module, rule) -> finding id (tests/findings/battle.md).
KNOWN = {
    ("VBE", "boss_win_opens_the_next_area"): "BAT-F9",
}


def _make(rule, module_name):
    def test(self):
        getattr(self, rule)(module_name)
    test.__doc__ = f"{module_name}: {getattr(AdventureRewards, rule).__doc__}."
    if (module_name, rule) in KNOWN:
        test = unittest.expectedFailure(test)
    return test


def _area_selection(module_name):
    with open(os.path.join(bf.MODULES, module_name, "module.json"), encoding="utf-8-sig") as fh:
        return json.load(fh).get("adventure_style", "Area Selection") == "Area Selection"


# One test per module and rule, so one module's failure does not hide another's.
for _name in MODULE_NAMES:
    for _rule in ("win_pays_and_progresses", "loss_pays_nothing", "sickness_chances"):
        setattr(AdventureRewards, f"test_{bf.method_name(_name)}_{_rule}", _make(_rule, _name))
    if _area_selection(_name):
        setattr(AdventureRewards, f"test_{bf.method_name(_name)}_boss_win_opens_the_next_area",
                _make("boss_win_opens_the_next_area", _name))


if __name__ == "__main__":
    unittest.main()
