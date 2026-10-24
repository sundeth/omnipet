# -*- coding: utf-8 -*-
"""A minimal MQTT 3.1.1 broker on 127.0.0.1, for testing the paho transport.

Only what a WiFiCom session uses: CONNECT/CONNACK (username and password
checked when accounts are given), SUBSCRIBE/SUBACK and UNSUBSCRIBE/UNSUBACK
on exact topics, PUBLISH at QoS 0, PINGREQ/PINGRESP and DISCONNECT. No TLS:
wificom.dev's broker speaks TLS on 8883, which ``transport.MqttClient`` sets
up with ``use_tls``; everything above the socket is the same.
"""
import socket
import struct
import threading


def _encode_length(n):
    out = bytearray()
    while True:
        byte = n % 128
        n //= 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _string(data, at):
    (n,) = struct.unpack_from("!H", data, at)
    return data[at + 2:at + 2 + n].decode("utf-8"), at + 2 + n


class MiniBroker:
    def __init__(self, accounts=None):
        self.accounts = accounts
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.lock = threading.Lock()
        self.subscriptions = {}         # socket -> set(topic)
        self.published = []             # (topic, payload text)
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self.closed = True
        try:
            self.server.close()
        except OSError:
            pass
        with self.lock:
            for sock in list(self.subscriptions):
                try:
                    sock.close()
                except OSError:
                    pass

    def _accept(self):
        while not self.closed:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _read_packet(self, sock):
        head = sock.recv(1)
        if not head:
            return None, None
        multiplier, length = 1, 0
        while True:
            byte = sock.recv(1)
            if not byte:
                return None, None
            length += (byte[0] & 0x7F) * multiplier
            if not byte[0] & 0x80:
                break
            multiplier *= 128
        body = b""
        while len(body) < length:
            chunk = sock.recv(length - len(body))
            if not chunk:
                return None, None
            body += chunk
        return head[0], body

    def _send(self, sock, kind, body):
        try:
            sock.sendall(bytes([kind]) + _encode_length(len(body)) + body)
        except OSError:
            pass

    def publish(self, topic, payload):
        """Publish from the broker side (the site)."""
        text = payload if isinstance(payload, str) else payload.decode("utf-8")
        data = topic.encode("utf-8")
        body = struct.pack("!H", len(data)) + data + text.encode("utf-8")
        with self.lock:
            self.published.append((topic, text))
            targets = [s for s, topics in self.subscriptions.items() if topic in topics]
        for sock in targets:
            self._send(sock, 0x30, body)

    def _serve(self, sock):
        try:
            while not self.closed:
                kind, body = self._read_packet(sock)
                if kind is None:
                    break
                packet = kind >> 4
                if packet == 1:                                   # CONNECT
                    at = 0
                    _, at = _string(body, at)                     # protocol name
                    flags = body[at + 1]
                    at += 4                                       # level, flags, keepalive
                    _, at = _string(body, at)                     # client id
                    username = password = None
                    if flags & 0x80:
                        username, at = _string(body, at)
                    if flags & 0x40:
                        password, at = _string(body, at)
                    ok = self.accounts is None or self.accounts.get(username) == password
                    self._send(sock, 0x20, bytes([0, 0 if ok else 5]))
                    if not ok:
                        break
                    with self.lock:
                        self.subscriptions[sock] = set()
                elif packet == 8:                                 # SUBSCRIBE
                    (mid,) = struct.unpack_from("!H", body, 0)
                    at, granted = 2, []
                    while at < len(body):
                        topic, at = _string(body, at)
                        at += 1
                        with self.lock:
                            self.subscriptions.setdefault(sock, set()).add(topic)
                        granted.append(0)
                    self._send(sock, 0x90, struct.pack("!H", mid) + bytes(granted))
                elif packet == 10:                                # UNSUBSCRIBE
                    (mid,) = struct.unpack_from("!H", body, 0)
                    at = 2
                    while at < len(body):
                        topic, at = _string(body, at)
                        with self.lock:
                            self.subscriptions.get(sock, set()).discard(topic)
                    self._send(sock, 0xB0, struct.pack("!H", mid))
                elif packet == 3:                                 # PUBLISH (QoS 0)
                    topic, at = _string(body, 0)
                    if (kind >> 1) & 3:
                        at += 2
                    self.publish(topic, body[at:])
                elif packet == 12:                                # PINGREQ
                    self._send(sock, 0xD0, b"")
                elif packet == 14:                                # DISCONNECT
                    break
        finally:
            with self.lock:
                self.subscriptions.pop(sock, None)
            try:
                sock.close()
            except OSError:
                pass
