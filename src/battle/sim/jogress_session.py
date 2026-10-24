"""A jogress with a real device: one packet each way, then we evolve.

A battle exchanges four packets and settles who won. A jogress exchanges one
each way, and each side's packet describes **its own pet** -- so the whole
conversation is:

    send the ROM our pet fits   ->   read the pet the device presents
                                ->   match it against our evolve routes
                                ->   evolve

This module owns that exchange and nothing about the game: it takes a pet,
finds the ROM, drives the adapter a line at a time (the view polls it, the
same way `DComView` polls a battle, because a player pressing a button on a
toy can take a minute and the game must not freeze), and hands back the
route the reply resolved to. The view does the evolving.

**Which pets can do this is decided by the ROM database, not by us.** We
send a real device's own code; if no code presents a pet like ours, the
jogress is refused rather than built from our own data. See
`jogress_roms` -- that refusal is the enforcement, not a limitation to work
around.

**Single and Dual are not consulted.** They decide how many pets come out of
a jogress between two of ours. A real device keeps its own pet and evolves
it whatever happens, so over serial each side simply evolves its own: ours
takes the route, and the device's is its own business.

**Two wires answer in packets we can read**: the Colour one, which settles a
jogress in a single 16-byte packet, and the DMX one PENZ rides, which needs
two of its three -- the version and the pet are in different packets.
`jogress_roms.parse_reply` knows which; nothing here does.

PENX, Accel, Pendulum Cycle and Pendulum Progress have codes on record and no
established layout, so `jogress_roms.supports()` refuses them and
`can_jogress_over_serial` says which case a pet fell into.
"""
import re
import time

from core import runtime_globals
from battle.dcom.dcom_protocol import describe_status
from battle.sim import jogress_roms, protocol_constants


#: How long to wait for the player to start the jogress on the real toy.
#: The same window a DCom battle gets, and for the same reason: the player is
#: standing at the device, not at the keyboard.
EXCHANGE_TIMEOUT_SECONDS = 60.0


def pet_module(pet):
    """The loaded module *pet* belongs to, or None.

    Looked up rather than indexed: a save outlives the modules folder, so a
    pet can name a module the player has since removed -- and that should
    leave the jogress unavailable, not raise.
    """
    from core import runtime_globals as globals_

    return (getattr(globals_, "game_modules", None) or {}).get(
        getattr(pet, "module", None))


def pet_protocol(pet):
    """The battle format *pet*'s module speaks, canonically named."""
    module = pet_module(pet)
    return protocol_constants.canonical_format(
        getattr(module, "battle_protocol", None) or "")


def pet_roster(pet):
    """Every record in *pet*'s module, for turning a reply into a Digimon.

    A named jogress route asks *who* answered, and the reply carries a
    version and index -- which only mean something against the roster they
    were numbered on.
    """
    module = pet_module(pet)
    return module.get_all_monsters() if module else []


def can_jogress_over_serial(pet):
    """(possible, reason) for offering *pet* a serial jogress.

    Three things have to hold, and each failure reads differently to the
    player: the module has to name a device line, that line has to answer in
    packets we can read, and a real device has to present a pet like this
    one.
    """
    protocol = pet_protocol(pet)
    if not protocol:
        return False, "This module has no device line."
    if not jogress_roms.supports(protocol):
        if jogress_roms.available(protocol) or jogress_roms.roms(protocol):
            return False, f"{protocol} replies cannot be read yet."
        return False, f"No {protocol} jogress codes on record."
    if not jogress_roms.rom_for_pet(pet, protocol):
        return False, f"No device presents a pet like {pet.name}."
    return True, ""


class SerialJogressSession:
    """One jogress attempt against a real device.

    Driven a frame at a time: `start` sends, `consume_line` is fed every line
    the adapter prints, and `partner` / `route` are filled in once the device
    has answered with something our pet can act on.
    """

    def __init__(self, pet, dcom_controller):
        self.pet = pet
        self.dcom_controller = dcom_controller
        self.protocol = pet_protocol(pet)
        self.rom = jogress_roms.rom_for_pet(pet, self.protocol)

        #: What the device presented, once it has, and what we do about it.
        self.partner = None
        self.route = None
        self.failure = None

        self.started_at = None
        self.status_counts = {}
        self._last_status_log = 0.0
        self._device_answered = False

        wire = protocol_constants.get_wire(self.protocol) if self.protocol else None
        digits = getattr(wire, "PACKET_BYTES", 2) * 2
        self._pattern = re.compile(r"r:([0-9A-Fa-f]{%d})" % digits)

    # ------------------------------------------------------------------
    # The exchange
    # ------------------------------------------------------------------

    def start(self):
        """Send our ROM. True if it went out."""
        if not self.rom:
            self.failure = "No device presents a pet like this one."
            return False
        if not self.dcom_controller:
            self.failure = "No adapter connected."
            return False

        self.started_at = time.time()
        self.status_counts = {}
        self._last_status_log = time.time()
        runtime_globals.game_console.log(
            f"[Jogress] ===== {self.protocol} SERIAL JOGRESS =====")
        runtime_globals.game_console.log(
            f"[Jogress] {self.pet.name} presents as: {self.rom}")
        try:
            # The ROM is a real device's own code, prefix and all -- it says
            # which transport and turn it wants, so it goes out untouched.
            self.dcom_controller._send_raw(self.rom + "\r")
        except Exception as error:
            runtime_globals.game_console.log(f"[Jogress] Send failed: {error}")
            self.failure = "Could not reach the adapter."
            return False
        return True

    @property
    def timed_out(self):
        return (self.started_at is not None
                and time.time() - self.started_at > EXCHANGE_TIMEOUT_SECONDS)

    @property
    def seconds_left(self):
        if self.started_at is None:
            return EXCHANGE_TIMEOUT_SECONDS
        return max(0.0, EXCHANGE_TIMEOUT_SECONDS - (time.time() - self.started_at))

    def consume_line(self, line):
        """Handle one line from the adapter; True once the device answered.

        **One line is one exchange attempt**, the same rule a DCom battle
        follows, and the packets are handed on *in the order they arrived*:
        the DMX layout reads its version out of the first and its pet out of
        the second, so dropping one would shift the rest and read packet 3 as
        a Digimon. An attempt carrying a refusal is discarded whole instead.
        """
        status = describe_status(line)
        if status:
            # These arrive several times a second for as long as nothing is
            # held to the adapter, so they are tallied rather than logged.
            code, explanation = status
            count, _ = self.status_counts.get(code, (0, explanation))
            self.status_counts[code] = (count + 1, explanation)
            if time.time() - self._last_status_log > 2.0:
                runtime_globals.game_console.log(
                    f"[Jogress] DCom status: {line} -> {explanation} "
                    f"({count + 1} so far)")
                self._last_status_log = time.time()
            return False

        runtime_globals.game_console.log(f"[Jogress] RX: {line}")
        self.status_counts.clear()

        packets = self._pattern.findall(line)
        if not packets:
            return False
        if any(packet.upper() == "FF00" for packet in packets):
            # Not a terminator: the device sends this to abort, having
            # objected to something we sent it. The attempt is void.
            runtime_globals.game_console.log(
                "[Jogress] Device sent FF00 - it rejected the code")
            return False

        self._device_answered = True
        partner = jogress_roms.parse_reply(packets, self.protocol)
        if not partner:
            runtime_globals.game_console.log(
                "[Jogress] %s is not a jogress reply; ignoring"
                % " ".join(packets))
            return False

        self.partner = partner
        runtime_globals.game_console.log(
            "[Jogress] Device presents: v%s index %s %s stage %s"
            % (partner["version"], partner["index"],
               partner["attribute"], partner["stage"]))
        return True

    def diagnosis(self):
        """Why nothing usable arrived, in the adapter's own words."""
        if self.failure:
            return self.failure
        if self.partner:
            return ""
        if self._device_answered:
            return "The device answered, but not with a jogress."
        if not self.status_counts:
            return "No response from the adapter."
        _, explanation = max(self.status_counts.values(), key=lambda e: e[0])
        return explanation

    # ------------------------------------------------------------------
    # What the answer means
    # ------------------------------------------------------------------

    def resolve(self):
        """The route our pet takes for the partner it was shown, or None.

        Works for any module: the reply carries the partner's stage and
        attribute, which is what an attribute route asks for, and its version
        and index, which the module's own roster turns back into a Digimon
        for a named route.
        """
        if not self.partner:
            return None
        self.route = jogress_roms.matching_route(
            self.pet, self.partner, pet_roster(self.pet))
        if self.route:
            runtime_globals.game_console.log(
                f"[Jogress] {self.pet.name} -> {self.route.get('to')}")
        else:
            runtime_globals.game_console.log(
                f"[Jogress] {self.pet.name} has no route for that partner")
        return self.route

    def partner_name(self):
        """What the device presented, named if the roster knows it."""
        if not self.partner:
            return ""
        record = jogress_roms.presented_pet(
            self.partner, pet_roster(self.pet), self.protocol)
        if record:
            return record.get("name", "")
        stages = {2: "Baby II", 3: "Child", 4: "Adult", 5: "Perfect",
                  6: "Ultimate", 7: "Super Ultimate"}
        return "%s %s" % (self.partner["attribute"],
                          stages.get(self.partner["stage"], self.partner["stage"]))
