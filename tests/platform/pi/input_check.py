#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Which game action each GPIO button produces (checklist UI-01, GPIO).

Run through input_check.sh on the Pi with the game stopped (it holds the
pins). Builds the game's own InputManager the way the game does at start-up:
created when core.runtime_globals is imported (gpiozero Buttons registered
then, with the mapping known at that moment), then the saved configuration
applied and input_manager.reload_input_mappings() called, as
VirtualPetGame.__init__ does. Every button press is then passed through
InputManager.process_event, so the action printed is the one the scenes get.

The mapping is GameConfiguration's (src/models/game_configuration.py): the
defaults, overridden by the gpio_map stored in the player's newest save.
config/input_config_raspberry.json is no longer read by the game (the config
folder was removed in 1.0); the save is only READ, from a copy.

    python3 input_check.py [--game DIR] [--seconds 60] [--defaults]
                           [--remap 21=B,20=A] [--scan-pins 4,17] [--simulate]

  --defaults   ignore the save: the default GamePi mapping
  --remap      apply a custom pin=ACTION mapping on top (as the setup screen
               saves one), to see whether the game honours it
  --scan-pins  also listen on these unmapped BCM pins (to find a button
               wired to a pin the mapping does not use); avoid the display's
               SPI/DC/RST/backlight pins and I2C (2, 3)
  --simulate   no hardware: a stand-in gpiozero presses every mapped pin once
               (checking the script, or the mapping logic, off the Pi)

Press each button once (any order); it stops when every mapped button has
been pressed and released, or after --seconds. Exit 1 when a mapped button
was never pressed or produced another action than its mapping.
"""
import argparse
import contextlib
import io
import os
import pickle
import platform
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pi_common  # noqa: E402


# ---------------------------------------------------------------- saved mapping
class _Stub:
    """Stand-in for any game class while reading a save (no game code runs)."""

    def __init__(self, *args, **kwargs):
        pass

    def __setstate__(self, state):
        if isinstance(state, tuple) and len(state) == 2:
            state = state[0] or state[1]
        if isinstance(state, dict):
            self.__dict__.update(state)


class _SaveReader(pickle.Unpickler):
    SAFE = {"builtins", "copyreg", "collections", "datetime", "_codecs", "__builtin__", "decimal"}

    def find_class(self, module, name):
        if module in self.SAFE:
            return super().find_class(module, name)
        return type(name, (_Stub,), {"__module__": module})


def saved_configuration(save_dir):
    """(configuration dict or None, description) from the newest save the
    game would load (save/Default in Free Mode, the player folder otherwise)."""
    mode = pi_common.read(os.path.join(save_dir, "game_mode.cfg"))
    folders = []
    if os.path.isdir(save_dir):
        for name in sorted(os.listdir(save_dir)):
            p = os.path.join(save_dir, name)
            if os.path.isdir(p) and (name == "Default") == (mode != "1"):
                folders.append(p)
    files = [os.path.join(f, n) for f in folders for n in os.listdir(f)
             if n.startswith("save_data_") and n.endswith(".dat")]
    if not files:
        return None, f"no save found (game_mode.cfg={mode!r}); defaults"
    files.sort(key=os.path.getmtime, reverse=True)
    for path in files:
        try:
            with open(path, "rb") as fh:
                data = _SaveReader(fh).load()
        except Exception:
            continue
        cfg = data.get("configuration") if isinstance(data, dict) else None
        if isinstance(cfg, _Stub):
            cfg = {k: v for k, v in vars(cfg).items() if not k.startswith("_")}
        rel = os.path.relpath(path, os.path.dirname(save_dir))
        if isinstance(cfg, dict):
            return cfg, f"{rel} (newest save, read from a copy)"
        return None, f"{rel} has no configuration; defaults"
    return None, "no readable save; defaults"


# ---------------------------------------------------------------- simulation
def fake_gpiozero():
    """A stand-in gpiozero: Button objects that can be pressed from code."""
    mod = types.ModuleType("gpiozero")
    registry = {}

    class Button:
        def __init__(self, pin, pull_up=True, bounce_time=None, **kw):
            if pin in registry:
                raise RuntimeError(f"GPIO{pin} is already in use")
            self.pin, self.when_pressed, self.when_released = pin, None, None
            registry[pin] = self

        def press(self):
            if self.when_pressed:
                self.when_pressed()

        def release(self):
            if self.when_released:
                self.when_released()

        def close(self):
            registry.pop(self.pin, None)
    mod.Button = Button
    mod.registry = registry
    mod.__version__ = "simulated"
    return mod


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--defaults", action="store_true")
    ap.add_argument("--remap", help="pin=ACTION,... applied on top of the mapping")
    ap.add_argument("--scan-pins", help="extra BCM pins to listen on, comma-separated")
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--display", action="store_true", help="open the real display (default: headless SDL)")
    ap.add_argument("--in-place", action="store_true",
                    help="run in the game folder (save redirected, writes blocked) instead of a symlink sandbox")
    ap.add_argument("--tmp")
    args = ap.parse_args()
    game_dir = pi_common.find_game(args.game)

    print("== Omnipet input_check (UI-01, GPIO) ==")
    for line in pi_common.system_lines(game_dir):
        print(line)
    old = [p for p in ("config/input_config.json", "config/input_config_raspberry.json")
           if os.path.isfile(os.path.join(game_dir, p))]
    if old:
        print(f"note     {', '.join(old)} found: the game no longer reads it (mapping = defaults + save)")
    box = pi_common.Sandbox(game_dir, args.tmp, copy_save=not args.defaults, links=not args.in_place)
    pi_common.choose_display(dummy=not args.display)
    pi_common.NetworkGuard().install()
    pi_common.WriteGuard(game_dir, [box.dir]).install()
    if args.simulate:
        sys.modules["gpiozero"] = fake_gpiozero()
    os.chdir(box.root)
    for p in (os.path.join(box.root, "src"), box.root):
        if p not in sys.path:
            sys.path.insert(0, p)

    # 1. as the game starts: InputManager built while runtime_globals is imported
    boot_out = io.StringIO()
    real_system = platform.system
    with contextlib.redirect_stdout(boot_out):
        import pygame
        game_globals = pi_common.patch_save_dir(box.save, free_mode=False)
        if args.simulate and real_system() != "Linux":
            platform.system = lambda: "Linux"      # InputManager only registers GPIO on Linux
        try:
            from core import runtime_globals
        finally:
            platform.system = real_system
        from input.input_manager import GPIO_PRESS_EVENT, GPIO_RELEASE_EVENT, HAS_GPIO, reload_input_mappings
        pygame.display.init()
        pygame.display.set_mode((240, 240) if args.display else (1, 1))
        runtime_globals.game_input._ensure_mouse_detection()     # its one-time print, here
    im = runtime_globals.game_input
    try:
        import gpiozero
        gz = f"gpiozero {getattr(gpiozero, '__version__', '?')}"
        try:
            factory = gpiozero.Device.pin_factory or "(chosen at first use)"
            gz += f", pin factory {type(factory).__name__ if not isinstance(factory, str) else factory}"
        except Exception:
            pass
    except Exception as exc:
        gz = f"gpiozero not importable: {exc}"
    print(f"gpio     {gz}; input device '{im.device}'; HAS_GPIO={HAS_GPIO}")
    for line in boot_out.getvalue().splitlines():
        if line.startswith("[Input]"):
            print(f"boot     {line}")
    registered = dict(im.pin_map)                      # what the Buttons were created with

    # 2. the saved configuration, then reload_input_mappings (VirtualPetGame.__init__)
    cfg = game_globals.configuration
    if args.defaults:
        source = "--defaults: GameConfiguration.DEFAULT_GPIO_MAP"
    else:
        saved, source = saved_configuration(box.save)
        if saved:
            with contextlib.redirect_stdout(io.StringIO()):
                cfg.from_dict(saved)
    if args.remap:
        for part in args.remap.split(","):
            pin, _, action = part.partition("=")
            cfg.gpio_map[int(pin)] = action.strip().upper()
        source += f"; --remap {args.remap}"
    with contextlib.redirect_stdout(io.StringIO()):
        reload_input_mappings(im)
    print(f"mapping  {source}; configured_input_type={cfg.configured_input_type!r}")
    print()
    print(f"{'pin':>4}  {'configured':10}  {'button made':12}")
    for pin in sorted(set(im.pin_map) | set(registered)):
        made = "yes" if pin in im.buttons else ("NO (setup failed)" if im.device == "Pi" else "no (not Linux)")
        print(f"{pin:>4}  {im.pin_map.get(pin, '-'):10}  {made}")
    extra = {}
    if args.scan_pins:
        Button = sys.modules["gpiozero"].Button if args.simulate else gpiozero.Button
        for pin in (int(p) for p in args.scan_pins.split(",") if p.strip()):
            if pin in im.pin_map:
                continue
            try:
                btn = Button(pin, pull_up=True, bounce_time=0.04)
                btn.when_pressed = im.make_gpio_handler(f"(unmapped pin {pin})", pin, True)
                btn.when_released = im.make_gpio_handler(f"(unmapped pin {pin})", pin, False)
                extra[pin] = btn
            except Exception as exc:
                print(f"scan     pin {pin}: {exc}")
        if extra:
            print(f"scan     also listening on unmapped pins {sorted(extra)}")
    print()

    # 3. presses
    seen = {}            # pin -> {"actions": [...], "presses": n, "released": bool}
    start = time.perf_counter()

    def handle(ev):
        t = time.perf_counter() - start
        quiet = contextlib.redirect_stdout(io.StringIO())     # a debug-mode save logs every press
        if ev.type == GPIO_PRESS_EVENT:
            with quiet:
                got = im.process_event(ev)
            action = got[0] if got else None
            pin = getattr(ev, "gpio_pin", None)
            want = im.pin_map.get(pin)
            row = seen.setdefault(pin, {"actions": [], "presses": 0, "released": False, "down": t})
            row["presses"] += 1
            row["down"] = t
            row["actions"].append(action)
            note = ""
            if want and action != want:
                note = f"   <-- configured {want}: the game acts on {action}"
            print(f"+{t:6.2f}s  pin {pin:>2} pressed  -> {action}{note}", flush=True)
        elif ev.type == GPIO_RELEASE_EVENT:
            with quiet:
                im.process_event(ev)
            pin = getattr(ev, "gpio_pin", None)
            row = seen.get(pin)
            if row is not None:
                row["released"] = True
                print(f"+{t:6.2f}s  pin {pin:>2} released (held {t - row['down']:.2f} s)", flush=True)
        elif ev.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN, pygame.JOYHATMOTION):
            with quiet:
                got = im.process_event(ev)
            if got:
                print(f"+{t:6.2f}s  {pygame.event.event_name(ev.type)} -> {got[0]}", flush=True)

    mapped = sorted(p for p in im.pin_map if p in im.buttons)
    if args.simulate:
        fake = sys.modules["gpiozero"].registry
        print("simulate pressing every registered pin once")
        for pin in sorted(fake):
            fake[pin].press()
            for ev in pygame.event.get():
                handle(ev)
            fake[pin].release()
            for ev in pygame.event.get():
                handle(ev)
    elif not mapped:
        print("no GPIO button could be registered: nothing to press (see the gpio/boot lines above)")
    else:
        print(f"press every button once ({len(mapped)} mapped); stops when all are done or after {args.seconds:g} s")
        try:
            while time.perf_counter() - start < args.seconds:
                for ev in pygame.event.get():
                    handle(ev)
                if all(p in seen and seen[p]["released"] for p in mapped):
                    break
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("stopped (Ctrl+C)")

    # 4. summary
    print()
    print(f"{'pin':>4}  {'configured':10}  {'game action':12}  {'presses':>7}  result")
    bad = 0
    for pin in sorted(set(im.pin_map) | set(seen)):
        want = im.pin_map.get(pin, "-")
        row = seen.get(pin)
        acts = sorted({a for a in (row or {}).get("actions", []) if a})
        if row is None:
            result = "NOT PRESSED" if pin in im.buttons else "no button (registration failed)"
            bad += 1
        elif want != "-" and acts != [want]:
            result = f"WRONG: configured {want}, game got {'/'.join(acts) or 'nothing'}"
            bad += 1
        elif want == "-":
            result = "unmapped pin (scan)"
        else:
            result = "ok"
        print(f"{pin:>4}  {want:10}  {'/'.join(acts) or '-':12}  {(row or {}).get('presses', 0):>7}  {result}")
    stale = {p: a for p, a in registered.items() if im.pin_map.get(p) != a}
    if stale:
        print(f"note     buttons were registered with the start-up mapping {stale}; "
              "the configured actions differ for these pins")
    print(f"RESULT   UI-01 GPIO {'PASS' if not bad else 'FAIL'}: {len(mapped)} mapped buttons, "
          f"{sum(1 for p in mapped if p in seen)} pressed, {bad} problems")
    pygame.quit()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
