"""Socket diagnostics expose numeric kernel metadata, never the byte stream."""

import ctypes
import json
import socket
import struct
import sys
from types import SimpleNamespace

import pytest

from mcp_venus_os import socket_diagnostics as diagnostics

_UAPI_U32_NAMES = (
    "rto",
    "ato",
    "snd_mss",
    "rcv_mss",
    "unacked",
    "sacked",
    "lost",
    "retrans",
    "fackets",
    "last_data_sent",
    "last_ack_sent",
    "last_data_recv",
    "last_ack_recv",
    "pmtu",
    "rcv_ssthresh",
    "rtt",
    "rttvar",
    "snd_ssthresh",
    "snd_cwnd",
    "advmss",
    "reordering",
    "rcv_rtt",
    "rcv_space",
    "total_retrans",
)


class _LinuxTCPInfoPrefix(ctypes.Structure):
    # Independently model the stable prefix from the Linux6.8 UAPI. The header
    # contains byte-sized flags/bitfields whose bit ordering we never decode.
    _fields_ = [("header", ctypes.c_ubyte * 8)] + [
        (name, ctypes.c_uint32) for name in _UAPI_U32_NAMES
    ]


def _native_info() -> bytes:
    info = _LinuxTCPInfoPrefix()
    for i in range(8):
        info.header[i] = i + 1
    for i, name in enumerate(_UAPI_U32_NAMES):
        setattr(info, name, 0x10203040 + i)
    return bytes(info)


class MetadataSocket:
    def __init__(self, info: object = None, descriptor: object = 9) -> None:
        self.info = _native_info() if info is None else info
        self.descriptor = descriptor
        self.calls: list[str] = []
        self.forbidden: list[str] = []

    def fileno(self) -> object:
        self.calls.append("fileno")
        if isinstance(self.descriptor, Exception):
            raise self.descriptor
        return self.descriptor

    def getsockopt(self, level: int, option: int, length: int) -> object:
        self.calls.append("getsockopt")
        assert (level, option, length) == (socket.IPPROTO_TCP, 11, 104)
        if isinstance(self.info, Exception):
            raise self.info
        return self.info

    def __getattr__(self, name: str) -> object:
        self.forbidden.append(name)
        raise AssertionError(name)


@pytest.fixture
def linux_metadata(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(socket, "TCP_INFO", 11, raising=False)
    monkeypatch.setattr(diagnostics, "termios", SimpleNamespace(FIONREAD=0x541B, TIOCOUTQ=0x5411))
    calls: list[int] = []

    def ioctl(sock: object, request: int, buffer: bytes) -> bytes:
        assert isinstance(sock, MetadataSocket)
        assert buffer == struct.pack("=i", 0)
        calls.append(request)
        assert request in (0x541B, 0x5411)
        return struct.pack("=i", 17 if request == 0x541B else 29)

    monkeypatch.setattr(diagnostics, "fcntl", SimpleNamespace(ioctl=ioctl))
    return calls


def test_native_uapi_prefix_offsets_and_integer_abi() -> None:
    assert ctypes.sizeof(_LinuxTCPInfoPrefix) == 104
    assert ctypes.sizeof(ctypes.c_int) == struct.calcsize("=i") == 4
    assert _LinuxTCPInfoPrefix.rto.offset == 8
    assert _LinuxTCPInfoPrefix.rtt.offset == 68
    assert _LinuxTCPInfoPrefix.total_retrans.offset == 100


def test_only_allowlisted_metadata_is_returned(linux_metadata: list[int]) -> None:
    sock = MetadataSocket()
    result = diagnostics.sample_socket(sock)
    assert result == {
        "status": "ok",
        "tcp_info_status": "ok",
        "recv_queue_status": "ok",
        "send_queue_status": "ok",
        "state": 1,
        "ca_state": 2,
        "retransmits": 3,
        "probes": 4,
        "backoff": 5,
        "rto_us": 0x10203040,
        "unacked": 0x10203044,
        "lost": 0x10203046,
        "retrans": 0x10203047,
        "last_data_sent_ms": 0x10203049,
        "last_data_recv_ms": 0x1020304B,
        "last_ack_recv_ms": 0x1020304C,
        "rtt_us": 0x1020304F,
        "rttvar_us": 0x10203050,
        "snd_cwnd": 0x10203052,
        "total_retrans": 0x10203057,
        "recv_queue_bytes": 17,
        "send_queue_bytes": 29,
    }
    assert linux_metadata == [0x541B, 0x5411]
    assert sock.calls == ["fileno", "getsockopt"]
    assert not sock.forbidden
    assert len(json.dumps(result)) < 700


@pytest.mark.parametrize("length", [0, 1, 7, 8, 67, 68, 103])
def test_short_tcp_info_never_decodes_missing_fields(
    linux_metadata: list[int], length: int
) -> None:
    result = diagnostics.sample_socket(MetadataSocket(_native_info()[:length]))
    assert result == {
        "status": "partial",
        "tcp_info_status": "short",
        "recv_queue_status": "ok",
        "recv_queue_bytes": 17,
        "send_queue_status": "ok",
        "send_queue_bytes": 29,
    }


def test_unknown_tcp_info_suffix_is_not_returned(linux_metadata: list[int]) -> None:
    result = diagnostics.sample_socket(MetadataSocket(_native_info() + b"secret-address-payload"))
    assert result == diagnostics.sample_socket(MetadataSocket())
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "info", [OSError("secret-peer-password"), RuntimeError("secret"), 42, "secret"]
)
def test_tcp_info_failures_keep_queues_and_hide_details(
    linux_metadata: list[int], info: object
) -> None:
    result = diagnostics.sample_socket(MetadataSocket(info))
    assert result["tcp_info_status"] == "unavailable"
    assert result["recv_queue_bytes"] == 17
    assert result["send_queue_bytes"] == 29
    assert "state" not in result
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("descriptor", [-1, OSError("secret-fd"), "9", True])
def test_closed_or_invalid_socket_is_not_inspected(
    linux_metadata: list[int], descriptor: object
) -> None:
    sock = MetadataSocket(descriptor=descriptor)
    expected = "closed" if descriptor == -1 else "unavailable"
    assert diagnostics.sample_socket(sock) == {"status": expected}
    assert sock.calls == ["fileno"]
    assert not linux_metadata


def test_no_socket_does_not_access_platform_apis(linux_metadata: list[int]) -> None:
    assert diagnostics.sample_socket(None) == {"status": "no_socket"}
    assert not linux_metadata


def test_unsupported_platform_never_touches_the_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = MetadataSocket()
    monkeypatch.setattr(sys, "platform", "win32")
    assert diagnostics.sample_socket(sock) == {"status": "unsupported"}
    assert sock.calls == []
    assert sock.forbidden == []


@pytest.mark.parametrize(
    "reply", [OSError("secret-ioctl"), b"", b"12345", -1, struct.pack("=i", -1)]
)
def test_queue_failures_are_independent_and_do_not_hide_tcp_info(
    linux_metadata: list[int], monkeypatch: pytest.MonkeyPatch, reply: object
) -> None:
    def ioctl(sock: object, request: int, buffer: bytes) -> object:
        if request == 0x5411:
            return struct.pack("=i", 7)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(diagnostics, "fcntl", SimpleNamespace(ioctl=ioctl))
    result = diagnostics.sample_socket(MetadataSocket())
    assert result["status"] == "partial"
    assert result["tcp_info_status"] == "ok"
    assert result["recv_queue_status"] == "unavailable"
    assert "recv_queue_bytes" not in result
    assert result["send_queue_bytes"] == 7
    assert "secret" not in json.dumps(result)


def test_missing_optional_apis_degrade_without_inventing_zeros(
    linux_metadata: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(socket, "TCP_INFO")
    monkeypatch.setattr(diagnostics, "termios", None)
    monkeypatch.setattr(diagnostics, "fcntl", None)
    assert diagnostics.sample_socket(MetadataSocket()) == {
        "status": "partial",
        "tcp_info_status": "unsupported",
        "recv_queue_status": "unsupported",
        "send_queue_status": "unsupported",
    }


@pytest.mark.skipif(sys.platform != "linux", reason="Uses real Linux queue ioctl ABI")
def test_linux_socketpair_metadata_does_not_consume_payload_or_change_socket() -> None:
    # AF_UNIX stays entirely local and deliberately lacks TCP_INFO support.
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"local-test-payload")
        timeout = right.gettimeout()
        result = diagnostics.sample_socket(right)
        assert result["tcp_info_status"] == "unavailable"
        assert result["recv_queue_status"] == "ok"
        assert result["recv_queue_bytes"] == len(b"local-test-payload")
        assert right.gettimeout() == timeout
        assert right.recv(100) == b"local-test-payload"
