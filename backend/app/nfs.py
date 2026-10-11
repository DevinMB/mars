"""Lists the folders an NFS server shares, so nobody has to find the export path.

The path is often not what a NAS shows its user: UniFi shares a folder called
"mars.savepoints" as /volume/<uuid>/.srv/.unifi-drive/mars.savepoints/.data. The
usual way to find it is `showmount -e`, a terminal on a machine with the NFS
tools. This asks the server the same question: the MOUNT protocol's EXPORT call,
found through the portmapper, over TCP. Read-only, and it mounts nothing.

ONC RPC (RFC 5531) with XDR encoding, the subset these two calls need.
"""
from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

PORTMAP = (100000, 2)
MOUNT = (100005, 3)
_GETPORT, _EXPORT = 3, 5
_TCP = 6
_XID = 0x4D415253  # "MARS"


class NfsError(RuntimeError):
    pass


@dataclass
class Export:
    path: str
    # What the server allows to mount it: host names, addresses or networks.
    # Empty means everyone.
    clients: list[str]

    @property
    def name(self) -> str:
        """What the folder is called, as its owner would recognise it.

        The last part of the path that is not hidden: UniFi puts the share name
        before a final ".data".
        """
        parts = [p for p in self.path.split("/") if p and not p.startswith(".")]
        return parts[-1] if parts else self.path


def _recv(sock: socket.socket, n: int) -> bytes:
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise NfsError("The server closed the connection.")
        out += chunk
    return out


def _call(host: str, port: int, program: tuple[int, int], proc: int,
          args: bytes = b"", timeout: float = 4.0) -> bytes:
    prog, vers = program
    # Call header, then empty (AUTH_NONE) credentials and verifier.
    msg = struct.pack(">IIIIII", _XID, 0, 2, prog, vers, proc) + struct.pack(">IIII", 0, 0, 0, 0) + args
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(struct.pack(">I", 0x80000000 | len(msg)) + msg)
        data, last = b"", False
        while not last:  # record marking: fragments until the last-fragment bit
            (header,) = struct.unpack(">I", _recv(sock, 4))
            last = bool(header & 0x80000000)
            data += _recv(sock, header & 0x7FFFFFFF)
    if len(data) < 24:
        raise NfsError("The server sent a reply too short to read.")
    xid, kind, status = struct.unpack(">III", data[:12])
    if xid != _XID or kind != 1:
        raise NfsError("The server's reply did not match the request.")
    if status != 0:
        raise NfsError("The server refused the request.")
    _, verf_len = struct.unpack(">II", data[12:20])
    at = 20 + ((verf_len + 3) & ~3)
    (accepted,) = struct.unpack(">I", data[at:at + 4])
    if accepted != 0:
        raise NfsError("The server does not offer this (no NFS version 3 mount service).")
    return data[at + 4:]


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.at = data, 0

    def u32(self) -> int:
        if self.at + 4 > len(self.data):
            raise NfsError("The server's list of shares was cut short.")
        (v,) = struct.unpack(">I", self.data[self.at:self.at + 4])
        self.at += 4
        return v

    def string(self) -> str:
        n = self.u32()
        if n > 4096 or self.at + n > len(self.data):
            raise NfsError("The server's list of shares was cut short.")
        v = self.data[self.at:self.at + n].decode("utf-8", "replace")
        self.at += (n + 3) & ~3
        return v


def parse_exports(body: bytes) -> list[Export]:
    r = _Reader(body)
    out = []
    while r.u32() and len(out) < 500:
        path = r.string()
        clients = []
        while r.u32() and len(clients) < 500:
            clients.append(r.string())
        out.append(Export(path=path, clients=clients))
    return out


def exports(host: str) -> list[Export]:
    try:
        reply = _call(host, 111, PORTMAP, _GETPORT, struct.pack(">IIII", *MOUNT, _TCP, 0))
        (port,) = struct.unpack(">I", reply[:4])
        if not port:
            raise NfsError("The server is not sharing anything over NFS version 3.")
        return parse_exports(_call(host, port, MOUNT, _EXPORT))
    except NfsError:
        raise
    except socket.timeout as exc:
        raise NfsError("The server did not answer.") from exc
    except OSError as exc:
        raise NfsError(f"Could not reach it: {exc.strerror or exc}") from exc
    except struct.error as exc:
        raise NfsError("The server's reply could not be read.") from exc
