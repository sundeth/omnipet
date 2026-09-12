# wificom-lib, vendored

| | |
|---|---|
| upstream | https://github.com/mechawrench/wificom-lib |
| release | v2.1.0 |
| commit | `3894cf88c1c58c3c29b50d9fad4b2ac800ea7433` (2025-12-17) |
| licence | MIT — `utilities/wificom/upstream/LICENSE.txt` |
| verbatim copy | `utilities/wificom/upstream/` |

Upstream runs on CircuitPython on a Pi Pico W, next to
[dmcomm-python](https://github.com/dmcomm/dmcomm-python). Omnipet runs
CPython 3.10 on desktop, Pi and Android. Most of what upstream does is
therefore either portable as it stands or hardware that Omnipet replaces with
something it already has.

**Vendored files keep upstream's tab indentation and formatting**, so they
diff cleanly against `utilities/wificom/upstream/`. Omnipet-authored files in
this package use Omnipet's own 4-space style.

## What each upstream file became

| upstream | here | why |
|---|---|---|
| `lib/wificom/import_secrets.py` | **ported** | Omnipet's save directory |
| `lib/wificom/mqtt.py` | **verbatim** | client-agnostic — see below |
| `lib/wificom/punchbag.py` | **verbatim** | pure-Python DigiROM tree parser |
| `lib/wificom/realtime.py` | **2 lines changed** | the `dmcomm` import |
| `lib/wificom/settings.py` | **verbatim** | plain `json` |
| `digiroms.txt` | **verbatim** | data for `punchbag.py` |
| `lib/wificom/version.py` | **ported** → `version.py` | needs `board`, `os.uname()` |
| `version_info.py` | folded into `version.py` | written by upstream's build CI |
| `lib/wificom/wifi_picow.py` | **replaced** → `transport.py` | WiFi join + minimqtt client |
| `lib/wificom/main.py` | **omitted** | see "Still to do" |
| `lib/wificom/modes.py` | **omitted** | `alarm.sleep_memory` across reboots |
| `lib/wificom/ui.py` | **omitted** | I2C display, buttons, `rainbowio` |
| `lib/wificom/sound.py` | **omitted** | `rp2pio` PIO square wave |
| `lib/wificom/status.py` | **omitted** | `analogio` battery monitor + display |
| `lib/wificom/led_hardware.py` | **omitted** | `pwmio`, `neopixel` |
| `lib/wificom/wifi_nina.py` | **omitted** | Nano RP2040 WiFi |
| `board_config.py`, `boot.py`, `code.py` | **omitted** | pin maps and CircuitPython entry |

Omnipet has its own screen, sound, input and settings, so the omitted UI
files have nothing to give it. They stay in `utilities/wificom/upstream/` as
reference for what a real WiFiCom shows the player at each point.

### `mqtt.py` is verbatim because it never imports an MQTT library

It is handed a client by `connect_to_mqtt(mqtt_client)` and only ever calls
`connect`, `subscribe`, `unsubscribe`, `add_topic_callback`, `publish`,
`loop` and `is_connected` on it, plus assigns four callbacks. `transport.py`
presents exactly that surface over paho-mqtt, so the file needed no edit.

One upstream quirk is carried over deliberately. `mqtt.py` writes
`if _data.mqtt_client.is_connected:` — but minimqtt's `is_connected` is a
*method*, so that reads a bound method object and is always true. The publish
is attempted whether or not the session is up. `transport.py` keeps
`is_connected` a method for the same reason, and a publish with no connection
fails on a return code rather than raising. Do not "fix" the call site: it
would diverge from upstream for no behavioural gain.

### `realtime.py`'s two changed lines

```diff
-import dmcomm.protocol
-from dmcomm import CommandError
+from wificom import dmcomm_shim as dmcomm
+from wificom.dmcomm_shim import CommandError
```

Everything else, including every `dmcomm.protocol.parse_command(...)` call
site, is untouched.

### Credentials

Upstream opens `secrets.json` relative to the working directory, which on a
CircuitPython device is the root of the drive the player drops the file onto.
Omnipet looks in two places instead, in order:

1. `_get_base_save_dir()/secrets.json` — the player's own data, and on
   Android `app_storage_path()/save`, the way
   `services/omninet_service.py` keeps its device key;
2. `secrets.json` beside the game, which is upstream's own location, so a
   file copied straight from the WiFiCom docs still works.

The module-level names are unchanged, because `mqtt.py` is vendored verbatim
and reads them directly. Two additions: `reload()`, so a file dropped in
while the game is running is picked up without a restart, and `find_secrets()`
/ `candidate_paths()` for the menu's availability check.

One rule was dropped. Upstream rejects the file if `wireless_networks` is
missing or malformed; Omnipet is already on a network and never reads that
key, so making a player invent SSIDs to satisfy it would be pointless. It is
now optional.

`utilities/wificom/upstream/secrets.example.json` shows the shape:
`wireless_networks` (ignored), `broker`, `mqtt_username`, `mqtt_password`,
`user_uuid`, `device_uuid`.

### The topics are built at import time

`mqtt.py` computes its topic strings once, at import, out of the credentials.
Import it before they load and the topics are built from empty strings, and
nothing reaches the broker. `services/wificom_service.py` therefore imports
`wificom.mqtt` inside its worker thread, only after `import_secrets.reload()`
has returned True — and the menu's availability check goes through
`credentials_available()`, which stats the file rather than importing `mqtt`.

## Still to do

1. ~~**A DigiROM parser.**~~ Done: `wificom/digirom.py` reads a command back
   into a signal type, a turn and its packets, and is installed into the shim
   with `set_parser()` when the service starts. Packets keep their `^`/`@`
   operators, which the adapter resolves at send time against bytes that do
   not exist until the exchange runs.
2. ~~**An executor.**~~ Done: `wificom/executor.py` plays the ROM against the
   pet through `battle/sim/` and renders the exchange the way the adapter
   prints it -- `s:` for the ROM's packets, `r:` for ours.
3. ~~**Receiving.**~~ Done: the worker polls `mqtt.get_subscribed_output()`
   each loop and publishes the result immediately, because the app is holding
   a request open waiting for it. `P` and `I` are answered without touching a
   pet.
4. **A real-time battle runner.** `realtime.py` is vendored and the parser it
   needs now exists, but nothing drives `rtb_types` yet -- an RTB invite is
   reported to the view and otherwise ignored.
5. **`Battle!` still publishes a command.** A WiFiCom is a responder: the app
   drives, and an unsolicited command lands in `last_output` where a reader
   expects an exchange. Kept for now because it is the only thing the screen
   can do, but it should either drive an RTB or go.
6. **Version reporting.** `version.dictionary()` goes to the server on every
   message. The keys are upstream's, but whether wificom.dev validates
   `circuitpython_board_id` against known boards is unconfirmed — if it does,
   `BOARD_ID` needs a value the site accepts.

## Re-syncing with upstream

1. Diff the new upstream tree against `utilities/wificom/upstream/` to see
   what actually moved.
2. Refresh `utilities/wificom/upstream/` and convert to LF — upstream ships
   CRLF, Omnipet's `.gitattributes` forces LF on `*.py` and `*.txt`.
3. Re-copy the verbatim files, re-apply `realtime.py`'s two lines, and check
   the ported and replaced files against their upstream originals.
4. Update `UPSTREAM_VERSION` / `UPSTREAM_COMMIT` in `__init__.py`, `VERSION`
   in `version.py`, and this file's header.
