"""The iC minigames' art in assets/ (owner, 2026-10-06): every file there at
its size, its black original kept in utilities/IC/originals/<game>/
(utilities/IC/make_*_sprites.py), and the coloured ones coloured."""

import os
import unittest

from PIL import Image

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
ASSETS = os.path.join(REPO_ROOT, "assets")
ORIGINALS = os.path.join(REPO_ROOT, "utilities", "IC", "originals")

SIZES = {
    "poop_dodge_sukamon.png": (96, 96),
    "poop_dodge_sukamon_throw.png": (96, 96),
    "poop_dodge_player.png": (21, 24),
    "shuffle_chuumon.png": (48, 48),
    "shuffle_bucket.png": (45, 48),
    "shuffle_cursor.png": (21, 21),
    "ic_get.png": (96, 96),
    "ic_digits.png": (129, 15),
}


class ArtTests(unittest.TestCase):
    def test_every_file_is_there_at_its_size(self):
        for name, size in SIZES.items():
            with self.subTest(name=name):
                self.assertEqual(Image.open(os.path.join(ASSETS, name)).size, size)

    def test_the_new_games_keep_their_originals(self):
        for name in SIZES:
            game = ("poop_dodge" if name.startswith("poop_dodge") else
                    "shuffle" if name.startswith("shuffle") else None)
            if game:
                with self.subTest(name=name):
                    self.assertTrue(os.path.exists(os.path.join(ORIGINALS, game, name)))

    def test_the_shuffle_art_is_coloured(self):
        screens = [os.path.join("ui", f"Combat_{n}_1.png")
                   for n in ("ShuffleTitle1", "ShuffleTitle2", "ShuffleSelect1", "ShuffleSelect2")]
        for name in ["shuffle_chuumon.png", "shuffle_bucket.png"] + screens:
            with self.subTest(name=name):
                image = Image.open(os.path.join(ASSETS, name)).convert("RGBA")
                used = {c for _, c in image.getcolors(100000) if c[3]}
                self.assertGreater(len(used), 2)
                self.assertNotEqual(used, {(0, 0, 0, 255)})

    def test_the_screens_live_in_ui_only(self):
        """The full-screen screens are the animated sprite's (assets/ui),
        not loose art in assets/."""
        for name in ("shuffle_title_1", "shuffle_title_2", "shuffle_select_1", "shuffle_select_2",
                     "ic20_ready", "ic20_start", "ic20_clear"):
            self.assertFalse(os.path.exists(os.path.join(ASSETS, f"{name}.png")), name)
        for name in ("ShuffleTitle1", "ShuffleTitle2", "ShuffleSelect1", "ShuffleSelect2",
                     "IC20Ready", "IC20Start", "IC20Clear"):
            image = Image.open(os.path.join(ASSETS, "ui", f"Combat_{name}_1.png"))
            self.assertEqual(image.size, (240, 240), name)

    def test_my_colours_are_the_games(self):
        """utilities/IC/game_palette.py: the colours of the combat screens."""
        import sys
        sys.path.insert(0, os.path.join(REPO_ROOT, "utilities", "IC"))
        import game_palette
        names = ["shuffle_bucket.png", "poop_dodge_sukamon.png", "poop_dodge_sukamon_throw.png",
                 "building_1.png", "building_2.png", "building_3.png", "building_explosion_1.png",
                 "building_explosion_2.png", "digi_whack_hole.png", "digi_whack_peek.png",
                 "digi_whack_out.png", "digi_whack_hit.png", "digi_whack_cursor.png",
                 "digi_mash_digits.png", "digi_mash_puwamon.png", "digi_mash_falcomon.png",
                 "digi_mash_peckmon.png", "digi_mash_loaderleomon.png"]
        names += [os.path.join("ui", f"Combat_{n}_1.png") for n in
                  ("ShuffleTitle1", "ShuffleTitle2", "ShuffleSelect1", "ShuffleSelect2",
                   "IC20Ready", "IC20Start", "IC20Clear")]
        for name in names:
            with self.subTest(name=name):
                image = Image.open(os.path.join(ASSETS, name)).convert("RGBA")
                colours = {"#%02x%02x%02x" % c[:3] for _, c in image.getcolors(100000) if c[3]}
                game_palette.check(colours, name)

    def test_the_peeking_chuumon_is_an_original_only(self):
        self.assertFalse(os.path.exists(os.path.join(ASSETS, "shuffle_bucket_chuumon.png")))
        self.assertTrue(os.path.exists(os.path.join(ORIGINALS, "shuffle", "shuffle_bucket_chuumon.png")))

    def test_the_ic_sounds_are_registered_and_the_menu_chirp_is_not(self):
        """utilities/IC/make_ic_sounds.py: its sounds for the game, the
        iC's menu chirp only for the Digimon Database."""
        import ast
        source = open(os.path.join(REPO_ROOT, "src", "models", "game_sound.py"), encoding="utf-8").read()
        labels = {}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Dict) and node.keys and all(isinstance(k, ast.Constant) for k in node.keys):
                labels.update({k.value: v.value for k, v in zip(node.keys, node.values)
                               if isinstance(v, ast.Constant)})
        expected = {24: "ic_shuffle", 25: "ic_fail", 26: "ic_success",
                    27: "ic_building_break", 28: "ic_poop_start", 29: "ic_poop_stage",
                    30: "ic20_ready", 31: "ic20_start", 32: "ic_press"}
        for number, label in expected.items():
            self.assertEqual(labels.get(number), label)
            self.assertTrue(os.path.exists(os.path.join(ASSETS, "dmc_sounds", f"{number}.wav")))
        self.assertNotIn("ic_menu", labels.values())
        self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, "utilities", "IC", "sounds", "ic_menu.wav")))

    def test_the_purse_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ASSETS, "ic_purse.png")))


if __name__ == "__main__":
    unittest.main()
