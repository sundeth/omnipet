"""A pet selection never outlives the party it was made in (UI-10).

Found by the menu crawl (boot fixture, 2026-10-13): Settings > Change Mode
reloads the save, every pet becomes a new object, and the selection still
named the old ones; using an item in Feeding then crashed looking one up in
the party (scene_inventory._setup_eating_animation). `game_globals.load()`
now clears the selection and `pet_utils.get_selected_pets()` drops pets that
left the party (frozen, released, reloaded).
"""
import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "support"))
MODULES = os.path.join(REPO_ROOT, "modules")


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class SelectionAfterReload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness import Env
        cls.env = Env("240x240")

    def setUp(self):
        self.env.reset()

    def test_a_reload_clears_the_selection(self):
        env = self.env
        env.rg.selected_pets = [env.gg.pet_list[0]]
        from harness import quiet
        with quiet():
            env.gg.load()
        self.assertEqual(env.rg.selected_pets, [])

    def test_stale_pets_are_dropped_and_the_party_is_used(self):
        from utils.pet_utils import get_selected_pets
        env = self.env
        old = env.gg.pet_list[0]
        env.gg.pet_list = env.gg.pet_list[1:]          # that pet left the party
        env.rg.selected_pets = [old]
        targets = get_selected_pets()
        self.assertNotIn(old, targets)
        self.assertTrue(all(any(p is q for q in env.gg.pet_list) for p in targets))
        self.assertEqual(env.rg.selected_pets, [])

    def test_feeding_with_a_stale_selection_does_not_crash(self):
        env = self.env
        stale = env.gg.pet_list[0]
        from harness import quiet
        with quiet():
            env.gg.load()                               # new pet objects
        env.rg.selected_pets = [stale]                  # as a selection kept across the reload
        stale.hunger = stale.strength = 0               # hungry, so it eats (the crashing path)
        game = env.game("feeding")
        env.frames(game, 30)                            # the scene ignores presses while it opens
        env.press(game, "A")                            # use the focused item (Food)
        env.frames(game, 30)


if __name__ == "__main__":
    unittest.main()
