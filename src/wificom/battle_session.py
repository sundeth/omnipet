"""A battle over the WiFiCom pipe, from either end.

A WiFiCom is a middleman: the same battle two toys would have over a cable,
carried as DigiROMs through wificom.dev. So it is starter-agnostic -- Omnipet
has to be able to open one and to answer one, and which it is doing is the
only thing the two ends disagree about.

The exchange is driven **a packet at a time**, which is not a stylistic
choice: the DMX's last packet has to be the inverse of the opponent's and the
DMOG's verdict the opposite of theirs, so neither side can state its whole
hand up front. `battle.sim.exchange.PacketExchange` owns that, and owns it
for the cable and the versus battle too -- this module only carries it.

**A message is a DigiROM.** Nothing here invents a format: what goes in the
`digirom` field is the same command string a DCom cable would carry, and a
reply is read with the same parser. Each message carries every packet its
sender has sent so far, so it is self-describing -- the wire is readable from
the signal letter and packet width, the step from how many there are -- and a
peer that answers everything at once (a real WiFiCom with a toy behind it)
works without a special case.
"""

from core import runtime_globals
from wificom import digirom as digirom_module


class WiFiComBattle:
    """One battle, either as the side that opened it or the side that answered."""

    def __init__(self, pet, battle_format, opens):
        from battle.sim.dcom_battle_simulator import pet_to_digimon
        from battle.sim.exchange import PacketExchange

        self.pet = pet
        self.battle_format = battle_format
        self.opens = bool(opens)
        self.digimon = pet_to_digimon(pet, battle_format)
        self.exchange = PacketExchange(battle_format, self.digimon,
                                       opens=self.opens, peer=True)
        self.failed = None

    # ------------------------------------------------------------------

    @property
    def complete(self):
        return self.exchange.complete

    @property
    def packet_count(self):
        return self.exchange.packet_count

    def progress(self):
        """(sent, received, total), for the waiting screen."""
        return (len(self.exchange.sent), len(self.exchange.received),
                self.packet_count)

    # ------------------------------------------------------------------

    def open(self):
        """Our opening message, or None if we are not the one opening."""
        if not self.opens:
            return None
        return self._say(1)

    def consume(self, command):
        """Take their message and return ours, or None if there is nothing to say.

        Accepts however many packets arrived: one at a time from another
        Omnipet, or all of them at once from a WiFiCom with a toy behind it.
        """
        try:
            rom = digirom_module.parse_command(command)
        except Exception as error:  # pylint: disable=broad-except
            self.failed = str(error)
            return None
        if rom.signal_type is None:
            return None

        before = len(self.exchange.received)
        for packet in rom.packets[before:]:
            self.exchange.receive(packet)
        gained = len(self.exchange.received) - before
        if not gained:
            return None
        if self.exchange.aborted:
            self.failed = "The other side refused the battle"
            return None

        # Answer with as many as they are now owed. Whoever opened is one
        # ahead throughout, so this settles to one packet each way.
        owed = len(self.exchange.received) + (1 if self.opens else 0)
        return self._say(min(owed, self.packet_count))

    def _say(self, upto):
        """Send packets until we have sent *upto* of them.

        None when that adds nothing: with both sides answering every message,
        a step that produces no new packet would otherwise bounce a duplicate
        back and forth for ever.
        """
        before = len(self.exchange.sent)
        while len(self.exchange.sent) < upto:
            if self.exchange.next_packet() is None:
                break
        if len(self.exchange.sent) == before:
            return None
        return self.exchange.command()

    # ------------------------------------------------------------------

    def exchange_string(self):
        """The exchange as the adapter prints it: `s:` theirs, `r:` ours.

        What an app with a real WiFiCom expects back, and what upstream
        publishes -- `str(rom.result)`, two entries per packet. A peer taking
        turns gets the DigiROM command instead, because it is going to answer
        rather than read a finished exchange.
        """
        from wificom.executor import format_result

        entries = []
        theirs = self.exchange.received
        ours = self.exchange.sent
        for index in range(max(len(theirs), len(ours))):
            pair = []
            if index < len(theirs):
                pair.append(("s", theirs[index].hex().upper()))
            if index < len(ours):
                pair.append(("r", ours[index].hex().upper()))
            entries.extend(pair if not self.opens else list(reversed(pair)))
        return format_result(entries, timed_out=not self.complete)

    def validate(self):
        return self.exchange.validate()

    def result(self):
        """The finished battle, or None."""
        if not self.complete:
            return None
        if not self.validate():
            self.failed = "The exchange did not check out"
            runtime_globals.game_console.log(
                "[WiFiCom] Their packets failed the %s validator" % self.battle_format)
            return None
        return self.exchange.result()

    def opponent(self):
        return self.exchange.opponent()


def format_for(command, pet):
    """The battle format an incoming message is on, or None."""
    from wificom import executor

    try:
        rom = digirom_module.parse_command(command)
    except Exception:  # pylint: disable=broad-except
        return None
    if rom.signal_type is None:
        return None
    return executor.battle_format_for(rom, pet)
