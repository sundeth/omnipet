"""RPM: the Digivice iC's charge, its bars, its targets and its attack table.

The iC does not play the Digimon Mini's game. The Mini counts presses and
rewards more of them; the iC measures a RATE against the Digimon's own
target and rewards hitting it. The two shared a screen and a table in
Omnipet until 2026-09-21, and most of what is checked here is the seam
between them.

Sources, and which parts are read rather than assumed, are in
`src/data/attack_patterns/IC.json` and `utilities/IC/protocol.txt`.
"""

import io
import json
import os
import random
import sys
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SRC = os.path.join(REPO_ROOT, "src")
for path in (SRC, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

import pygame  # noqa: E402

from core import runtime_globals  # noqa: E402
from battle.sim import battle_utils, protocol_constants  # noqa: E402
from battle.sim.dcom_battle_simulator import DComBattleSimulator  # noqa: E402
from ui.minigames import rpm as rpm_game  # noqa: E402
from ui.minigames.rpm import RPM, BAR_COUNT, bar_color, bar_rect  # noqa: E402


def setUpModule():
    pygame.init()
    pygame.display.set_mode((240, 240))
    # **Fonts cached before someone else's `pygame.quit()` are dangling.**
    # `asset_utils` keeps one Font per (path, size) because constructing one
    # opens the TTF, and another test module tears pygame down in its own
    # teardown -- so re-initialising here is not enough, and rendering
    # through a stale handle is an access violation rather than an error.
    from utils import asset_utils
    asset_utils._font_cache.clear()


def tearDownModule():
    from utils import asset_utils
    asset_utils._font_cache.clear()
    pygame.quit()


def DMMDevice_unpack(word):
    """The five shot values a 16-bit word's bits 13..4 would decode to.

    Used only to show what packet 3 WOULD have claimed under the superseded
    reading, so the correction is visible rather than merely asserted.
    """
    from battle.sim.battle_simulator import DMMDevice
    return DMMDevice.unpack_rounds((word >> 4) & 0x3FF)


def ic_table():
    path = os.path.join(SRC, "data", "attack_patterns", "IC.json")
    return json.load(open(path, encoding="utf-8"))


class TableTests(unittest.TestCase):
    """The owner's reading, and what it turned out to be."""

    #: Exactly as read off the device on 2026-09-21. Thirty-one rows.
    MEASURED = [
        (0, "5000"),
        (1, "4100"), (1, "3200"),
        (2, "2210"), (2, "1220"),
        (3, "0320"), (3, "0410"),
        (4, "0500"), (4, "1130"), (4, "0230"), (4, "0140"),
        (5, "2111"), (5, "1211"), (5, "1121"), (5, "1112"),
        (6, "0050"), (6, "4010"), (6, "4001"), (6, "1400"),
        (7, "0401"), (7, "1040"), (7, "0041"), (7, "0104"),
        (8, "2300"), (8, "0302"), (8, "1130"), (8, "0221"),
        (9, "0122"), (9, "0023"), (9, "0014"),
        (10, "0005"),
    ]

    def test_the_table_is_what_was_read(self):
        table = ic_table()
        got = [(entry["bar"], "".join(map(str, entry["shots"])))
               for entry in table["patterns"]]
        self.assertEqual(got, self.MEASURED)
        self.assertEqual(table["max_bar"], 10)

    def test_every_row_is_five_shots(self):
        for entry in ic_table()["patterns"]:
            self.assertEqual(sum(entry["shots"]), 5, entry)
            self.assertEqual(len(entry["pattern"]), 5, entry)

    def test_the_pool_is_the_mini_s(self):
        """**The two devices share the rows.** Every iC row is a Mini row and
        every Mini row appears here; what differs is the key. The one Mini
        entry missing is its second `0050` -- it carries that row twice,
        adjacent -- and IC.json records that as an assumption rather than
        inventing it."""
        mini = json.load(open(os.path.join(
            SRC, "data", "attack_patterns", "DMM.json"), encoding="utf-8"))
        mine = {tuple(e["shots"]) for e in ic_table()["patterns"]}
        theirs = {tuple(e["shots"]) for e in mini["patterns"]}
        self.assertEqual(mine, theirs)

        numbers = [e["dmm_no"] for e in ic_table()["patterns"]]
        absent = sorted(set(e["no"] for e in mini["patterns"]) - set(numbers))
        self.assertEqual(absent, [16])
        self.assertEqual(mini["patterns"][16]["shots"], [0, 0, 5, 0])

    def test_a_bar_is_a_contiguous_block_of_that_pool(self):
        """Which is the whole reason to believe the reading: the bars are not
        a re-ordering of the Mini's rows, they are runs of it."""
        table = ic_table()
        seen = []
        for bar in range(table["max_bar"] + 1):
            rows = table["bar_rows"][str(bar)]
            numbers = [table["patterns"][r]["dmm_no"] for r in rows]
            self.assertEqual(numbers, sorted(numbers), bar)
            seen.extend(numbers)
        self.assertEqual(seen, sorted(seen), "the bars do not run in pool order")

    def test_bar_ten_is_the_hyper_five(self):
        """The playbook's threshold is the rate at which a column first
        reaches the Hyper x5, so the top bar has to BE it."""
        table = ic_table()
        rows = table["bar_rows"]["10"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(table["patterns"][rows[0]]["pattern"], [4, 4, 4, 4, 4])
        self.assertTrue(battle_utils.is_dmm_megahit(
            battle_utils.get_ic_pattern(10)))

    def test_bar_zero_is_five_weak(self):
        self.assertEqual(battle_utils.get_ic_pattern(0), [1, 1, 1, 1, 1])

    def test_a_bar_only_ever_throws_its_own_rows(self):
        rng = random.Random(3)
        table = ic_table()
        for bar in range(table["max_bar"] + 1):
            allowed = {tuple(sorted(table["patterns"][r]["pattern"]))
                       for r in table["bar_rows"][str(bar)]}
            for _ in range(40):
                pattern = battle_utils.get_ic_pattern(bar, rng=rng)
                self.assertIn(tuple(sorted(pattern)), allowed, bar)

    def test_a_bar_past_the_table_reads_the_last_one(self):
        self.assertEqual(battle_utils.get_ic_pattern(99), [4, 4, 4, 4, 4])
        self.assertEqual(battle_utils.get_ic_pattern(-5), [1, 1, 1, 1, 1])


class DamageTests(unittest.TestCase):
    """The iC's own numbers, not the compatibility mode's."""

    def test_a_value_is_its_damage(self):
        """"Normal Single/Double/Triple/Hyper attacks have power 1/2/3/4" --
        the 10X playbook. The Mini's 6 for a Hyper is the compatibility
        mode's override, from the same page that drops both sides to 6 HP,
        so importing it here imported the exception instead of the rule.
        The owner confirmed a value-3 shot costing 3 on 2026-09-21."""
        self.assertEqual(protocol_constants.IC.HIT_DAMAGE,
                         {1: 1, 2: 2, 3: 3, 4: 4})
        self.assertEqual(protocol_constants.DMM.HIT_DAMAGE[4], 6,
                         "the Mini's Hyper is still its own")

    def test_the_bar_and_the_damage_are_consistent(self):
        """Sixteen HP against a top row of five 4s: decisive, not a one-shot.
        Under the Mini's 6 a full charge would have been 30 against 16."""
        limits = protocol_constants.IC
        self.assertEqual(limits.FIXED_HP, 16)
        worst = sum(limits.HIT_DAMAGE[v] for v in battle_utils.get_ic_pattern(10))
        self.assertEqual(worst, 20)
        self.assertGreater(worst, limits.FIXED_HP)
        best = sum(limits.HIT_DAMAGE[v] for v in battle_utils.get_ic_pattern(0))
        self.assertEqual(best, 5)
        self.assertLess(best, limits.FIXED_HP)

    def test_the_damage_cap_is_the_playbook_s(self):
        self.assertEqual(protocol_constants.IC.DAMAGE_LIMIT, 4)
        self.assertEqual(protocol_constants.IC.JUST_ATTACK_DAMAGE,
                         {1: 2, 2: 3, 3: 4, 4: 8})


class TargetTests(unittest.TestCase):
    """Whose rate it is."""

    def test_a_digimon_reads_its_own(self):
        """**Per Digimon, not per stage.** The iC roster gives every 10X form
        a figure and the playbook prints the same numbers as a stage table;
        the roster is the finer of the two, so it wins."""
        self.assertEqual(battle_utils.ic_rpm_target(stage=3, attribute="Vi",
                                                    rpm=70), 70)

        class Pet:
            rpm = 85
            stage = 3
            attribute = "Vi"
        self.assertEqual(battle_utils.ic_rpm_target(Pet()), 85)

    def test_without_one_it_reads_the_playbook(self):
        """p.57: 55 for Baby I-Child, then 50/65/60/55 for the Adults,
        60/75/70/65 for the Perfects and 70/85/80/75 for the Ultimates."""
        cases = [
            (0, "Va", 55), (3, "Vi", 55), (3, "Free", 55),
            (4, "Va", 50), (4, "Da", 65), (4, "Vi", 60), (4, "Free", 55),
            (5, "Va", 60), (5, "Da", 75), (5, "Vi", 70), (5, "Free", 65),
            (6, "Va", 70), (6, "Da", 85), (6, "Vi", 80), (6, "Free", 75),
            (7, "Da", 85),
        ]
        for stage, attribute, expected in cases:
            self.assertEqual(
                battle_utils.ic_rpm_target(stage=stage, attribute=attribute),
                expected, (stage, attribute))

    def test_a_free_pet_and_an_unspelled_one_land_on_Fr(self):
        for attribute in ("", None, "Fr", "Free", "nonsense"):
            self.assertEqual(
                battle_utils.ic_rpm_target(stage=4, attribute=attribute), 55,
                attribute)

    def test_a_stage_off_the_ladder_takes_the_nearest(self):
        self.assertEqual(battle_utils.ic_rpm_target(stage=-3, attribute="Va"), 55)
        self.assertEqual(battle_utils.ic_rpm_target(stage=99, attribute="Va"), 70)

    def test_the_module_carries_the_roster(self):
        """The 10X roster went into `modules/IC/monster.json` -- 50 to 85, and
        GeoGreymon's own playbook page over Database.txt's copied row."""
        path = os.path.join(REPO_ROOT, "modules", "IC", "monster.json")
        if not os.path.exists(path):          # modules/ is gitignored
            self.skipTest("the IC module is not installed")
        records = json.load(open(path, encoding="utf-8"))["monster"]
        rates = {r["name"]: r["rpm"] for r in records
                 if int(r.get("version", 0) or 0) == 1 and r.get("rpm")}
        self.assertGreaterEqual(len(rates), 20)
        self.assertTrue(all(50 <= v <= 85 for v in rates.values()), rates)
        self.assertEqual(rates.get("Koromon"), 55)
        self.assertEqual(rates.get("GeoGreymon"), 50)
        self.assertEqual(rates.get("MirageGaogamon"), 85)


class MinigameTests(unittest.TestCase):
    def setUp(self):
        from ui.ui_manager import UIManager
        self.ui = UIManager("GREEN")

    def game(self, pet=None, at=0):
        with mock.patch.object(pygame.time, "get_ticks", return_value=at):
            game = RPM(self.ui, pet)
            game.start()
        return game

    def test_the_three_steps_run_to_ten_seconds(self):
        """Six counting, three blinking, one held."""
        game = self.game()
        for at, counting, blinking, over in (
                (0, True, False, False),
                (rpm_game.DURATION_MS - 1, True, False, False),
                (rpm_game.DURATION_MS, False, True, False),
                (rpm_game.DURATION_MS + rpm_game.BLINK_MS - 1, False, True, False),
                (rpm_game.DURATION_MS + rpm_game.BLINK_MS, False, False, False),
                (rpm_game.DURATION_MS + rpm_game.BLINK_MS
                 + rpm_game.HOLD_MS, False, False, True)):
            with mock.patch.object(pygame.time, "get_ticks", return_value=at):
                self.assertEqual(game.is_counting(), counting, at)
                self.assertEqual(game.is_blinking(), blinking, at)
                self.assertEqual(game.is_time_up(), over, at)

    def test_presses_stop_registering_when_the_clock_does(self):
        game = self.game()
        with mock.patch.object(pygame.time, "get_ticks", return_value=1000):
            self.assertTrue(game.handle_event(("A", None)))
            with mock.patch.object(pygame.time, "get_ticks", return_value=1400):
                self.assertTrue(game.handle_event(("LCLICK", {"pos": (1, 1)})))
            self.assertFalse(game.handle_event(("B", None)))
        self.assertEqual(game.get_presses(), 2)
        with mock.patch.object(pygame.time, "get_ticks",
                               return_value=rpm_game.DURATION_MS):
            # Claimed, so it cannot fall through to the scene, but not counted.
            self.assertTrue(game.handle_event(("A", None)))
        self.assertEqual(game.get_presses(), 2)

    def test_the_counter_holds_steady_after_it_blinks(self):
        """The last second is there so the number can be read; a player who
        looks up during a blink-off frame would otherwise see nothing."""
        game = self.game()
        with mock.patch.object(pygame.time, "get_ticks",
                               return_value=rpm_game.DURATION_MS
                               + rpm_game.BLINK_MS + 10):
            self.assertTrue(game._label_visible())
        blinks = set()
        for offset in range(0, rpm_game.BLINK_MS, 20):
            with mock.patch.object(pygame.time, "get_ticks",
                                   return_value=rpm_game.DURATION_MS + offset):
                blinks.add(game._label_visible())
        self.assertEqual(blinks, {True, False}, "the counter never flashed")

    def test_the_bars_follow_the_pet_s_own_target(self):
        """Two pets pressing identically light different numbers of bars,
        which is the difference from the Mini in one assertion."""
        class Pet:
            def __init__(self, rpm):
                self.rpm, self.stage, self.attribute = rpm, 4, "Va"
        easy, hard = self.game(Pet(50)), self.game(Pet(85))
        self.assertEqual(easy.target, 50)
        self.assertEqual(hard.target, 85)
        for game in (easy, hard):
            for at in range(100, 5800, 400):
                with mock.patch.object(pygame.time, "get_ticks", return_value=at):
                    game.handle_event(("A", None))
        self.assertEqual(easy.get_bars(), 10)
        self.assertLess(hard.get_bars(), 10)

    def test_ten_bars_all_the_same_height_on_the_device_s_grid(self):
        """The iC is 32 pixels across: a 2-pixel border, then ten 2-pixel
        bars a pixel apart. The Mini's row is eight bars of stepped heights,
        which is the other device's screen."""
        self.assertEqual(BAR_COUNT, 10)
        rects = [bar_rect(i) for i in range(BAR_COUNT)]
        self.assertEqual({r.height for r in rects}, {64})
        self.assertEqual({r.width for r in rects}, {15})
        self.assertEqual({r.bottom for r in rects}, {rpm_game.BAR_BOTTOM})
        self.assertEqual(rects[0].left, 15, "the device's 2-pixel border")
        # 240/32 is 7.5 layout pixels to the device's one, so a 1-pixel gap
        # lands on 7 or 8 by turns. Both are the same gap; what has to hold
        # is that they stay even and inside the screen.
        gaps = {rects[i + 1].left - rects[i].right for i in range(BAR_COUNT - 1)}
        self.assertTrue(gaps <= {7, 8}, gaps)
        self.assertLessEqual(rects[-1].right, 240)
        # The device's own arithmetic, before any rounding: a 2-pixel border,
        # ten 2-pixel bars and nine 1-pixel gaps fill 31 of its 32, leaving
        # the last as the right border.
        used = (rpm_game.DEVICE_BORDER + BAR_COUNT * rpm_game.DEVICE_BAR
                + (BAR_COUNT - 1) * rpm_game.DEVICE_GAP)
        self.assertEqual(used, rpm_game.DEVICE_WIDTH - 1)
        # Left to right and never overlapping.
        for i in range(BAR_COUNT - 1):
            self.assertLess(rects[i].right, rects[i + 1].left)

    def test_it_draws_its_own_screen_and_lights_what_it_should(self):
        # Pin the screen: another test module may have left the globals on a
        # different resolution, and the bars are drawn through the UI
        # manager's scale, so a 240-wide surface would be indexed past its
        # edge rather than simply drawn small.
        with mock.patch.object(runtime_globals, "SCREEN_WIDTH", 240),                 mock.patch.object(runtime_globals, "SCREEN_HEIGHT", 240),                 mock.patch.object(runtime_globals, "UI_SCALE", 1):
            from ui.ui_manager import UIManager
            ui = UIManager("GREEN")
            with mock.patch.object(pygame.time, "get_ticks", return_value=0):
                game = RPM(ui, None)
                game.start()
            for at in range(100, 2101, 400):
                with mock.patch.object(pygame.time, "get_ticks", return_value=at):
                    game.handle_event(("A", None))
            surface = pygame.Surface((240, 240))
            with mock.patch.object(pygame.time, "get_ticks", return_value=1000):
                game.draw(surface)
            self.assertEqual(game.get_bars(), 5)
            lit = tuple(surface.get_at(ui.scale_rect(bar_rect(4)).center))[:3]
            unlit = tuple(surface.get_at(ui.scale_rect(bar_rect(5)).center))[:3]
        self.assertEqual(lit, bar_color(4))
        self.assertNotEqual(unlit, bar_color(5))

    def test_the_screen_is_the_rpm_one(self):
        """`assets/RPM.png` belongs to this charge. The Mini's borrowed it,
        counter and all, which is the mixture being unpicked here."""
        from ui.minigames import count_bar
        self.assertEqual(rpm_game.BACKGROUND_PATH, "assets/RPM.png")
        self.assertEqual(count_bar.COUNTING_PATH, "assets/CountMatch1.png")
        self.assertEqual(count_bar.RESULT_PATH, "assets/CountMatch2.png")


class CaptureTests(unittest.TestCase):
    """**The first native iC battles**, 2026-09-21 (battles2.txt 34 and 35).

    An iC 10X answering Omnipet on the infrared wire, not in the Accel/Mini
    compatibility mode. Everything below packet 1 had been DMM's layout read
    across from six fan-made DigiROM codes; this is the first time a device
    has spoken it. Two exchanges three minutes apart, the same Chuumon.
    """

    #: The device's five packets, exactly as the adapter reported them.
    #: 34/35 are an iC 10X Chuumon; 36/38 an iC 20X Goblimon at 0 RPM.
    BATTLE_34 = ["C087", "4C67", "0167", "22D7", "9017"]
    BATTLE_35 = ["C087", "4C67", "0167", "0277", "21F7"]
    BATTLE_36 = ["D087", "4867", "0167", "0007", "E1F7"]
    BATTLE_38 = ["D087", "4867", "0167", "0007", "E007"]
    #: The stage-4 pair, 2026-09-22: a 20X Starmon at 50 RPM / 7 bars and a
    #: 10X Aquilamon at 25 RPM / 5 bars. These are what moved packet 3 and
    #: identified packet 4.
    BATTLE_39 = ["D0A7", "4C97", "0377", "2AB7", "B1F7"]
    BATTLE_40 = ["C0A7", "4AB7", "0377", "14E7", "01F7"]

    #: The same 20X in the Accel/Mini compatibility mode, read against a
    #: Digimon Mini -- four packets on the DMM wire, not five on this one.
    BATTLE_37_DMM = ["1089", "0169", "0879", "30C9"]

    ALL_NATIVE = ("34", "35", "36", "38", "39", "40")

    def native(self, label):
        return getattr(self, "BATTLE_" + label)

    def dcom(self):
        return DComBattleSimulator(None, battle_format="IC")

    def test_every_capture_validates(self):
        for label in self.ALL_NATIVE:
            self.assertTrue(
                self.dcom()._validate_packets(
                    [bytes.fromhex(p) for p in self.native(label)]), label)

    def test_the_nibble_names_both_devices(self):
        """The 10X sends version 0 and the 20X version 1, with the flag bits
        set on both. The device numbering came out of the module notes before
        any code was decoded; two devices have now sent it."""
        from battle.sim.battle_simulator import ICDevice
        seen = {}
        for label in self.ALL_NATIVE:
            fields = ICDevice.parse([bytes.fromhex(p) for p in self.native(label)])
            seen[label] = (fields["version"] >> 2 & 0b11, fields["version"] & 0b11)
        self.assertEqual(seen["34"], (0b11, 0), "10X")
        self.assertEqual(seen["35"], (0b11, 0), "10X")
        self.assertEqual(seen["36"], (0b11, 1), "20X")
        self.assertEqual(seen["38"], (0b11, 1), "20X")
        # Wire 1 inverts to module version 2, which is what the 20X is.
        self.assertEqual(protocol_constants.module_versions_for_wire("IC", 1), [2])

    def test_packet_three_never_moved(self):
        """**The finding that matters.** Four battles, two Digimon, two
        devices, and a charge from 0 bars to 5 -- packet 3 is `0167` every
        time, where the same devices vary it freely in compatibility mode.

        So it is not tracking the charge, and may not be the attack row at
        all. It decodes to 32211, a real row, but any ten bits decode to a
        real row. Nothing is done about it: the replay uses what was
        transmitted, and inventing a row would be worse.
        """
        words = {self.native(label)[2] for label in ("34", "35", "36", "38")}
        self.assertEqual(words, {"0167"}, "the four index-8 captures")
        self.assertEqual(protocol_constants.IC.OBSERVED_PACKET3_BY_INDEX,
                         {8: 0x0167, 10: 0x0377})
        # The compatibility mode DOES vary it -- same device, same session.
        self.assertNotEqual(self.BATTLE_37_DMM[2], "0167")

    def test_packet_three_is_the_slot_s_compatibility_power(self):
        """**Two slots, exact both times.** Packet 3's twelve-bit body equals
        the Power the same device sends for that slot on the Accel/Mini
        wire -- 22 at index 8 and 55 at index 10. So it is a number keyed on
        the slot, not the sender's five shots: it did not move between a 0
        RPM charge and a 90 RPM one, and the index-10 value decodes to a
        multiset that is not in the pool at all.
        """
        compatibility_power = {8: 22, 10: 55}
        for index, word in protocol_constants.IC.OBSERVED_PACKET3_BY_INDEX.items():
            self.assertEqual((word >> 4) & 0xFFF, compatibility_power[index],
                             "index %d" % index)
        # And the wire really did send those on the compatibility side.
        from battle.sim.battle_simulator import DMMDevice
        for code, expected in (("1089-0169-0879-30C9", 22),
                               ("10A9-0379-F579-01F9", 55)):
            side = [bytes.fromhex(p) for p in code.split("-")]
            self.assertEqual(DMMDevice.parse(side)["power"], expected)

    def test_the_attribute_moves_on_the_compatibility_wire(self):
        """It never has on this one -- six sides, all 0, including a Data and
        a Free Digimon. **The same two Digimon state their real attribute in
        compatibility mode**, which is what says the iC has attributes and
        this wire is not where they are.
        """
        from battle.sim.battle_simulator import DMMDevice
        # DMM codes Vi/Da/Va/Free as 0/1/2/3.
        for code, expected, who in (("1089-0169-0879-30C9", 0, "Goblimon, Virus"),
                                    ("10A9-0379-F579-01F9", 3, "Aquilamon, Free"),
                                    ("10A9-0379-5959-C1B9", 1, "Starmon, Data")):
            side = [bytes.fromhex(p) for p in code.split("-")]
            self.assertEqual(DMMDevice.parse(side)["attribute"], expected, who)
        # ...against every native side reading 0.
        from battle.sim.battle_simulator import ICDevice
        for label in self.ALL_NATIVE:
            fields = ICDevice.parse([bytes.fromhex(p) for p in self.native(label)])
            self.assertEqual(fields["attribute"], 0, label)

    #: What the device was showing on its own bar meter, where it was noted.
    CHARGE_BARS = {"35": 5, "36": 0, "38": 0, "39": 7, "40": 5}

    def test_packet_four_is_the_attack_pattern(self):
        """**The field that was being thrown away as "the empty packet".**

        Every device side's packet 4 decodes to a row of the owner's own bar
        table, at exactly the bar the device was displaying. Two battles at
        0 RPM / 0 bars sent `000` -- five weak shots, which is bar 0 -- and a
        7-bar charge sent `2AB`, which is `0041`, a bar 7 row.

        This is also the wire confirming the bar table itself, which had only
        ever been read off the device's screen.
        """
        from battle.sim.battle_simulator import ICDevice
        for label, bars in self.CHARGE_BARS.items():
            rounds = ICDevice.parse(
                [bytes.fromhex(p) for p in self.native(label)])["rounds"]
            self.assertIn(bars, battle_utils.ic_bars_for_pattern(rounds),
                          "battle %s showed %d bars but sent %s"
                          % (label, bars, "".join(map(str, rounds))))

    def test_a_zero_charge_sends_the_zero_bar_row(self):
        """Bar 0 is `5000`, five weak shots. Both 0 RPM captures sent exactly
        that -- which is what identified the field."""
        from battle.sim.battle_simulator import ICDevice
        for label in ("36", "38"):
            rounds = ICDevice.parse(
                [bytes.fromhex(p) for p in self.native(label)])["rounds"]
            self.assertEqual(rounds, [1, 1, 1, 1, 1], label)
        self.assertEqual(battle_utils.get_ic_pattern(0), [1, 1, 1, 1, 1])

    def test_the_pattern_tracks_the_charge_not_the_digimon(self):
        """The same Chuumon sent two different rows; two different Digimon at
        the same bar sent rows from the same bar. That is the opposite of
        packet 3, and it is how the two were told apart."""
        from battle.sim.battle_simulator import ICDevice
        rounds = {label: ICDevice.parse(
            [bytes.fromhex(p) for p in self.native(label)])["rounds"]
            for label in self.ALL_NATIVE}
        self.assertNotEqual(rounds["34"], rounds["35"], "one Chuumon, two rows")
        self.assertEqual(rounds["36"], rounds["38"], "same Digimon, same charge")

    def test_the_spare_bits_of_the_pattern_packet_are_clear(self):
        """Ten bits of shot sizes leave two over, and they have been 0 every
        time -- which is what says the field really is ten bits wide."""
        from battle.sim.battle_simulator import ICDevice
        for label in self.ALL_NATIVE:
            fields = ICDevice.parse(
                [bytes.fromhex(p) for p in self.native(label)])
            self.assertEqual(fields["pattern_spare"], 0, label)

    def test_the_two_wires_disagree_about_power(self):
        """**Per Digimon on the native wire, one number on the other.**
        Chuumon 198 and Goblimon 134 natively -- different, so the field is
        the Digimon's. Both send 22 in compatibility mode, on two different
        devices, which is either slot 8's shared base or a canned side.
        """
        from battle.sim.battle_simulator import DMMDevice, ICDevice
        native = {label: ICDevice.parse(
            [bytes.fromhex(p) for p in self.native(label)])["power"]
            for label in self.ALL_NATIVE}
        self.assertEqual([native["34"], native["35"]], [198, 198], "Chuumon")
        self.assertEqual([native["36"], native["38"]], [134, 134], "Goblimon")
        self.assertNotEqual(native["34"], native["36"],
                            "the native scale would be canned if these matched")

        compat = DMMDevice.parse([bytes.fromhex(p) for p in self.BATTLE_37_DMM])
        self.assertEqual(compat["power"], 22, "Goblimon on the DMM wire")
        self.assertEqual(compat["index"], 8)
        self.assertEqual(compat["projectile"], 0,
                         "the playbook drops the weapon for those battles")

    def test_the_readings_file_keeps_the_wires_apart(self):
        """Which is the whole point of the `wire` column: one Digimon, two
        wires, two numbers that must never be averaged into one base."""
        import csv
        path = os.path.join(REPO_ROOT, "utilities", "DMM", "power_readings.csv")
        if not os.path.exists(path):
            self.skipTest("the readings file is not installed")
        with io.open(path, encoding="utf-8") as handle:
            rows = [r for r in csv.DictReader(handle, delimiter=";")
                    if r["device"] == "IC"]
        got = {}
        for r in rows:
            got.setdefault((r["digimon"], r["wire"]), set()).add(int(r["wire_power"]))
        self.assertEqual(got.get(("Chuumon", "IC")), {198})
        self.assertEqual(got.get(("Chuumon", "DMM")), {22})
        self.assertEqual(got.get(("Goblimon", "IC")), {134})
        self.assertEqual(got.get(("Goblimon", "DMM")), {22})

    def test_the_flag_bits_were_real(self):
        """**Confirmed on hardware.** Packet 1's nibble was read as
        Flags(2) | Version(2) rather than a 4-bit version, and the checksum
        as covering the twenty digits EXCEPT those two bits. Both came from
        one dmcomm code explaining its own exception, which is thin. A real
        iC sent nibble C -- flags 11, device 0, the 10X -- and its digits sum
        to 15, reaching 3 only once the flag bits come out. Two readings that
        could have been a coincidence, confirmed by a device.
        """
        from battle.sim.battle_simulator import ICDevice
        for label in self.ALL_NATIVE:
            words = [bytes.fromhex(p) for p in self.native(label)]
            fields = ICDevice.parse(words)
            self.assertEqual((fields["version"] >> 2) & 0b11, 0b11, "flags")
            digits = sum((b >> 4) + (b & 0xF) for w in words for b in w)
            self.assertEqual(digits % 16, 15, "the plain sum")
            self.assertEqual((digits - 0b11 * 4) % 16,
                             protocol_constants.IC.CHECKSUM_REMAINDER)

    def test_the_checksum_target_moves_with_our_own_flag_bits(self):
        """**Measured by getting it wrong, 2026-09-22.** The check skips
        packet 1's two flag bits, so a side that SETS them has a digit sum
        4 per bit above the number the device checks. A probe sent flags 11
        with a plain `@3` and the iC answered two packets and stopped, three
        times running -- it read our side and refused it.

        dmcomm's own flagged code has the rule in it: `IC1-C067-...-@F007`
        sets both bits and asks for F, which is 3 + 12.
        """
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.models import Digimon

        def side(flags):
            pet = Digimon(name="p", order=0, traited=0, egg_shake=0, index=6,
                          hp=16, attribute=0, power=37, handicap=0, buff=0,
                          mini_game=0, level=1, stage=3, sick=0, shot1=4,
                          shot2=4, tag_meter=0)
            pet.version = (flags << 2) | 0
            return ICDevice(pet).generate_all_packets(
                hits=0, pattern=[2, 3, 2, 1, 1])

        target = protocol_constants.IC.CHECKSUM_REMAINDER
        for flags in (0, 1, 2, 3):
            packets = side(flags)
            digits = sum((b >> 4) + (b & 0xF) for p in packets for b in p)
            self.assertEqual((digits - flags * 4) % 16, target,
                             "flags %d" % flags)
            # ...and the adapter is asked for the matching digit.
            segment = protocol_constants.IC.dcom_final_segment(packets)
            self.assertEqual(segment,
                             "@%X^1^F%X" % ((target + flags * 4) % 16,
                                            protocol_constants.IC.EOL),
                             "flags %d" % flags)
        # Our own sides send flags 0, so nothing about the game moved.
        self.assertEqual(protocol_constants.IC.dcom_final_segment(side(0)),
                         protocol_constants.IC.DCOM_FINAL_SEGMENT)

        # dmcomm's flagged code obeys the same rule.
        code = [bytes.fromhex(x)
                for x in "C067-4257-0197-0007-5007".split("-")]
        digits = sum((b >> 4) + (b & 0xF) for p in code for b in p)
        self.assertEqual((digits - 3 * 4) % 16, target)

    def test_the_identity_reads_as_chuumon(self):
        """Index 8 on the iC 10X, Virus -- which is the module's own Chuumon,
        and settles the name battle 36 had carried with a question mark."""
        dcom = self.dcom()
        opponent = dcom.parse_opponent(self.BATTLE_34, None)
        self.assertIsNotNone(opponent)
        self.assertEqual(opponent.index, 8)
        # 198 is Family(3) | Strength(5): a Machine at strength 6.
        self.assertEqual((opponent.power, opponent.digisoul), (6, "Machine"))
        self.assertEqual(opponent.version, 0, "the nibble's low two bits")

        path = os.path.join(REPO_ROOT, "modules", "IC", "monster.json")
        if not os.path.exists(path):          # modules/ is gitignored
            return
        records = json.load(open(path, encoding="utf-8"))["monster"]
        chuumon = next(r for r in records if r.get("name") == "Chuumon")
        self.assertEqual(chuumon["index"], 8)
        self.assertEqual(chuumon["version"], 1, "wire 0 + WIRE_VERSION_OFFSET")
        self.assertEqual(chuumon["attribute"], "Vi")

    def test_the_projectile_differs_from_the_compatibility_mode(self):
        """4 here, 0 in the compatibility captures. The playbook says the
        weapon is dropped for those battles, which is what a 0 would be."""
        from battle.sim.battle_simulator import ICDevice
        fields = ICDevice.parse([bytes.fromhex(p) for p in self.BATTLE_34])
        self.assertEqual(fields["projectile"], 4)

    def test_the_device_opens_and_we_answer(self):
        """The transcripts run `r:` then `s:` for every pair, so the device
        transmitted first and our turn-2 listen was the right role. That had
        been a guess -- "unknown which side opens; listening is the safe
        default" -- and it held."""
        self.assertEqual(protocol_constants.IC.DCOM_TURN,
                         protocol_constants.DCOM_TURN_LISTEN)

    def test_both_battles_replay_to_a_knockout_on_one_bar(self):
        """Our side's hits are the inverse of theirs, which is what the
        adapter's `@3^1^F7` builds, and both sides count down from 16."""
        from battle.sim.battle_simulator import ICDevice
        ours = {"34": ["0017", "E0F7", "6BA7", "0007", "81E7"],
                "35": ["0017", "E0F7", "4007", "0007", "E007"]}
        theirs = {"34": self.BATTLE_34, "35": self.BATTLE_35}
        for label in ("34", "35"):
            mine = ICDevice.parse([bytes.fromhex(p) for p in ours[label]])
            yours = ICDevice.parse([bytes.fromhex(p) for p in theirs[label]])
            self.assertEqual(mine["hits"] ^ yours["hits"], 0x1F,
                             "hits are not complementary in battle " + label)
        # Battle 34's device threw 24313 -- packet 4, `22D` -- which is
        # `1121`, a bar 5 row. What we sent that day was an all-weak pattern
        # in packet 4, because the pattern was going into packet 3.
        self.assertEqual(
            ICDevice.parse([bytes.fromhex(p) for p in theirs["34"]])["rounds"],
            [2, 4, 3, 1, 3])
        self.assertEqual(battle_utils.ic_bars_for_pattern([2, 4, 3, 1, 3]), [5])

    def test_packet_three_is_not_a_pattern_at_all(self):
        """It decodes to a legal multiset, which is exactly why it fooled the
        reading -- any ten bits do. `0167` is `2210`, a bar 2 row, on a
        battle the device fought at 5 bars; `0377` is not in the pool at all.
        Neither is what the device threw, which is in packet 4.
        """
        from battle.sim.battle_simulator import ICDevice
        fields = ICDevice.parse([bytes.fromhex(p) for p in self.BATTLE_35])
        self.assertEqual(fields["slot_value"], 22)
        stale = DMMDevice_unpack(0x0167)
        self.assertEqual(battle_utils.ic_bars_for_pattern(stale), [2],
                         "the bar it would have claimed")
        self.assertNotEqual(stale, fields["rounds"],
                            "and it is not what was actually thrown")
        self.assertIsNone(battle_utils.ic_pattern_number(DMMDevice_unpack(0x0377)),
                          "the index-10 value is not even a row")

    def test_the_same_device_sent_the_same_row_twice(self):
        """P1, P2 and P3 are byte-identical across the two battles; only
        packet 4 and the hits moved. The compatibility captures did the same
        thing (battles 36-37), and it is the reason the Power reading above
        is worth trusting and the pattern reading is not yet."""
        self.assertEqual(self.BATTLE_34[:3], self.BATTLE_35[:3])
        self.assertNotEqual(self.BATTLE_34[3:], self.BATTLE_35[3:])


class CritSpriteTests(unittest.TestCase):
    """On the iC line a value-4 Hyper comes from the crit bank; on the Mini's
    it does not.

    This is the rule for a pet from ANOTHER line fighting on the iC's: it
    keeps its own sprites, `atk_alt_2` naming its critical as on the X line.
    The iC's own Digimon follow the iC's rule instead (`ICAttackSpriteTests`).
    """

    class Pet:
        atk_main = 7
        atk_alt = 9
        atk_alt_2 = 12
        module = "PENC"
        name = "probe"

    def encounter(self, battle_format, crit_bank=("12",)):
        """A BattleEncounter with only what the sprite choice touches."""
        from battle.battle_encounter import BattleEncounter
        encounter = BattleEncounter.__new__(BattleEncounter)
        encounter.battle_format = battle_format
        encounter.module = None
        encounter.get_crit_attack_sprite = (
            lambda entity, atk_id: ("CRIT", str(atk_id))
            if str(atk_id) in crit_bank else None)
        encounter.get_attack_sprite = lambda entity, atk_id: ("ATK", str(atk_id))
        return encounter

    def test_the_line_declares_it(self):
        self.assertEqual(protocol_constants.IC.CRIT_BANK_DAMAGE, 4)
        self.assertIsNone(
            getattr(protocol_constants.DMM, "CRIT_BANK_DAMAGE", None),
            "the Mini scales its ordinary sprite up instead")

    def test_four_draws_the_crit_bank_at_atk_alt_2(self):
        """**`atk_alt_2` names it, exactly as on the X line.** Not the
        ordinary shot id: the crit bank is its own folder with its own
        numbering, and `atk_alt_2` is the field that indexes it."""
        encounter = self.encounter("IC")
        sprite, atk_id, count, double = encounter._count_bar_sprite(self.Pet(), 4)
        self.assertEqual(sprite, ("CRIT", "12"))
        self.assertEqual((atk_id, count, double), ("12", 1, False))

    def test_one_to_three_stay_on_the_ordinary_bank(self):
        encounter = self.encounter("IC")
        for value in (1, 2, 3):
            sprite, atk_id, count, double = encounter._count_bar_sprite(
                self.Pet(), value)
            self.assertEqual(sprite, ("ATK", "7"), value)
            self.assertEqual((atk_id, count, double), ("7", value, False), value)

    def test_no_atk_alt_2_falls_back_the_way_the_x_line_does(self):
        """`atk_alt` at double size, and `atk_main` at double size with no
        alternate either -- `_ladder_shot`'s own chain."""
        class NoCrit(self.Pet):
            atk_alt_2 = 0
        encounter = self.encounter("IC")
        sprite, atk_id, count, double = encounter._count_bar_sprite(NoCrit(), 4)
        self.assertEqual(sprite, ("ATK", "9"), "atk_alt at 2x")
        self.assertEqual((atk_id, count, double), ("9", 1, True))

        class NoAlt(self.Pet):
            atk_alt_2 = 0
            atk_alt = 0
        sprite, atk_id, count, double = encounter._count_bar_sprite(NoAlt(), 4)
        self.assertEqual(sprite, ("ATK", "7"), "atk_main at 2x")
        self.assertEqual((atk_id, count, double), ("7", 1, True))

    def test_it_matches_the_x_line_rung_for_rung(self):
        """The fallback is the X line's, so the two must agree on a pet with
        no crit sprite -- that is the whole claim of "the same way DMX does"."""
        encounter = self.encounter("IC", crit_bank=())
        class NoCrit(self.Pet):
            atk_alt_2 = 0
        ladder = encounter._ladder_shot(NoCrit(), 5, critical=True)
        count_bar = encounter._count_bar_sprite(NoCrit(), 4)
        self.assertEqual(ladder[0], count_bar[1], "same id")
        self.assertEqual(ladder[1], count_bar[2], "same sprite count")
        self.assertEqual(ladder[2], count_bar[3], "same doubling")

    def test_the_mini_still_scales_its_own_sprite_up(self):
        """The Mini has no crit bank on this ladder: a 4 is `atk_alt` at
        double size, which is what makes its Hyper read as a one-shot kill."""
        encounter = self.encounter("DMM")
        sprite, atk_id, count, double = encounter._count_bar_sprite(self.Pet(), 4)
        self.assertEqual(sprite, ("ATK", "9"))
        self.assertEqual((atk_id, count, double), ("9", 1, True))

    def test_an_empty_crit_id_falls_back_rather_than_drawing_nothing(self):
        """A pet naming a crit id the folder has nothing for -- which matters
        while `assets/atk_crit/` is still being filled in."""
        encounter = self.encounter("IC", crit_bank=())
        sprite, atk_id, count, double = encounter._count_bar_sprite(self.Pet(), 4)
        self.assertEqual(sprite, ("ATK", "9"))
        self.assertEqual((atk_id, count, double), ("9", 1, True))

    def test_the_nibble_goes_out_as_the_kind_not_a_sprite(self):
        """It is not a sprite id at all (2026-09-30): a pet from another line
        sends 4, an ordinary battle, whatever its own sprites are. Our
        Floramon used to send its 38, clamped to 14."""
        self.assertEqual(protocol_constants.IC.MAX_SHOT, 0xF)
        from battle.sim.dcom_battle_simulator import pet_to_digimon

        class Pet:
            name, module = "Floramon", "PENC"
            atk_main, atk_alt, atk_alt_2 = 38, 38, 0
            index, version, stage, level = 6, 1, 3, 1
            attribute, traited, shook, sick = "Vi", False, False, 0
            hp, power, mini_game, effort = 10, 15, 0, 0
            def get_power(self): return 15
            def get_hp(self): return 10
        digimon = pet_to_digimon(Pet(), "IC")
        self.assertEqual(digimon.shot1, protocol_constants.IC.KIND_NORMAL)
        self.assertEqual(digimon.power, 6, "its stage's strength, as a device sends")


class ICAttackSpriteTests(unittest.TestCase):
    """The iC draws every Digimon from its own library (2026-09-30).

    Read with `utilities/IC/crit_sprite_probe.py` against a real iC 10X:
    packet 2's nibble is a Kind whose low bit is the Just Attack flag, and
    the receiver picks the sprites from that flag and the Power byte.
    utilities/IC/protocol.txt has the battles.
    """

    IC = protocol_constants.IC
    #: The same three Digimon below and at Reliability 31 (Database captures
    #: 548-550, answering; battles2.txt 51-52, opening).
    RAVEMON = ["1137", "4B07", "0B37", "3FF7", "D1F7"]
    RAVEMON_JUST = ["D137", "5B07", "0B37", "3E97", "31F7"]
    SHINEGREYMON_JUST = ["C147", "5107", "0B37", "0007", "71F7"]
    #: Ravemon below 31 with a Beast Claw and with a Fowl Tornado
    #: (battles2.txt 53-54).
    RAVEMON_BEAST_CLAW = ["D137", "4B07", "2B37", "0007", "4177"]
    RAVEMON_FOWL_TORNADO = ["D137", "4B07", "4C27", "3FF7", "91F7"]

    def dcom(self):
        return DComBattleSimulator(None, battle_format="IC")

    def encounter(self, crit_bank=("1", "2", "3", "4", "5")):
        from battle.battle_encounter import BattleEncounter
        encounter = BattleEncounter.__new__(BattleEncounter)
        encounter.battle_format = "IC"
        # A connection battle fought from some other module's screen.
        encounter.module = mock.Mock(battle_protocol=None)
        encounter.module.name = "PENC"
        encounter.get_crit_attack_sprite = (
            lambda entity, atk_id: ("CRIT", str(atk_id))
            if str(atk_id) in crit_bank else None)
        encounter.get_attack_sprite = lambda entity, atk_id: ("ATK", str(atk_id))
        return encounter

    class Pet:
        """One of the iC's own, below Reliability 31."""
        name, module = "ShineGreymon", "IC"
        atk_main, atk_alt, atk_alt_2 = 1, 2, 2
        index, version, device_version, stage, level = 20, 1, 1, 6, 1
        attribute, traited, shook, sick = "Va", False, False, 0
        hp, power, mini_game, effort, reliability = 16, 160, 0, 0, 30
        def get_power(self): return 160
        def get_hp(self): return 16

    def test_the_low_bit_is_the_flag(self):
        """Swept 0-14: every odd value drew the Reliability-31 set."""
        for kind in range(15):
            self.assertEqual(self.IC.is_max_reliability(kind), bool(kind % 2), kind)

    def test_the_power_bands_read(self):
        for power in (15, 16, 17):
            self.assertEqual(self.IC.crit_for_power(power), 2, power)    # claw
        for power in (49, 59, 60, 61):
            self.assertEqual(self.IC.crit_for_power(power), 3, power)    # wolf head
        for power in (175, 176, 177):
            self.assertEqual(self.IC.crit_for_power(power), 4, power)    # wing
        for power in (250, 255):
            self.assertEqual(self.IC.crit_for_power(power), 5, power)    # thorns
        for power in (100, 108):                     # Kudamon, Chirinmon
            self.assertEqual(self.IC.crit_for_power(power), 6, power)    # cross
        self.assertEqual(self.IC.crit_for_power(76), 7)      # Whamon: Water, bubbles
        self.assertEqual(self.IC.crit_for_power(134), 8)     # Goblimon: Dark, skull
        self.assertEqual(self.IC.crit_for_power(198), 9)     # Chuumon: Machine, gear
        for power in (10, 12, 15, 18, 25):
            self.assertEqual(self.IC.normal_for_power(power), 3, power)
        for power in (34, 50, 60):
            self.assertEqual(self.IC.normal_for_power(power), 1, power)

    def test_a_just_attack_side_is_read_as_one(self):
        """ShineGreymon at 31: the strong shot and the claw, as on its own
        screen. Ravemon at 31: the wing."""
        from battle.dcom.pvp_payload import opponent_attack_sprites
        dcom = self.dcom()
        shine = dcom.parse_opponent(self.SHINEGREYMON_JUST, None)
        self.assertTrue(shine.ic_max_reliability)
        self.assertEqual(opponent_attack_sprites(shine, "IC"), (3, 2, 2))
        ravemon = self.dcom().parse_opponent(self.RAVEMON_JUST, None)
        self.assertTrue(ravemon.ic_max_reliability)
        self.assertEqual(opponent_attack_sprites(ravemon, "IC")[1:], (2, 4))

    def test_an_ordinary_side_is_read_as_one(self):
        ravemon = self.dcom().parse_opponent(self.RAVEMON, None)
        self.assertFalse(ravemon.ic_max_reliability)
        self.assertEqual(ravemon.ic_sprites[0], self.IC.STANDARD_SPRITE)

    def test_packet_three_carries_the_weapon(self):
        from battle.sim.battle_simulator import ICDevice
        plain = ICDevice.parse([bytes.fromhex(p) for p in self.RAVEMON])
        claw = ICDevice.parse([bytes.fromhex(p) for p in self.RAVEMON_BEAST_CLAW])
        tornado = ICDevice.parse([bytes.fromhex(p) for p in self.RAVEMON_FOWL_TORNADO])
        self.assertEqual((plain["weapon"], plain["mini_power"]), (0, 179))
        self.assertEqual((claw["weapon"], claw["mini_power"]), (2, 179))
        self.assertEqual((tornado["weapon"], tornado["mini_power"]), (4, 194),
                         "its own family's weapon raised the Power")

    def test_the_weapon_is_a_five_bit_number(self):
        """battles2.txt 60-70: Metal Armor 10, Metal Axe 14, and the four
        from 16 up with their fifth bit in packet 2's Kind."""
        from battle.sim.battle_simulator import ICDevice
        def read(*packets):
            fields = ICDevice.parse([bytes.fromhex(p) for p in packets])
            return fields["weapon"], fields["mini_power"]
        self.assertEqual(read("D137", "5B07", "AC27", "2A87", "F1F7"), (10, 194))
        self.assertEqual(read("D137", "5B07", "EB37", "18A7", "C1F7"), (14, 179))
        self.assertEqual(read("D137", "7B07", "0B37", "0037", "7107"), (16, 179))
        self.assertEqual(read("D137", "7B07", "2BB7", "0C07", "51F7"), (18, 187))
        self.assertEqual(read("D137", "7B07", "3B37", "0037", "51F7"), (19, 179))
        self.assertTrue(self.IC.is_max_reliability(7), "Kind 7 is still a Just Attack")

    def test_a_weapon_above_fifteen_sets_the_kind_bit(self):
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        pet = self.Pet()
        pet.reliability = 31
        for weapon, kind in ((18, 7), (10, 5)):
            with mock.patch("utils.inventory_utils.active_protocol_value",
                            return_value=weapon):
                digimon = pet_to_digimon(pet, "IC")
            fields = ICDevice.parse(ICDevice(digimon).generate_all_packets(pattern=[1] * 5))
            self.assertEqual((fields["projectile"], fields["weapon"]), (kind, weapon))

    #: Every device side on record: (packet 2's byte, family, strength).
    POWER_BYTES = (
        ("Wanyamon", 35, "Beast", 3), ("Budmon", 227, "Insect", 3),
        ("Chuumon", 198, "Machine", 6), ("Aquilamon", 171, "Bird", 11),
        ("Whamon", 76, "Water", 12), ("RizeGreymon", 12, "Dragon", 12),
        ("ShineGreymon", 16, "Dragon", 16), ("MirageGaogamon", 49, "Beast", 17),
        ("Pinamon", 163, "Bird", 3), ("Goblimon", 134, "Dark", 6),
        ("Starmon", 201, "Machine", 9), ("Blossomon", 237, "Insect", 13),
        ("Ravemon", 176, "Bird", 16),
    )

    def test_the_power_byte_is_family_and_strength(self):
        """Eleven families' worth of readings, and no stage out of order."""
        IC = self.IC
        for name, byte, family, strength in self.POWER_BYTES:
            self.assertEqual((IC.FAMILY_NAMES[IC.family_of(byte)], IC.strength_of(byte)),
                             (family, strength), name)
            self.assertEqual(IC.power_byte(family, strength), byte, name)
        self.assertEqual(IC.FAMILY_CODES["Holy"], 3, "by elimination")

    def test_the_module_agrees_with_every_family_read(self):
        path = os.path.join(REPO_ROOT, "modules", "IC", "monster.json")
        if not os.path.exists(path):          # modules/ is gitignored
            return
        records = json.load(open(path, encoding="utf-8"))["monster"]
        families = {}
        for record in records:
            families.setdefault(record["name"], set()).add(record.get("digisoul"))
        for name, _byte, family, _strength in self.POWER_BYTES:
            self.assertEqual(families[name], {family}, name)

    def test_the_modules_power_is_the_strength_times_ten(self):
        path = os.path.join(REPO_ROOT, "modules", "IC", "monster.json")
        if not os.path.exists(path):          # modules/ is gitignored
            return
        records = json.load(open(path, encoding="utf-8"))["monster"]
        powers = {}
        for record in records:
            powers.setdefault(record["name"], set()).add(record["power"])
        for name, _byte, _family, strength in self.POWER_BYTES:
            self.assertEqual(powers[name], {strength * 10}, name)
        for record in records:
            if (1 <= record["stage"] <= 6
                    and record.get("availability") != "Unobtainable"):
                self.assertLessEqual(record["power"], 310, record["name"])
                if record["stage"] >= 2:
                    self.assertGreater(record["power"], 0, record["name"])

    def test_our_pet_sends_its_family_and_its_stages_strength(self):
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        pet = self.Pet()
        pet.digisoul = "Dragon"
        with mock.patch("utils.inventory_utils.active_protocol_value", return_value=0):
            digimon = pet_to_digimon(pet, "IC")
        self.assertEqual(digimon.power, 16, "the module's 160, over ten")
        fields = ICDevice.parse(ICDevice(digimon).generate_all_packets(pattern=[1] * 5))
        self.assertEqual((fields["power"], fields["family"], fields["strength"],
                          fields["mini_power"]), (16, 0, 16, 179),
                         "what ShineGreymon sends")
        pet.digisoul, pet.stage, pet.power = "Bird", 2, 30
        with mock.patch("utils.inventory_utils.active_protocol_value", return_value=0):
            digimon = pet_to_digimon(pet, "IC")
        fields = ICDevice.parse(ICDevice(digimon).generate_all_packets(pattern=[1] * 5))
        self.assertEqual((fields["power"], fields["mini_power"]), (163, 5),
                         "what Pinamon sends")

    def test_a_usable_weapon_picks_the_ordinary_sprite(self):
        """The any-family three draw sprite 4 and a family's two weapons its
        own sprite on that family (all eight read by 2026-10-04); another
        family's weapon changes nothing. The critical never moves, and
        Reliability does not gate it (battles2.txt 61-79)."""
        from battle import ic_attacks
        IC = self.IC
        for weapon in (9, 10, 11):
            self.assertEqual(IC.weapon_sprite(weapon), 4)
            self.assertEqual(IC.weapon_sprite(weapon, "Bird"), 4)
        for family, weapons, sprite in (("Dragon", (1, 16), 3),
                                        ("Insect", (6, 12), 5),
                                        ("Beast", (2, 15), 8),
                                        ("Bird", (4, 18), 10),
                                        ("Holy", (7, 19), 11),
                                        ("Dark", (8, 13), 6),
                                        ("Machine", (5, 14), 7),
                                        ("Water", (3, 17), 9)):
            for weapon in weapons:
                self.assertEqual(IC.weapon_sprite(weapon, family), sprite)
        for weapon in (1, 2, 3, 5, 6, 7, 8, 12, 13, 14, 15, 16, 17, 19):
            self.assertEqual(IC.weapon_sprite(weapon, "Bird"), 0, weapon)
        self.assertEqual(IC.weapon_sprite(18), 0, "family unknown")
        # Ravemon at 31 with a Fowl Buraiga, then named as a Bird.
        self.assertEqual(ic_attacks.sender_sprites(7, 176, 18, "Bird"),
                         (10, 10, 4, True))
        self.assertEqual(ic_attacks.sender_sprites(7, 176, 18), (1, 2, 4, True))
        side = self.dcom().parse_opponent(
            ["D137", "5B07", "9B77", "3E97", "61F7"], None)
        self.assertEqual((side.ic_weapon, tuple(side.ic_sprites[:2])), (9, (4, 4)))
        # MirageGaogamon below 31 with a Beast Blow (battle 72).
        pet = self.Pet()
        pet.digisoul, pet.ic_weapon = "Beast", 15
        self.assertEqual(ic_attacks.attack_ids(pet), (8, 1))
        pet.reliability = 31
        self.assertEqual(ic_attacks.attack_ids(pet), (8, 2))
        pet.digisoul = "Dragon"
        self.assertEqual(ic_attacks.attack_ids(pet), (2, 2), "not its family")

    def test_a_baby_at_31_is_not_flagged_but_draws_its_weapon(self):
        """Owner, 2026-10-02: a Baby II at Reliability 31 keeps the standard
        sprites and damage; a Wanyamon with a Beast Claw drew the Beast
        weapon sprite all the same."""
        from battle import ic_attacks
        pet = self.Pet()
        pet.stage, pet.reliability, pet.digisoul = 2, 31, "Beast"
        pet.ic_weapon = 0
        self.assertFalse(ic_attacks.max_reliability(pet))
        self.assertEqual(ic_attacks.attack_ids(pet), (1, 1))
        pet.ic_weapon = 2
        self.assertEqual(ic_attacks.attack_ids(pet), (8, 1))

    def test_the_flag_picks_between_the_pets_own_two_sprites(self):
        """`atk_main` below Max Reliability and `atk_alt` at it, with the
        wire's standard critical below and `atk_alt_2` at it."""
        from battle import ic_attacks
        pet = self.Pet()
        pet.ic_weapon = 0
        self.assertEqual(ic_attacks.attack_ids(pet), (1, 1))
        pet.reliability = 31
        self.assertEqual(ic_attacks.attack_ids(pet), (2, 2))
        pet.atk_alt = 99
        self.assertEqual(ic_attacks.attack_ids(pet), (2, 2), "not an iC sprite")

    def test_a_usable_weapon_raises_packet_three_power(self):
        """Own family +15 for the Attack +1 weapon and +8 for the +2; Digi
        Cannon +4, Metal Armor +15, Silver Rope +8; another family's 0."""
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        IC = self.IC
        def read(*packets):
            fields = ICDevice.parse([bytes.fromhex(p) for p in packets])
            return fields["projectile"], fields["weapon"], fields["mini_power"]
        # ShineGreymon below 31: Dragon Sword, then Dragon Break (Kind 6).
        self.assertEqual(read("C147", "4107", "1C27", "0007", "71F7"), (4, 1, 194))
        self.assertEqual(read("C147", "6107", "0BB7", "0007", "E1F7"), (6, 16, 187))
        # MirageGaogamon: Beast Claw, Silver Rope.
        self.assertEqual(read("C167", "4317", "2C27", "0007", "11F7"), (4, 2, 194))
        self.assertEqual(read("C167", "4317", "BBB7", "0007", "01F7"), (4, 11, 187))
        for weapon, family, power in ((1, "Dragon", 15), (16, "Dragon", 8),
                                      (2, "Beast", 15), (15, "Beast", 8),
                                      (4, "Bird", 15), (18, "Bird", 8),
                                      (9, "Bird", 4), (10, None, 15),
                                      (11, "Beast", 8), (12, "Bird", 0),
                                      (1, "Bird", 0), (0, "Bird", 0)):
            self.assertEqual(IC.weapon_power(weapon, family), power, weapon)
        pet = self.Pet()
        pet.digisoul = "Dragon"
        with mock.patch("utils.inventory_utils.active_protocol_value",
                        return_value=16):
            digimon = pet_to_digimon(pet, "IC")
        fields = ICDevice.parse(ICDevice(digimon).generate_all_packets(pattern=[1] * 5))
        self.assertEqual((fields["projectile"], fields["weapon"],
                          fields["mini_power"]), (6, 16, 179 + 8),
                         "stage 6's packet 3 Power, and the Dragon Break's +8")

    def replay(self, mine, theirs, family=None, opening=False):
        """Our side against a device's, as `(rounds, device HP, our HP,
        the device's damage each round)`."""
        from battle.sim.models import Digimon
        dcom = self.dcom()
        dcom.opening = opening
        def side(name):
            return Digimon(name=name, order=0, traited=0, egg_shake=0, index=1,
                           hp=16, attribute=0, power=60, handicap=0, buff=0,
                           mini_game=0, level=1, stage=3, sick=0, shot1=4,
                           shot2=4, tag_meter=0)
        device = side("device")
        device.digisoul = family
        log = dcom._simulate_dmm_turns(side("us"), device,
                                       [bytes.fromhex(p) for p in mine],
                                       [bytes.fromhex(p) for p in theirs])
        return (len(log), log[-1].device1_status[0].hp, log[-1].device2_status[0].hp,
                [a.hp_damage for turn in log for a in turn.attacks
                 if a.device == "device1"])

    def test_filmed_battle_83_is_a_knockout_at_round_four(self):
        """ShineGreymon below 31 with Metal Armor (+2): 4, 3, 3, 3 with round
        2 missed is 6 + 5 + 5 = 16, and the device won at round 4."""
        rounds, device_hp, our_hp, costs = self.replay(
            ("0017", "40F7", "00F7", "2F67", "4027"),
            ("C147", "4107", "AC27", "2AB7", "91D7"))
        self.assertEqual((rounds, our_hp), (4, 0))
        self.assertEqual(costs, [6, 5, 5, 5])
        self.assertEqual(device_hp, 14, "our one hit, a 2, in round 2")

    def test_filmed_battles_82_and_84_stop_after_five_rounds(self):
        """Nobody out, and the device ahead: Ravemon at 31 with a Fowl
        Tornado landing five 1s (2 + 1 each), then Ravemon below 31 with
        the Aura, which puts nothing on the wire."""
        rounds, device_hp, our_hp, costs = self.replay(
            ("0017", "40F7", "00F7", "0007", "D007"),
            ("D137", "5B07", "4C27", "0007", "91F7"), family="Bird")
        self.assertEqual((rounds, device_hp, our_hp), (5, 16, 1))
        self.assertEqual(costs, [3] * 5)
        rounds, device_hp, our_hp, costs = self.replay(
            ("0017", "4647", "0647", "2397", "8107"),
            ("D137", "4B07", "0B37", "2A87", "B0F7"), family="Bird")
        self.assertEqual((rounds, device_hp, our_hp), (5, 13, 6))
        self.assertEqual(costs, [1, 3, 3, 3, 3])

    def test_a_level_battle_is_settled_in_a_sixth_round(self):
        """The Master Book (scan 73): equal HP after five turns is decided
        on the sixth. We land 1 + 1 + 1, the device 1 + 2, so it stands 13
        to 13; round 6 is round 1 again, which is ours."""
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.models import Digimon
        def side(hits, pattern):
            d = Digimon(name="x", order=0, traited=0, egg_shake=0, index=1, hp=16,
                        attribute=0, power=60, handicap=0, buff=0, mini_game=0,
                        level=1, stage=3, sick=0, shot1=4, shot2=4, tag_meter=0)
            return [p.hex().upper() for p in ICDevice(d).generate_all_packets(hits=hits, pattern=pattern)]
        rounds, device_hp, our_hp, costs = self.replay(
            side(0b00111, [1, 1, 1, 1, 1]), side(0b11000, [1, 1, 1, 1, 2]))
        self.assertEqual((rounds, device_hp, our_hp), (6, 12, 13))
        self.assertEqual(self.IC.TIE_ROUNDS, 1)

    def test_a_weapon_adds_its_attack_only_where_it_can_be_used(self):
        IC = self.IC
        for weapon, family, attack in ((9, None, 1), (10, "Dragon", 2),
                                       (11, "Bird", 1), (4, "Bird", 1),
                                       (18, "Bird", 2), (18, "Beast", 0),
                                       (18, None, 0), (0, "Bird", 0)):
            self.assertEqual(IC.weapon_attack(weapon, family), attack, weapon)

    def test_an_items_attack_sprite_is_what_our_pet_throws(self):
        """The item names the sprite; the iC's family rule still decides
        whether this pet can use the weapon."""
        from types import SimpleNamespace
        from battle import ic_attacks
        from utils import inventory_utils
        blow = SimpleNamespace(id="blow", protocol_value=15, attack_sprite=8)
        pet = self.Pet()
        pet.digisoul = "Beast"
        with mock.patch.object(inventory_utils.game_globals, "battle_effects",
                               {"attack": {"module": "IC", "item_id": "blow"}}), \
                mock.patch.object(inventory_utils, "get_item_by_id",
                                  side_effect=lambda i: blow if i == "blow" else None):
            self.assertEqual(inventory_utils.active_attack_sprite(pet), 8)
            self.assertEqual(ic_attacks.attack_ids(pet), (8, 1))
            pet.digisoul = "Dragon"
            self.assertEqual(inventory_utils.active_attack_sprite(pet), 0)
            self.assertEqual(ic_attacks.attack_ids(pet), (1, 1))

    def test_a_just_attack_side_hits_for_two_three_four_and_eight(self):
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.models import Digimon
        dcom = self.dcom()
        # Ours: kind 4, Power 60, five 1s, every hit missed.
        mine = [bytes.fromhex(p) for p in ("0017", "43C7", "03C7", "0007", "3007")]
        theirs_fields = ICDevice.parse([bytes.fromhex(p) for p in self.RAVEMON_JUST])
        self.assertEqual(theirs_fields["rounds"], [2, 3, 3, 4, 4])
        def side(name):
            return Digimon(name=name, order=0, traited=0, egg_shake=0, index=1,
                           hp=16, attribute=0, power=60, handicap=0, buff=0,
                           mini_game=0, level=1, stage=3, sick=0, shot1=4,
                           shot2=4, tag_meter=0)
        log = dcom._simulate_dmm_turns(side("us"), side("Ravemon"), mine,
                                       [bytes.fromhex(p) for p in self.RAVEMON_JUST])
        costs = [a.hp_damage for turn in log for a in turn.attacks
                 if a.device == "device1"]
        self.assertEqual(costs[:4], [3, 4, 4, 8], "2/3/4/8, not 1/2/3/4")

    def test_our_own_iC_pet_sends_the_kind_and_its_band(self):
        from battle.sim.dcom_battle_simulator import is_oem_pet, pet_to_digimon
        pet = self.Pet()
        self.assertTrue(is_oem_pet(pet, "IC"), "the iC wire names its module")
        ordinary = pet_to_digimon(pet, "IC")
        self.assertEqual(ordinary.shot1, self.IC.KIND_NORMAL, "Reliability 30")
        self.assertEqual(ordinary.power, 16, "the claw's band, as ShineGreymon sends")
        self.assertEqual(ordinary.index, 20)
        pet.reliability = 31
        self.assertEqual(pet_to_digimon(pet, "IC").shot1, self.IC.KIND_MAX_RELIABILITY)
        pet.stage = 4
        self.assertEqual(pet_to_digimon(pet, "IC").shot1, self.IC.KIND_NORMAL,
                         "below Perfect there is no Just Attack")

    def test_an_equipped_weapon_goes_out_in_packet_three(self):
        """A boost item's `protocol_value` is the weapon nibble, over our Power."""
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        with mock.patch("utils.inventory_utils.active_protocol_value",
                        return_value=4) as lookup:
            digimon = pet_to_digimon(self.Pet(), "IC")
        lookup.assert_called_with("IC")
        self.assertEqual(digimon.ic_weapon, 4)
        fields = ICDevice.parse(ICDevice(digimon).generate_all_packets(pattern=[1] * 5))
        self.assertEqual((fields["weapon"], fields["mini_power"]), (4, 179),
                         "a Bird weapon on a pet with no family adds nothing")
        with mock.patch("utils.inventory_utils.active_protocol_value",
                        return_value=0):
            digimon = pet_to_digimon(self.Pet(), "IC")
        fields = ICDevice.parse(ICDevice(digimon).generate_all_packets(pattern=[1] * 5))
        self.assertEqual(fields["weapon"], 0, "no weapon, no nibble")

    def test_a_weapon_does_not_reach_another_wire(self):
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        with mock.patch("utils.inventory_utils.active_protocol_value",
                        return_value=4):
            self.assertEqual(pet_to_digimon(self.Pet(), "DMM").ic_weapon, 0)

    def test_our_own_iC_pet_draws_the_standard_pair_below_31(self):
        encounter = self.encounter()
        pet = self.Pet()
        for value in (1, 2, 3):
            self.assertEqual(encounter._count_bar_sprite(pet, value),
                             (("ATK", "1"), "1", value, False), value)
        self.assertEqual(encounter._count_bar_sprite(pet, 4),
                         (("CRIT", "1"), "1", 1, False))

    def test_and_the_strong_shot_and_its_own_critical_at_31(self):
        encounter = self.encounter()
        pet = self.Pet()
        pet.reliability = 31
        self.assertEqual(encounter._count_bar_sprite(pet, 2),
                         (("ATK", "2"), "2", 2, False))
        self.assertEqual(encounter._count_bar_sprite(pet, 4),
                         (("CRIT", "2"), "2", 1, False), "the claw")

    def test_an_unknown_critical_is_the_standard_one(self):
        encounter = self.encounter()
        pet = self.Pet()
        pet.reliability, pet.atk_alt_2 = 31, 0
        self.assertEqual(encounter._count_bar_sprite(pet, 4)[1], "1")

    def test_a_missing_critical_falls_back_to_a_doubled_shot(self):
        encounter = self.encounter(crit_bank=())
        self.assertEqual(encounter._count_bar_sprite(self.Pet(), 4),
                         (("ATK", "1"), "1", 1, True))

    def test_a_parsed_device_side_draws_what_its_packet_says(self):
        """A low-Power sender, flag clear, is drawn with the low-Power sprite."""
        class Opponent:
            name, module = "iC", "IC"
            atk_main, atk_alt, atk_alt_2 = 3, 2, 2
            ic_max_reliability = False
        encounter = self.encounter()
        self.assertEqual(encounter._count_bar_sprite(Opponent(), 3)[1:3], ("3", 3))
        Opponent.ic_max_reliability = True
        self.assertEqual(encounter._count_bar_sprite(Opponent(), 3)[1:3], ("2", 3))

    def test_a_pet_from_elsewhere_keeps_its_own_library(self):
        """No id crosses this wire, so ours resolve in our own module."""
        encounter = self.encounter()
        self.assertEqual(encounter._attack_sprite_module(CritSpriteTests.Pet()), "PENC")
        self.assertEqual(encounter._attack_sprite_module(self.Pet()), "IC")

    def test_the_module_points_at_the_ics_own_sprites(self):
        path = os.path.join(REPO_ROOT, "modules", "IC", "monster.json")
        if not os.path.exists(path):          # modules/ is gitignored
            return
        records = json.load(open(path, encoding="utf-8"))["monster"]
        by_key = {(r["version"], r["index"]): r for r in records}
        self.assertEqual(by_key[(1, 20)]["atk_alt_2"], 2, "ShineGreymon: claw")
        self.assertEqual(by_key[(1, 22)]["atk_alt_2"], 3, "MirageGaogamon: wolf head")
        self.assertEqual(by_key[(2, 19)]["atk_alt_2"], 4, "Ravemon: wing")
        for record in records:
            if record.get("stage", 0) < 1:
                continue
            # Enemies throw the standard sprites only (owner, 2026-10-01),
            # and below Perfect nothing has a strong shot (owner, 2026-10-05).
            enemy = record.get("availability") == "Unobtainable"
            alt = 1 if enemy else 2
            if record["stage"] < protocol_constants.IC.MAX_RELIABILITY_MIN_STAGE:
                alt = 0
            self.assertEqual(
                (record["atk_main"], record["atk_alt"]), (1, alt), record["name"])
            if enemy:
                self.assertEqual(record["atk_alt_2"], 1, record["name"])
            else:
                # Its family's critical from Perfect on, as a receiver draws it.
                ic = protocol_constants.IC
                code = ic.FAMILY_CODES.get(record.get("digisoul") or "")
                crit = (ic.FAMILY_CRITS.get(code, 0)
                        if record["stage"] >= ic.MAX_RELIABILITY_MIN_STAGE else 0)
                self.assertEqual(record["atk_alt_2"], crit, record["name"])
        self.assertEqual(by_key[(1, 18)]["atk_alt_2"], 5, "Lilamon: thorns")
        self.assertEqual(by_key[(2, 17)]["atk_alt_2"], 6, "Chirinmon: cross")


class HitRateTests(unittest.TestCase):
    """That a hit is rolled per round, against real power, on the right scale.

    The owner saw every battle come out all-hit or all-miss and asked whether
    the rate was being worked out at all. It is -- what those battles show is
    a power gap, not a missing roll, and the two halves below say so
    separately so a real regression cannot hide behind the explanation.
    """

    def test_each_round_is_rolled_on_its_own(self):
        """Not one roll applied to five rounds, which is what an all-or-
        nothing result looks like from the outside."""
        from battle.sim.exchange import PacketExchange
        roll = PacketExchange._roll
        shim = object.__new__(PacketExchange)
        seen = set()
        for _ in range(200):
            seen.add(roll(shim, 50, 5))
        self.assertGreater(len(seen), 8,
                           "five 50%% rounds produced only %d patterns" % len(seen))
        # And the extremes really are reachable, so a run of them is chance.
        self.assertEqual(roll(shim, 100, 5), 0b11111)
        self.assertEqual(roll(shim, 0, 5), 0)

    def test_the_rate_is_the_power_ratio(self):
        """`power * 100 / (power + opponent)`, which is what every manual on
        these lines states in the same words."""
        rate = protocol_constants.hit_rate(protocol_constants.IC, 100, 3, 100, 3)
        self.assertAlmostEqual(rate, 50.0)
        self.assertGreater(
            protocol_constants.hit_rate(protocol_constants.IC, 150, 3, 50, 3),
            protocol_constants.hit_rate(protocol_constants.IC, 50, 3, 150, 3))

    def test_the_attribute_triangle_is_in_WIRE_codes(self):
        """`ATTRIBUTE_BEATS` is keyed on what the packet carries, not on
        Omnipet's own numbering -- the parsed sides handed to `hit_rate` come
        straight off the wire. On this line Vi is 0, Da is 1 and Va is 2, so
        a table written in Omnipet's codes would invert the whole triangle.
        """
        IC = protocol_constants.IC
        internal_to_wire = IC.ATTRIBUTE_MAP
        va, da, vi = (internal_to_wire[0], internal_to_wire[1],
                      internal_to_wire[2])
        # Vaccine beats Virus, Virus beats Data, Data beats Vaccine.
        for attacker, defender in ((va, vi), (vi, da), (da, va)):
            self.assertEqual(
                protocol_constants.attribute_advantage(IC, attacker, defender),
                IC.ATTRIBUTE_ADVANTAGE, (attacker, defender))
            self.assertEqual(
                protocol_constants.attribute_advantage(IC, defender, attacker),
                -IC.ATTRIBUTE_ADVANTAGE, (defender, attacker))
        free = internal_to_wire[3]
        for other in (va, da, vi):
            self.assertEqual(
                protocol_constants.attribute_advantage(IC, free, other), 0)
            self.assertEqual(
                protocol_constants.attribute_advantage(IC, other, free), 0)

    def test_the_opener_rolls_against_what_it_heard(self):
        """When we speak first there is nothing to invert, so the final
        packet is rolled -- and it has heard their power and attribute by
        then. A generator default here beat a power-255 opponent 20 times in
        20 before this path existed."""
        from battle.sim.exchange import PacketExchange
        from battle.sim.battle_simulator import ICDevice

        strong = self.side(power=250)
        weak = self.side(power=5)
        wins = 0
        for _ in range(60):
            exchange = PacketExchange("IC", weak, opens=True)
            # **The opener speaks before it listens**, which is the whole
            # point: at its last packet it has heard one fewer than the
            # answerer has, so it cannot invert and has to roll. Driving it
            # the other way round makes it look like an answerer and it
            # inverts instead -- the hits then come out perfect regardless
            # of power, which is what `simulate_exchange`'s own ordering
            # avoids.
            for packet in ICDevice(strong).generate_all_packets(hits=0):
                exchange.next_packet()
                exchange.receive(packet)
            hits = ICDevice.parse(exchange.sent)["hits"]
            wins += bin(hits).count("1")
        self.assertLess(wins, 60 * 5 * 0.25,
                        "a power-5 opener landed %d of 300 against power 250" % wins)

    def side(self, power):
        from battle.sim.models import Digimon
        pet = Digimon(name="x", order=0, traited=0, egg_shake=0, index=8,
                      hp=16, attribute=0, power=power, handicap=0, buff=0,
                      mini_game=0, level=1, stage=3, sick=0, shot1=4,
                      shot2=4, tag_meter=0)
        pet.version = 0
        return pet

    def test_answering_does_not_roll_at_all(self):
        """**And that is the wire's rule, not a gap.** On turn 2 the two hit
        masks are each other's inverse -- one side lands each round -- so our
        pattern is the device's complement and no rate is taken. Every
        capture on record is a turn-2 listen, which is why they read as
        all-hit or all-miss: the DEVICE chose, and we got the negative.
        """
        from battle.sim.exchange import PacketExchange
        from battle.sim.battle_simulator import ICDevice

        theirs = ICDevice(self.side(power=198)).generate_all_packets(hits=0b10110)
        exchange = PacketExchange("IC", self.side(power=15), opens=False)
        for packet in theirs:
            exchange.receive(packet)
            exchange.next_packet()
        mine = ICDevice.parse(exchange.sent)["hits"]
        self.assertEqual(mine, (~0b10110) & 0x1F)


class WiringTests(unittest.TestCase):
    """That the charge reaches the battle as a bar and not as a rate."""

    def test_the_protocol_asks_for_it(self):
        self.assertEqual(protocol_constants.IC.MINIGAME, "RPM")
        self.assertEqual(protocol_constants.DMM.MINIGAME, "Count Bar")
        self.assertEqual(protocol_constants.IC.MAX_CHARGE, 10,
                         "the charge is the bar, 0-10")

    def test_the_session_knows_it(self):
        from ui.minigames.minigame_session import MINIGAMES, minigame_result
        self.assertIn("RPM", MINIGAMES)
        # The bar IS the key to the table, so a full charge grades Excellent
        # and an empty one fails. Reading it as the Mini's 0-31 count would
        # cap a full charge a third of the way up.
        self.assertEqual(minigame_result("RPM", strength=10), 3)
        self.assertEqual(minigame_result("RPM", strength=0), 0)

    def test_the_device_builds_its_packets_from_the_ic_table(self):
        """`ICDevice` inherited the Mini's lookup, which ran a 0-10 bar
        through a 0-31 count scale -- so a full iC charge asked for the
        Mini's row for count 10."""
        from battle.sim.battle_simulator import ICDevice
        from battle.sim.models import Digimon
        pet = Digimon(name="T", order=0, traited=0, egg_shake=0, index=6,
                      hp=16, attribute=0, power=37, handicap=0, buff=0,
                      mini_game=10, level=1, stage=3, sick=0, shot1=4,
                      shot2=4, tag_meter=0)
        self.assertEqual(ICDevice(pet).default_pattern(), [4, 4, 4, 4, 4])
        pet.mini_game = 0
        self.assertEqual(ICDevice(pet).default_pattern(), [1, 1, 1, 1, 1])

    def test_the_training_mode_is_registered(self):
        from scenes.scene_training import TRAINING_MODES
        self.assertIn("rpm", TRAINING_MODES)
        self.assertEqual(TRAINING_MODES["rpm"]["minigames"], ("RPM",))
        self.assertEqual(TRAINING_MODES["count_bar"]["minigames"], ("Count Bar",))

    def test_the_pet_loads_a_rate(self):
        """A real roster record, because GamePet wants a whole one -- and a
        real record is what proves the field survives the loader."""
        from models.game_pet import GamePet
        path = os.path.join(REPO_ROOT, "modules", "IC", "monster.json")
        if not os.path.exists(path):          # modules/ is gitignored
            self.skipTest("the IC module is not installed")
        records = json.load(open(path, encoding="utf-8"))["monster"]
        record = next(r for r in records if r.get("name") == "Koromon")
        record = dict(record, module="IC")

        class Module:
            """Enough of a GameModule for `set_data` to finish.

            The sprite name format has to be a string; everything else
            `set_data` reaches for is a flag or a number.
            """
            name = "IC"
            name_format = "$"
            monster_sprite_name_format = "$"

            def __getattr__(self, _name):
                return 0

        with mock.patch.dict(runtime_globals.game_modules,
                             {"IC": Module()}, clear=False):
            self.assertEqual(GamePet(record).rpm, 55)
            without = dict(record)
            without.pop("rpm")
            self.assertEqual(GamePet(without).rpm, 0,
                             "no rate means fall back to the playbook")


class AdventureTests(unittest.TestCase):
    """The IC module declares its own line, and its adventure plays the iC's
    rules: the RPM charge, the bar table, 1/2/3/4 damage on 16 HP."""

    @staticmethod
    def digimon(stage=4, attribute="Va"):
        from battle.sim.models import Digimon
        return Digimon(name="Pet", order=0, traited=0, egg_shake=0, index=0,
                       hp=16, attribute=attribute, power=100, handicap=0,
                       buff=0, mini_game=0, level=1, stage=stage, sick=0,
                       shot1=1, shot2=2, tag_meter=0)

    @staticmethod
    def simulator(charge=0):
        from battle.sim.global_battle_simulator import GlobalBattleSimulator
        return GlobalBattleSimulator(attribute_advantage=5, damage_limit=99,
                                     battle_format="IC", charge=charge)

    @staticmethod
    def manifest(module):
        path = os.path.join(REPO_ROOT, "modules", module, "module.json")
        if not os.path.exists(path):
            raise unittest.SkipTest(f"{module} module not installed")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_player_throws_a_row_of_its_own_bar(self):
        sim = self.simulator(charge=2)
        pet = self.digimon()
        for bar in (0, 4, 10):
            pet.charge = bar
            for _ in range(20):
                row = sim._pattern_for(pet)
                self.assertIn(bar, battle_utils.ic_bars_for_pattern(row), bar)
        # A pet with no bar of its own reads the shared charge.
        del pet.charge
        for _ in range(20):
            self.assertIn(2, battle_utils.ic_bars_for_pattern(sim._pattern_for(pet)))

    def test_an_enemy_plays_its_stage_s_bar(self):
        sim = self.simulator()
        for stage in range(1, 8):
            bar = max(0, min(battle_utils._ic_table()["max_bar"] - 1, stage + 1))
            for _ in range(20):
                row = sim._pattern_for(self.digimon(stage=stage), is_enemy=True)
                self.assertIn(bar, battle_utils.ic_bars_for_pattern(row), stage)

    def test_a_hyper_costs_four_not_the_mini_s_six(self):
        self.assertEqual([self.simulator()._hp_cost(v) for v in (1, 2, 3, 4)],
                         [1, 2, 3, 4])

    def test_the_modules_declare_their_own_lines(self):
        ic, twin = self.manifest("IC"), self.manifest("TWIN")
        self.assertEqual(ic["battle_protocol"], "IC")
        self.assertEqual(ic["battle_minigame"], protocol_constants.IC.MINIGAME)
        self.assertEqual(ic["battle_global_hit_points"],
                         protocol_constants.IC.FIXED_HP)
        self.assertEqual(twin["battle_protocol"], "TWIN")
        self.assertEqual(twin["battle_global_hit_points"],
                         protocol_constants.TWIN.FIXED_HP)
        self.assertEqual(protocol_constants.TWIN.FIXED_HP, 6)

    def test_the_adventure_charge_is_the_rpm_bar(self):
        from battle.battle_encounter import BattleEncounter
        from ui.ui_manager import UIManager

        class Pet:
            rpm, stage, attribute = 50, 4, "Va"
        encounter = BattleEncounter.__new__(BattleEncounter)
        encounter.reset_minigames()
        encounter.ui_manager = UIManager("GREEN")
        encounter.module = mock.Mock(battle_minigame="RPM")
        encounter._current_targets = lambda: [Pet()]
        with mock.patch.object(pygame.time, "get_ticks", return_value=0):
            encounter.setup_charge()
        self.assertIsInstance(encounter.rpm_meter, RPM)
        self.assertEqual(encounter.rpm_meter.target, 50)
        for at in range(100, 5800, 400):
            with mock.patch.object(pygame.time, "get_ticks", return_value=at):
                encounter.rpm_meter.handle_event(("A", None))
                encounter.update_charge()
        self.assertEqual(encounter.strength, 10)
        self.assertEqual(encounter.raw_charge(), 10)
        # The same presses against a harder pace light fewer bars.
        self.assertLess(encounter.rpm_meter.get_bars(85), 10)

    def test_a_real_ic_on_the_mini_s_wire_is_still_an_ic(self):
        """Declaring IC must not drop the module from the Mini's wire, where
        a real iC sends version 1 and its own index."""
        from battle.sim.dcom_battle_simulator import is_oem_pet, modules_for_format

        class Module:
            def __init__(self, name, battle_protocol):
                self.name, self.battle_protocol = name, battle_protocol
        modules = {"DMM": Module("DMM", "DMM"), "IC": Module("IC", "IC"),
                   "DMX": Module("DMX", "DMX")}
        with mock.patch.dict(runtime_globals.game_modules, modules, clear=True), \
                mock.patch("utils.module_utils.get_module", modules.get):
            names = [m.name for m in modules_for_format("DMM")]
            self.assertEqual(names, ["DMM", "IC"])
            self.assertEqual([m.name for m in modules_for_format("IC")], ["IC"])
            pet = mock.Mock(module="IC")
            self.assertTrue(is_oem_pet(pet, "DMM"))
            self.assertTrue(is_oem_pet(pet, "IC"))
            self.assertFalse(is_oem_pet(pet, "DMX"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
