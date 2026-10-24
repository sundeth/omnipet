"""
NFC reader service
==================

Backend-abstracted NFC tag reading for the card collection:

  * Desktop (Windows/Linux/macOS): PC/SC readers (e.g. ACR122U) via pyscard.
  * Raspberry Pi: PN532 over I2C via adafruit-circuitpython-pn532.
  * Android: not implemented yet (phone NFC needs a pyjnius intent bridge).

All hardware imports are lazy and optional — when no backend library or
reader is present, `available()` is False and the Collection scene disables
its Read button.

Physical cards are NTAG-style Type 2 tags whose NDEF payload is a small
JSON written by the module editor's card maker:
    {"id": uuid, "name": ..., "value": "01011[-L|-R]", "number": n, "series": s}

Reading is done on a background thread started with `start()`; the scene
polls `get_result()` each frame. Results:
    {"card": {...payload...}}        parsed card JSON
    {"unknown": True, "uid": "..."}  a tag was read but carried no card JSON
"""

import json
import threading
import time

from core import runtime_globals


def _parse_ndef_json(data: bytes):
    """Best-effort NDEF TLV → JSON payload extraction from raw tag memory."""
    try:
        # Find the NDEF message TLV (0x03)
        i = 0
        while i < len(data):
            t = data[i]
            if t == 0x00:  # NULL TLV
                i += 1
                continue
            if t == 0xFE:  # terminator
                return None
            if i + 1 >= len(data):
                return None
            length = data[i + 1]
            if length == 0xFF:
                if i + 3 >= len(data):
                    return None
                length = (data[i + 2] << 8) | data[i + 3]
                payload_start = i + 4
            else:
                payload_start = i + 2
            if t == 0x03:
                message = data[payload_start:payload_start + length]
                return _parse_ndef_message(message)
            i = payload_start + length
        return None
    except Exception:
        return None


def _parse_ndef_message(message: bytes):
    """Extract a JSON dict from the first text/URI/MIME record in an NDEF message."""
    try:
        i = 0
        while i < len(message):
            header = message[i]
            short_record = bool(header & 0x10)
            il = bool(header & 0x08)
            type_length = message[i + 1]
            if short_record:
                payload_length = message[i + 2]
                offset = i + 3
            else:
                payload_length = int.from_bytes(message[i + 2:i + 6], "big")
                offset = i + 6
            id_length = 0
            if il:
                id_length = message[offset]
                offset += 1
            rtype = bytes(message[offset:offset + type_length])
            offset += type_length + id_length
            payload = bytes(message[offset:offset + payload_length])

            text = None
            if rtype == b"T" and payload:
                # Text record: status byte + language code, then the text
                lang_len = payload[0] & 0x3F
                text = payload[1 + lang_len:].decode("utf-8", "ignore")
            elif rtype == b"U" and payload:
                text = payload[1:].decode("utf-8", "ignore")
            else:
                # MIME (e.g. application/json) or unknown — try raw utf-8
                text = payload.decode("utf-8", "ignore")

            if text:
                text = text.strip()
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end > start:
                    try:
                        parsed = json.loads(text[start:end + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass

            if header & 0x40:  # ME: last record
                return None
            i = offset + payload_length
        return None
    except Exception:
        return None


class _PcscBackend:
    """PC/SC smartcard readers (ACR122U and friends) via pyscard."""

    name = "pcsc"

    def __init__(self):
        from smartcard.System import readers  # noqa: F401 (import check)
        self._readers_fn = readers
        if not readers():
            raise RuntimeError("no PC/SC readers connected")

    def read_tag(self):
        """Try to read a tag once. Returns a result dict or None if no tag."""
        from smartcard.Exceptions import NoCardException, CardConnectionException
        reader_list = self._readers_fn()
        if not reader_list:
            return None
        try:
            connection = reader_list[0].createConnection()
            connection.connect()
        except (NoCardException, CardConnectionException):
            return None
        except Exception:
            return None

        try:
            # UID: FF CA 00 00 00
            uid_resp, sw1, sw2 = connection.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
            uid = "".join(f"{b:02X}" for b in uid_resp) if sw1 == 0x90 else ""

            # Dump NTAG user memory: 16-byte reads from page 4 upward.
            data = bytearray()
            for page in range(4, 132, 4):
                resp, sw1, sw2 = connection.transmit([0xFF, 0xB0, 0x00, page, 0x10])
                if sw1 != 0x90:
                    break
                data.extend(resp)
                if 0xFE in resp:  # NDEF terminator seen — enough data
                    break

            payload = _parse_ndef_json(bytes(data))
            if payload:
                return {"card": payload, "uid": uid}
            return {"unknown": True, "uid": uid}
        except Exception:
            return None
        finally:
            try:
                connection.disconnect()
            except Exception:
                pass


class _Pn532I2cBackend:
    """PN532 breakout over I2C (Raspberry Pi) via adafruit-circuitpython-pn532."""

    name = "pn532_i2c"

    def __init__(self):
        import board
        import busio
        from adafruit_pn532.i2c import PN532_I2C
        i2c = busio.I2C(board.SCL, board.SDA)
        self._pn532 = PN532_I2C(i2c, debug=False)
        self._pn532.SAM_configuration()

    def read_tag(self):
        uid_bytes = self._pn532.read_passive_target(timeout=0.2)
        if uid_bytes is None:
            return None
        uid = "".join(f"{b:02X}" for b in uid_bytes)
        data = bytearray()
        try:
            for block in range(4, 132):
                chunk = self._pn532.ntag2xx_read_block(block)
                if chunk is None:
                    break
                data.extend(chunk)
                if 0xFE in chunk:
                    break
        except Exception:
            pass
        payload = _parse_ndef_json(bytes(data))
        if payload:
            return {"card": payload, "uid": uid}
        return {"unknown": True, "uid": uid}


class NfcService:
    """Reader detection + background polling. Safe to use with no hardware."""

    def __init__(self):
        self._backend = None
        self._detected = None  # None = not probed yet
        self._thread = None
        self._stop_flag = threading.Event()
        self._result = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        """True when a compatible reader is present (probes once, cached)."""
        if self._detected is None:
            self._backend = self._detect_backend()
            self._detected = self._backend is not None
            if self._detected:
                runtime_globals.game_console.log(
                    f"[NFC] Reader detected (backend: {self._backend.name})")
            else:
                runtime_globals.game_console.log("[NFC] No NFC reader available")
        return self._detected

    def _detect_backend(self):
        if runtime_globals.IS_ANDROID:
            # TODO: Android phone NFC via pyjnius intents.
            return None
        for backend_cls in (_PcscBackend, _Pn532I2cBackend):
            try:
                return backend_cls()
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Background polling
    # ------------------------------------------------------------------

    def start(self):
        """Begin polling for a tag on a background thread."""
        if not self.available() or (self._thread and self._thread.is_alive()):
            return
        self._stop_flag.clear()
        with self._lock:
            self._result = None
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag.set()

    def get_result(self):
        """The last read result (consumed on read), or None while waiting."""
        with self._lock:
            result = self._result
            self._result = None
        return result

    def _poll_loop(self):
        while not self._stop_flag.is_set():
            try:
                result = self._backend.read_tag()
            except Exception as exc:
                runtime_globals.game_console.log(f"[NFC] read error: {exc}")
                result = None
            if result:
                with self._lock:
                    self._result = result
                return  # one read per start()
            time.sleep(0.25)


nfc_service = NfcService()
