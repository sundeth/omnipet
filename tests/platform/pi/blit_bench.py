#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How fast the Pi can draw the menus' UI overlay, per blit method (PERF-01).

Run through blit_bench.sh on the Pi. perf_scenes --profile showed every menu
spending about 17 ms a frame in one blit: the UI manager's cached overlay
(a 240x240 surface with per-pixel alpha) onto the frame. This boots the game
as perf_scenes does, builds the real overlay of a few menus, and times each
way of drawing it onto the real display surface, checking every method's
picture against the plain blit's (one level of rounding allowed):

    plain        the overlay as the game makes it (pygame.Surface(SRCALPHA))
    convert      convert_alpha(): the display's own alpha pixel format
    rle          RLE acceleration (transparent runs skipped, opaque runs copied)
    convert+rle  both
    premul       premultiplied alpha, BLEND_PREMULTIPLIED
    bbox         the plain blit of the overlay's bounding rectangle only

    python3 blit_bench.py [--game DIR] [--scene settings training ...] [--count 200]
"""
import argparse
import contextlib
import importlib
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pi_common  # noqa: E402


def fmt(surface):
    f = surface.get_masks()
    return (f"{surface.get_bitsize()}-bit masks " + "/".join(f"{m:08x}" for m in f)
            + f" flags {surface.get_flags():#x}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game")
    ap.add_argument("--scene", nargs="*", default=["settings", "training", "status"])
    ap.add_argument("--count", type=int, default=200, help="blits per method")
    ap.add_argument("--driver")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--dummy", action="store_true")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--tmp")
    args = ap.parse_args()

    game_dir = pi_common.find_game(args.game)
    video = pi_common.choose_display(args.driver, args.dummy, audio=False)
    net = pi_common.NetworkGuard().install()
    box = pi_common.Sandbox(game_dir, args.tmp, links=not args.in_place)
    pi_common.WriteGuard(game_dir, [box.dir]).install()
    print("== Omnipet blit_bench (PERF-01) ==")
    for line in pi_common.system_lines(game_dir):
        print(line)
    log = io.StringIO()
    game = pi_common.Game(box, (240, 240), fullscreen=not args.windowed, log=log)
    import pygame
    rg = game.rg
    display = pygame.display.get_surface()
    render = rg.render_surface
    print(f"video    {game.driver()} via {video}; pygame {pygame.version.ver}, SDL "
          f"{'.'.join(map(str, pygame.get_sdl_version()))}")
    print(f"display  {display.get_size()} {fmt(display)}")
    print(f"canvas   {'the display itself' if render is display else f'{render.get_size()} ' + fmt(render)}")
    scenes, _source = pi_common.scene_list()
    rg.INPUT_MODE = rg.KEYBOARD_MODE
    rg.selected_pets = list(game.gg.pet_list)

    for name in args.scene:
        module_name, class_name = scenes[name]
        with contextlib.redirect_stdout(log):
            scene = getattr(importlib.import_module(module_name), class_name)()
            scene.update()
            scene.draw(render)
        ui = getattr(scene, "ui_manager", None)
        game_overlay = getattr(ui, "master_ui_surface", None)
        if game_overlay is None:
            print(f"\n{name}: no UI overlay")
            continue
        rle_in_game = bool(game_overlay.get_flags() & (pygame.RLEACCEL | pygame.RLEACCELOK))
        # The same pixels in a plain SRCALPHA surface, as the game made it
        # before RLE (a max-blend onto a transparent surface copies them exactly)
        overlay = pygame.Surface(game_overlay.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 0))
        overlay.blit(game_overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MAX)
        backdrop = render.copy()
        backdrop.fill((40, 90, 160))
        bbox = overlay.get_bounding_rect()
        opaque = sum(1 for x in range(0, overlay.get_width(), 4) for y in range(0, overlay.get_height(), 4)
                     if overlay.get_at((x, y)).a == 255)
        partial = sum(1 for x in range(0, overlay.get_width(), 4) for y in range(0, overlay.get_height(), 4)
                      if 0 < overlay.get_at((x, y)).a < 255)
        samples = (overlay.get_width() // 4 + 1) * (overlay.get_height() // 4 + 1)
        print(f"\n{name}: overlay {overlay.get_size()} {fmt(overlay)}; bounding rect {tuple(bbox)}; "
              f"opaque {100 * opaque // samples}%, partly transparent {100 * partial // samples}% of sampled pixels; "
              f"the game now draws it {'RLE' if rle_in_game else 'plain'}")

        def picture(src, special=0, area=None):
            out = render.copy()
            out.blit(backdrop, (0, 0))
            if area is None:
                out.blit(src, (0, 0), special_flags=special)
            else:
                out.blit(src, area.topleft, area, special_flags=special)
            return pygame.image.tostring(out, "RGB")

        reference = picture(overlay)
        variants = []
        variants.append(("plain", overlay, 0, None))
        conv = overlay.convert_alpha()
        variants.append(("convert", conv, 0, None))
        rle = overlay.copy()
        rle.set_alpha(255, pygame.RLEACCEL)
        variants.append(("rle", rle, 0, None))
        conv_rle = overlay.convert_alpha()
        conv_rle.set_alpha(255, pygame.RLEACCEL)
        variants.append(("convert+rle", conv_rle, 0, None))
        try:
            pre = overlay.premul_alpha()
            variants.append(("premul", pre, pygame.BLEND_PREMULTIPLIED, None))
        except Exception as exc:
            print(f"  premul   unavailable: {exc}")
        variants.append(("bbox", overlay, 0, bbox))

        print(f"  {'method':12} {'ms/blit':>8} {'x plain':>8}  same picture")
        base = None
        for label, src, special, area in variants:
            for _ in range(5):                         # warm up (RLE encodes on the first blit)
                if area is None:
                    render.blit(src, (0, 0), special_flags=special)
                else:
                    render.blit(src, area.topleft, area, special_flags=special)
            t = time.perf_counter()
            for _ in range(args.count):
                if area is None:
                    render.blit(src, (0, 0), special_flags=special)
                else:
                    render.blit(src, area.topleft, area, special_flags=special)
            ms = 1000 * (time.perf_counter() - t) / args.count
            base = base or ms
            got = picture(src, special, area)
            if got == reference:
                same_txt = "yes"
            else:
                worst = max(abs(x - y) for x, y in zip(got, reference))
                diff = sum(1 for i in range(0, len(got), 3) if got[i:i + 3] != reference[i:i + 3])
                same_txt = (f"{'yes' if worst <= 1 else 'NO'}: {diff} pixels differ, by up to {worst} "
                            "(1 = rounding of half-transparent pixels)")
            print(f"  {label:12} {ms:8.2f} {base / ms if ms else 0:7.1f}x  {same_txt}", flush=True)
    if net.refused:
        print(f"\nNETWORK  refused (expected): {net.summary()}")
    pygame.quit()


if __name__ == "__main__":
    main()
