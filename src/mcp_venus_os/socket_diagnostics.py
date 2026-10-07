"""Bounded transport metadata without reading or changing the MQTT stream.

Linux TCP_INFO uses the stable 104-byte prefix of ``struct tcp_info`` through
``tcpi_total_retrans``. Its eight initial bytes precede native-endian __u32
fields; explicit offsets avoid ctypes bitfield and alignment differences.
Reference: Linux v6.8, include/uapi/linux/tcp.h (struct tcp_info).
https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/tcp.h

SIOCINQ/FIONREAD reports queued receive bytes; SIOCOUTQ/TIOCOUTQ reports bytes
not yet sent or acknowledged. Architecture-specific ioctl numbers come from
termios, not hard-coded asm-generic values. The returned integer is a native
signed C int (32 bits on supported Linux ABIs). Queue sizes concern the kernel
socket; for TLS they do not include decrypted bytes buffered by the TLS layer.
https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/sockios.h
"""

import socket
import struct
import sys
from typing import Protocol, cast

try:
    import fcntl
    import termios
except ImportError:  # Windows has neither; unsupported platforms remain importable.
    fcntl = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]

_TCP_INFO_SIZE = 104
_U32 = struct.Struct("=I")  # Native byte order, fixed width, no implicit padding.
_C_INT = struct.Struct("=i")
_BYTE_FIELDS = ("state", "ca_state", "retransmits", "probes", "backoff")
_U32_FIELDS = {
    "rto_us": 8,
    "unacked": 24,
    "lost": 32,
    "retrans": 36,
    "last_data_sent_ms": 44,
    "last_data_recv_ms": 52,
    "last_ack_recv_ms": 56,
    "rtt_us": 68,
    "rttvar_us": 72,
    "snd_cwnd": 80,
    "total_retrans": 100,
}


class _SocketMetadata(Protocol):
    def fileno(self) -> int: ...

    def getsockopt(self, level: int, option: int, length: int) -> bytes: ...


def _tcp_info(sock: _SocketMetadata) -> dict[str, int | str]:
    option = getattr(socket, "TCP_INFO", None)
    if option is None:
        return {"tcp_info_status": "unsupported"}
    try:
        raw = sock.getsockopt(socket.IPPROTO_TCP, option, _TCP_INFO_SIZE)
    except Exception:
        # Exception strings can contain addresses or wrapper-specific secrets.
        return {"tcp_info_status": "unavailable"}
    if not isinstance(raw, bytes):
        return {"tcp_info_status": "unavailable"}
    if len(raw) < _TCP_INFO_SIZE:
        return {"tcp_info_status": "short"}
    result: dict[str, int | str] = {"tcp_info_status": "ok"}
    result.update({name: raw[offset] for offset, name in enumerate(_BYTE_FIELDS)})
    result.update({name: _U32.unpack_from(raw, offset)[0] for name, offset in _U32_FIELDS.items()})
    return result


def _queue(sock: _SocketMetadata, request: int | None, name: str) -> dict[str, int | str]:
    status = name + "_status"
    if fcntl is None or request is None:
        return {status: "unsupported"}
    try:
        # Passing the socket itself avoids retaining a file descriptor after closure.
        # An immutable buffer makes ioctl return only the four metadata bytes.
        raw = fcntl.ioctl(sock, request, _C_INT.pack(0))
    except Exception:
        return {status: "unavailable"}
    if not isinstance(raw, bytes) or len(raw) != _C_INT.size:
        return {status: "unavailable"}
    value = _C_INT.unpack(raw)[0]
    if value < 0:
        return {status: "unavailable"}
    return {status: "ok", name + "_bytes": value}


def sample_socket(sock: object | None) -> dict[str, int | str]:
    """Read one bounded, best-effort Linux socket metadata snapshot.

    ``status`` is ok/partial/no_socket/closed/unsupported/unavailable. On Linux
    each attempted component also has a fixed status: tcp_info_status is
    ok/short/unsupported/unavailable; recv_queue_status and send_queue_status
    are ok/unsupported/unavailable. Missing measurements are omitted, never
    synthesized as zero. Numeric values follow the explicit allowlists above.

    Only fileno(), getsockopt(TCP_INFO), and two read-only queue ioctls are used.
    There are no reads/peeks, addresses, file descriptor values, socket writes,
    option changes, background work, or exception text in the returned mapping.
    The three measurements are sequential, not an atomic transport snapshot.
    """
    if sock is None:
        return {"status": "no_socket"}
    if sys.platform != "linux":
        return {"status": "unsupported"}
    candidate = cast(_SocketMetadata, sock)
    try:
        descriptor = candidate.fileno()
    except Exception:
        return {"status": "unavailable"}
    if not isinstance(descriptor, int) or isinstance(descriptor, bool):
        return {"status": "unavailable"}
    if descriptor < 0:
        return {"status": "closed"}
    result = _tcp_info(candidate)
    result.update(_queue(candidate, getattr(termios, "FIONREAD", None), "recv_queue"))
    result.update(_queue(candidate, getattr(termios, "TIOCOUTQ", None), "send_queue"))
    statuses = (result["tcp_info_status"], result["recv_queue_status"], result["send_queue_status"])
    result["status"] = "ok" if all(status == "ok" for status in statuses) else "partial"
    return result
