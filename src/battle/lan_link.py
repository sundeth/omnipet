"""The local network link behind WiFi battles between two Omnipets.

**Discovery.** A host answers UDP requests on ``DISCOVERY_PORT``. A joining
game sends its request to every broadcast address it can work out and to
itself (two games on one computer), a few times over, and lists the hosts
that answer. The host's TCP port is ephemeral and travels in the answer, so
no other program can be sitting on it: the first version listened on a
fixed 5555, which BlueStacks' ADB also holds.

**Connection.** One TCP socket carrying newline-delimited JSON objects. A
reader thread queues what arrives and the game polls the queue once a frame,
so nothing here blocks a frame. Nothing here touches pygame either.

The battle on top of the link is ``battle.lan_battle``.
"""
import ipaddress
import json
import queue
import random
import socket
import string
import threading
import time

#: Bumped when the discovery or framing changes; a peer on another one is
#: refused before anything else is read.
PROTOCOL = 1

#: The UDP port hosts answer discovery on.
DISCOVERY_PORT = 47555

#: Discovery datagrams: a request, and a host's answer.
DISCOVER = "omnipet-discover"
ANNOUNCE = "omnipet-host"

#: The longest message line accepted; a battle log is a few kilobytes.
MAX_LINE = 1 << 20

#: How long a joining game keeps asking, and how often it asks again.
DISCOVERY_SECONDS = 3.0
DISCOVERY_INTERVAL = 0.5

CONNECT_TIMEOUT = 5.0


def host_code():
    """A short code the host shows and the joining list names it by."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=4))


def local_addresses():
    """This computer's IPv4 addresses (not loopback), best guess first."""
    found = []
    try:
        # The address the default route would use; a UDP connect sends nothing.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found:
                found.append(address)
    except OSError:
        pass
    return [a for a in found if not a.startswith("127.") and a != "0.0.0.0"]


def _adapter_broadcasts():
    """Each network adapter's own broadcast address, from its netmask
    (psutil, when installed; the builds bundle it)."""
    try:
        import psutil
        adapters = psutil.net_if_addrs()
    except Exception:  # pylint: disable=broad-except
        return []
    found = []
    for addresses in adapters.values():
        for entry in addresses:
            if entry.family != socket.AF_INET or not entry.netmask \
                    or entry.address.startswith("127."):
                continue
            try:
                network = ipaddress.IPv4Network(f"{entry.address}/{entry.netmask}", strict=False)
            except ValueError:
                continue
            found.append(str(network.broadcast_address))
    return found


def broadcast_targets():
    """Where a discovery request goes: the limited broadcast, each adapter's
    own broadcast (a computer with several adapters sends the limited one
    out of only one of them; without psutil each address's /24 is assumed)
    and this computer itself."""
    targets = ["255.255.255.255"] + _adapter_broadcasts()
    for address in local_addresses():
        targets.append(".".join(address.split(".")[:3] + ["255"]))
    targets.append("127.0.0.1")
    return list(dict.fromkeys(targets))


def _datagram(data):
    """A discovery datagram as a dict, or None."""
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return message if isinstance(message, dict) else None


# ---------------------------------------------------------------------------
# A connection
# ---------------------------------------------------------------------------

class LanConnection:
    """One open link to the other game: ``send`` a dict, ``poll`` the dicts
    that arrived. ``closed`` turns true when either side hangs up."""

    def __init__(self, sock, peer=None):
        self.peer = peer
        self.closed = False
        self._sock = sock
        self._inbox = queue.Queue()
        self._send_lock = threading.Lock()
        sock.settimeout(None)
        for option in ((socket.SOL_SOCKET, socket.SO_KEEPALIVE),
                       (socket.IPPROTO_TCP, socket.TCP_NODELAY)):
            try:
                sock.setsockopt(option[0], option[1], 1)
            except OSError:
                pass
        self._reader = threading.Thread(target=self._read, name="lan-link-reader", daemon=True)
        self._reader.start()

    def send(self, message):
        """Send one dict; False once the link is down."""
        if self.closed:
            return False
        data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            with self._send_lock:
                self._sock.sendall(data)
            return True
        except OSError:
            self.closed = True
            return False

    def poll(self):
        """Every message received since the last poll, oldest first."""
        messages = []
        while True:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                return messages

    def close(self):
        """Hang up. Everything already sent is still delivered: the reader
        drains the socket all along, so no unread data turns the close into
        a reset."""
        self.closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def _read(self):
        buffer = b""
        try:
            while True:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if isinstance(message, dict):
                        self._inbox.put(message)
                if len(buffer) > MAX_LINE:
                    break
        except OSError:
            pass
        finally:
            # Hung up by either side: release the socket as well.
            self.closed = True
            try:
                self._sock.close()
            except OSError:
                pass


def connect(address, port, timeout=CONNECT_TIMEOUT):
    """A LanConnection to a host found by ``discover``; raises OSError."""
    sock = socket.create_connection((address, int(port)), timeout=timeout)
    return LanConnection(sock, peer=address)


# ---------------------------------------------------------------------------
# Hosting
# ---------------------------------------------------------------------------

class LanHost:
    """Wait for one game to join: answer discovery, accept one connection.

    ``announce`` is merged into every discovery answer (the host's code,
    name and team size). ``poll`` returns the LanConnection once a game has
    joined; hosting then stops. ``error`` says why hosting failed.
    """

    def __init__(self, announce):
        self.announce = dict(announce)
        self.port = None
        self.error = None
        self.discoverable = False
        self._server = None
        self._udp = None
        self._joined = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        """Open the sockets (raises OSError when TCP cannot listen at all)."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("", 0))
            server.listen(1)
        except OSError:
            server.close()
            raise
        server.settimeout(0.2)
        self._server = server
        self.port = server.getsockname()[1]
        try:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp.bind(("", DISCOVERY_PORT))
            udp.settimeout(0.05)
            self._udp = udp
            self.discoverable = True
        except OSError as exc:
            # Joinable only by address; the view says so.
            self.error = "discovery port busy: %s" % exc
            self._udp = None
        self._thread = threading.Thread(target=self._serve, name="lan-host", daemon=True)
        self._thread.start()
        return self

    def poll(self):
        """The joined LanConnection, once (then None again)."""
        joined, self._joined = self._joined, None
        return joined

    def close(self):
        self._stop.set()
        for sock in (self._server, self._udp):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._server = self._udp = None
        joined, self._joined = self._joined, None
        if joined is not None:
            joined.close()

    def _answer(self):
        try:
            data, sender = self._udp.recvfrom(4096)
        except (socket.timeout, OSError):
            return
        request = _datagram(data)
        if not request or request.get("omnipet") != DISCOVER:
            return
        answer = dict(self.announce, omnipet=ANNOUNCE, protocol=PROTOCOL, port=self.port)
        try:
            self._udp.sendto(json.dumps(answer).encode("utf-8"), sender)
        except OSError:
            pass

    def _serve(self):
        while not self._stop.is_set():
            if self._udp is not None:
                self._answer()
            server = self._server
            if server is None:
                return
            try:
                sock, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if self._stop.is_set():
                sock.close()
                return
            self._joined = LanConnection(sock, peer=address[0])
            # One opponent: stop listening and answering.
            for other in (self._server, self._udp):
                if other is not None:
                    try:
                        other.close()
                    except OSError:
                        pass
            self._server = self._udp = None
            return


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------

def discover(seconds=DISCOVERY_SECONDS, interval=DISCOVERY_INTERVAL, stop=None, targets=None):
    """The hosts answering on this network, as dicts: ``code``, ``address``,
    ``port``, ``protocol`` and whatever else the host announced. A host
    reached both through loopback and through the network is listed once.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    hosts = {}
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        sock.settimeout(0.1)
        request = json.dumps({"omnipet": DISCOVER, "protocol": PROTOCOL}).encode("utf-8")
        destinations = targets if targets is not None else broadcast_targets()
        deadline = time.monotonic() + seconds
        next_send = 0.0
        while time.monotonic() < deadline and not (stop is not None and stop.is_set()):
            now = time.monotonic()
            if now >= next_send:
                for target in destinations:
                    try:
                        sock.sendto(request, (target, DISCOVERY_PORT))
                    except OSError:
                        pass
                next_send = now + interval
            try:
                data, sender = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            answer = _datagram(data)
            if not answer or answer.get("omnipet") != ANNOUNCE:
                continue
            try:
                port = int(answer.get("port"))
            except (TypeError, ValueError):
                continue
            # The same game answering through loopback and through the
            # network is listed once, by its network address.
            key = (str(answer.get("code", "")), port)
            known = hosts.get(key)
            if known is not None and not known["address"].startswith("127."):
                continue
            host = {k: v for k, v in answer.items() if k != "omnipet"}
            host.update(address=sender[0], port=port)
            hosts[key] = host
    finally:
        sock.close()
    return list(hosts.values())
