"""
WiFiCom support for Omnipet.

A WiFiCom is a Pi Pico W sitting between a real Digimon V-Pet and
wificom.dev: it takes a DigiROM off an MQTT topic, plays it to the toy over
the prong/IR line, and publishes what came back. That is how a physical toy
reaches the site's real-time battles and API.

Omnipet already speaks the other half of this -- `src/battle/dcom/` drives a
DCom adapter over USB serial, which is the same job over a cable. But Omnipet
carries the pets itself, so it has no reason to own a WiFiCom: it should *be*
one. The pet on the wire is a simulated pet, and the prong line is replaced
by Omnipet's own battle simulator.

This package is upstream wificom-lib, vendored. Layout:

    import_secrets.py   vendored verbatim   credentials
    mqtt.py             vendored verbatim   topics, callbacks, RTB state
    punchbag.py         vendored verbatim   the DigiROM tree
    realtime.py         vendored, 2 lines   real-time battle state machines
    settings.py         vendored verbatim   stored settings
    digiroms.txt        vendored verbatim   canned DigiROMs
    version.py          ported              version info sent to the server
    transport.py        Omnipet             paho-mqtt in place of wifi_picow
    dmcomm_shim.py      Omnipet             stands in for dmcomm-python

Upstream's own imports (`from wificom import mqtt`) resolve unchanged,
because `main.py` puts `src/` on `sys.path` and this package sits there under
its upstream name.

UPSTREAM.md records the revision, what each upstream file became and why, and
how to re-sync. The verbatim upstream tree is kept at
`utilities/wificom/upstream/` to diff against.
"""

#: The wificom-lib release this package was vendored from.
UPSTREAM_VERSION = "2.1.0"
#: The upstream commit, for an exact diff.
UPSTREAM_COMMIT = "3894cf88c1c58c3c29b50d9fad4b2ac800ea7433"
#: Where it came from.
UPSTREAM_REPO = "https://github.com/mechawrench/wificom-lib"


def is_available():
    """Whether the WiFiCom feature can run at all.

    False when paho-mqtt is missing, which is the only hard dependency this
    package adds. Credentials and a DigiROM parser are checked separately --
    those are configuration and work-in-progress, not a missing install.
    """
    from wificom.transport import PAHO_AVAILABLE
    return PAHO_AVAILABLE
