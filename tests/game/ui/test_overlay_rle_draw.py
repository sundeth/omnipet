"""Rebuilding the RLE-encoded UI overlay does not crash the game (UI-05, PERF-01).

The UI manager RLE-encodes its overlay (2026-10-14, for the Pi Zero 2W). Once
SDL has encoded it (at its first blit), pygame.draw into it is an access
violation in pygame 2.6.1; fill() and blits are not. The frame border drawn on
every screen larger than the UI then crashed the game at an overlay rebuild:
the 2026-10-17 scene sweep lost the Status scene at all six non-square sizes.
The crash kills the process, so each case runs in a child of its own.
"""
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SUPPORT = os.path.join(REPO_ROOT, "tests", "support")
MODULES = os.path.join(REPO_ROOT, "modules")

CHILD = """
import sys
sys.path.insert(0, {support!r})
from harness import Env, quiet
env = Env({res!r})
with quiet():
    game = env.game({scene!r})
    env.frames(game, 3)
    ui = game.scene.ui_manager
    for _ in range(3):
        ui.master_ui_dirty = True
        env.frames(game, 2)
print("survived")
"""


def run_child(res, scene):
    code = CHILD.format(support=SUPPORT, res=res, scene=scene)
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=REPO_ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300)


@unittest.skipUnless(os.path.isdir(MODULES), "modules folder not present")
class OverlayRebuild(unittest.TestCase):
    def test_rebuilding_the_overlay_on_a_framed_screen(self):
        # 320x240 frames the 240x240 UI (border drawn); 240x240 does not
        for res in ("320x240", "240x320", "240x240"):
            for scene in ("status", "settings"):
                with self.subTest(res=res, scene=scene):
                    proc = run_child(res, scene)
                    self.assertEqual(proc.returncode, 0, f"exit {proc.returncode}: {proc.stderr[-800:]}")
                    self.assertIn("survived", proc.stdout)

    def test_drawing_after_turning_rle_off_works(self):
        """The fix's mechanism: set_alpha(255) decodes an encoded surface, and
        pygame.draw into it is then safe."""
        code = (
            "import os; os.environ['SDL_VIDEODRIVER'] = 'dummy'\n"
            "import pygame; pygame.init(); screen = pygame.display.set_mode((320, 240))\n"
            "s = pygame.Surface((240, 240), pygame.SRCALPHA); s.set_alpha(255, pygame.RLEACCEL)\n"
            "screen.blit(s, (0, 0)); s.set_alpha(255)\n"
            "pygame.draw.rect(s, (255, 0, 255), s.get_rect(), width=2); print('ok')\n")
        proc = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, "drawing after set_alpha(255) (RLE off) crashed")


if __name__ == "__main__":
    unittest.main()
