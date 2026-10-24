"""The link behind online (Discord) battles: Omninet's relay rooms.

A relay room (Omninet ``omninet/discord/relay.py``, ``GameRooms``) keeps one
message queue that both players post to (``POST /room/{id}/data``) and read
the last 50 entries of (``GET /room/{id}/status``). ``RelayLink`` turns that
into what ``battle.lan_link.LanConnection`` offers -- ``send`` a dict,
``poll`` the dicts that arrived, ``close``, ``closed`` -- so the WiFi
battle's handshake (``battle.lan_battle.Session``) runs over it unchanged.

Each message is posted as ``{"omnipet": 1, "from": role, "seq": n, "msg":
...}``: a game reads only the other role's entries, each once, in order.
Posting and polling run on a worker thread; the game polls the inbox once a
frame. The relay cannot tell when a player simply goes away, so a room that
disappears (``fetch`` answers None) is the only hang-up besides "bye".

Nothing here touches pygame or the network itself: ``post(data) -> bool``
and ``fetch() -> list | None`` are handed in (``DiscordModule``'s).
"""
import queue
import threading

#: Tags the relay entries this link wrote, apart from anything else posted
#: to the room.
TAG = 1

POLL_SECONDS = 0.5

#: Consecutive fetches that find no room before the link counts as down.
MISSING_ROOM_LIMIT = 3


class RelayLink:
    """One player's side of a relay room, as a link."""

    def __init__(self, post, fetch, role, peer=None, poll_seconds=POLL_SECONDS):
        if role not in ("host", "guest"):
            raise ValueError("role is host or guest")
        self.peer = peer
        self.role = role
        self.other = "guest" if role == "host" else "host"
        self.closed = False
        self._post = post
        self._fetch = fetch
        self._poll_seconds = poll_seconds
        self._seq = 0
        self._seen = 0
        self._inbox = queue.Queue()
        self._outbox = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="relay-link", daemon=True)
        self._worker.start()

    def send(self, message):
        """Queue one dict for the other player; False once the link is down."""
        if self.closed:
            return False
        with self._lock:
            self._seq += 1
            self._outbox.put({"omnipet": TAG, "from": self.role, "seq": self._seq, "msg": message})
        return True

    def poll(self):
        """Every message received since the last poll, oldest first."""
        messages = []
        while True:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                return messages

    def close(self):
        """Hang up. What was already sent (a "bye") still goes out."""
        self.closed = True
        self._stop.set()

    # ------------------------------------------------------------- worker
    def _flush(self):
        while True:
            try:
                entry = self._outbox.get_nowait()
            except queue.Empty:
                return True
            if not self._post(entry):
                return False

    def _receive(self, entries):
        for entry in entries:
            data = entry.get("data") if isinstance(entry, dict) else None
            if not isinstance(data, dict) or data.get("omnipet") != TAG \
                    or data.get("from") != self.other:
                continue
            seq = data.get("seq")
            if not isinstance(seq, int) or seq <= self._seen:
                continue
            self._seen = seq
            if isinstance(data.get("msg"), dict):
                self._inbox.put(data["msg"])

    def _run(self):
        missing = 0
        try:
            while not self._stop.is_set():
                if not self._flush():
                    break
                entries = self._fetch()
                if entries is None:
                    missing += 1
                    if missing >= MISSING_ROOM_LIMIT:
                        break
                else:
                    missing = 0
                    self._receive(entries)
                self._stop.wait(self._poll_seconds)
            else:
                self._flush()      # the last words (a bye) after close()
        except Exception:  # pylint: disable=broad-except
            pass
        finally:
            self.closed = True
