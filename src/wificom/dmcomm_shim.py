"""
Stand-in for the parts of dmcomm-python that the vendored WiFiCom code uses.

Upstream wificom-lib runs on CircuitPython next to dmcomm-python, which owns
both the DigiROM string parser and the controller that executes a parsed ROM
against a real toy over the prong/IR line. Omnipet has neither, and does not
need the second one: Omnipet *is* the toy, so a DigiROM is executed against a
simulated pet rather than over a wire.

What the vendored code actually reaches for is small:

    dmcomm.protocol.parse_command(str) -> DigiROM
    dmcomm.CommandError
    dmcomm.ReceiveError

so this module carries those names. Omnipet installs the parser with
`set_parser()` once it has one. Until then `parse_command` raises
`CommandError` rather than returning something that only looks parsed -- a
WiFiCom that cannot read the DigiROM the server sent has to say so, and the
callers in `realtime.py` already treat `CommandError` as the normal way a bad
ROM is reported.

`src/battle/dcom/dcom_protocol.py` formats DigiROM command strings but does
not parse them back, so the parser is still to be written (or dmcomm-python
vendored alongside this package). See UPSTREAM.md.
"""

from typing import Any, Callable, Optional


class CommandError(Exception):
    """A DigiROM command string could not be understood.

    Same role as `dmcomm.CommandError`: raised by the parser, and caught by
    the real-time battle loops to reject a message from the other player.
    """


class ReceiveError(Exception):
    """A DigiROM executed but the reply was unusable.

    Same role as `dmcomm.ReceiveError`. Nothing in the vendored code raises
    it; it is here because upstream's execute path catches it, so an Omnipet
    executor should raise it for the same reason.
    """


#: Installed by `set_parser`. `None` means no parser is available yet.
_parser: Optional[Callable[[str], Any]] = None


def set_parser(func: Optional[Callable[[str], Any]]) -> None:
    """Install the DigiROM parser, or clear it by passing ``None``.

    `func` takes a command string ("V1-FC03-FD02", "X2-...", "C1-...") and
    returns a DigiROM object. It should raise `CommandError` on bad input.
    """
    global _parser  # pylint: disable=global-statement
    _parser = func


def has_parser() -> bool:
    """Whether a DigiROM parser has been installed."""
    return _parser is not None


def parse_command(command: str) -> Any:
    """Parse a DigiROM command string. Mirrors `dmcomm.protocol.parse_command`."""
    if _parser is None:
        raise CommandError(
            "No DigiROM parser installed: call wificom.dmcomm_shim.set_parser()"
        )
    return _parser(command)


class _ProtocolNamespace:
    """Mirrors `dmcomm.protocol`, which the vendored code reaches by attribute."""

    parse_command = staticmethod(parse_command)


#: `dmcomm.protocol` as the vendored code expects to find it.
protocol = _ProtocolNamespace()
