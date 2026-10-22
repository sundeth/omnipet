"""Every PvP battle counts toward the battle record (owner, 2026-10-21: "all
pvp battles (including versus) should add to the battle and win
counters"). A local Versus, a DCom battle with a device and an online one
all end in GamePet.finish_versus: battles, win, totalBattles and totalWin
move as after an adventure battle, so the battle and win-ratio routes (the
iC's 20/50 wins, the Mini's battle gates, the 1997 DM's 15 battles) can be
met by connection too. A connection also counts its PvP win (the
connection unlocks read pvp_wins; a Versus between the player's own pets
does not) and pays G-Cells as a battle with another device. The arena's
battles are fought on the server and only replayed here.

The DCom path is played end to end, on every battle format, in
tests/game/battle/test_dcom_fake_device.py.
"""
import ast
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests", "unit", "android"))

from core import runtime_globals  # noqa: E402
from models.game_pet import GamePet  # noqa: E402
from test_android_offline import module, pet  # noqa: E402


class FinishVersus(unittest.TestCase):
    def setUp(self):
        for target in ("game_console", "game_sound"):
            p = patch.object(runtime_globals, target, SimpleNamespace(log=lambda *_: None, play=lambda *_: None))
            p.start()
            self.addCleanup(p.stop)
        self.mod = module(battle_cost_type="Nothing", battle_base_sick_chance_win=0,
                          battle_base_sick_chance_lose=0, protein_overdose_max=0, protein_penalty=0,
                          disturbance_penalty_max=0)

    def fight(self, won, connection, opponent_module="Test"):
        p = pet(self.mod, battles=2, win=1, totalBattles=10, totalWin=6, pvp_battles=0, pvp_wins=0,
                protein_overdose=0, disturbance_penalty=0)
        events = []
        opponent = SimpleNamespace(name="Gabumon", version=1, module=opponent_module)
        with patch("models.game_pet.get_module", return_value=self.mod), \
                patch.object(GamePet, "_gcell_event", lambda self, kind, **kw: events.append(kw)):
            p.finish_versus(won, opponent=opponent, connection=connection)
        return p, events

    def test_a_connection_win_counts_everywhere(self):
        p, events = self.fight(True, connection=True)
        self.assertEqual((p.battles, p.win, p.totalBattles, p.totalWin), (3, 2, 11, 7))
        self.assertEqual((p.pvp_battles, p.pvp_wins), (1, 1))
        self.assertTrue(events[0]["other_device"], "a connection is another device")

    def test_a_connection_loss(self):
        p, _events = self.fight(False, connection=True)
        self.assertEqual((p.battles, p.win, p.totalBattles, p.totalWin, p.pvp_wins), (3, 1, 11, 6, 0))

    def test_a_versus_counts_the_record_but_not_pvp_wins(self):
        p, events = self.fight(True, connection=False)
        self.assertEqual((p.battles, p.win, p.totalBattles, p.totalWin), (3, 2, 11, 7))
        self.assertEqual((p.pvp_battles, p.pvp_wins), (1, 0))
        self.assertFalse(events[0]["other_device"], "two of the player's pets of one module")


class EveryPath(unittest.TestCase):
    """The online PvP and DCom result loops end in finish_versus(connection)."""

    def calls(self, relpath):
        tree = ast.parse(open(os.path.join(ROOT, relpath), encoding="utf-8").read())
        return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "finish_versus"]

    def test_both_connection_paths(self):
        for relpath in ("src/battle/battle_encounter.py", "src/battle/battle_encounter_dcom.py"):
            with self.subTest(path=relpath):
                calls = self.calls(relpath)
                self.assertEqual(len(calls), 1)
                self.assertTrue(any(k.arg == "connection" and getattr(k.value, "value", None) is True
                                    for k in calls[0].keywords))

    def test_no_path_counts_pvp_by_hand(self):
        for relpath in ("src/battle/battle_encounter.py", "src/battle/battle_encounter_dcom.py"):
            with self.subTest(path=relpath):
                src = open(os.path.join(ROOT, relpath), encoding="utf-8").read()
                self.assertNotIn("pvp_battles += 1", src)


if __name__ == "__main__":
    unittest.main()
