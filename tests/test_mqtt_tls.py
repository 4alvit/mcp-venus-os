"""Actual MQTT 3.1.1/TLS handshakes with disposable loopback identities."""

import asyncio
import contextlib
import os
import socket
import ssl
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import paho.mqtt.client as paho
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from paho.mqtt.enums import CallbackAPIVersion

from mcp_venus_os import mqtt_client
from mcp_venus_os.config import MQTTConfig, ServerConfig
from mcp_venus_os.tls_policy import enforce_peer_key_policy, mqtt_context

Key = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey
CHAIN_CASES = (
    "strong",
    "strong-ec",
    "weak-leaf",
    "weak-intermediate",
    "weak-root",
    "weak-2047-leaf",
    "weak-2047-intermediate",
    "weak-2047-root",
    "weak-ec-root",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.upper().endswith("_PROXY") or name in (
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "REQUESTS_CA_BUNDLE",
            "CURL_CA_BUNDLE",
        ):
            monkeypatch.delenv(name)


def certificate(
    key: Key, name: str, issuer: x509.Certificate | None, issuer_key: Key, *, ca: bool
) -> x509.Certificate:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=not ca,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=ca,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), False
        )
    )
    if not ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.DNSName("sub.localhost")]),
            False,
        ).add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def chains(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Path, Path]]:
    directory = tmp_path_factory.mktemp("mqtt-synthetic-pki")
    result = {}
    for case in CHAIN_CASES:
        root_bits = {"weak-root": 1024, "weak-2047-root": 2047}.get(case, 2048)
        root_key: Key
        if case in ("strong-ec", "weak-ec-root"):
            curve = ec.SECP192R1() if case == "weak-ec-root" else ec.SECP256R1()
            root_key = ec.generate_private_key(curve)
        else:
            root_key = rsa.generate_private_key(65537, root_bits)
        root = certificate(root_key, case, None, root_key, ca=True)
        issuer, issuer_key = root, root_key
        intermediate = b""
        if case in ("weak-intermediate", "weak-2047-intermediate"):
            # Deliberately weak, disposable certificate for rejection testing.
            issuer_key = rsa.generate_private_key(
                65537, 1024 if case == "weak-intermediate" else 2047
            )
            issuer = certificate(issuer_key, "intermediate", root, root_key, ca=True)
            intermediate = issuer.public_bytes(serialization.Encoding.PEM)
        leaf_key: Key = (
            ec.generate_private_key(ec.SECP256R1())
            if case == "strong-ec"
            else rsa.generate_private_key(
                65537, {"weak-leaf": 1024, "weak-2047-leaf": 2047}.get(case, 2048)
            )
        )
        leaf = certificate(leaf_key, "localhost", issuer, issuer_key, ca=False)
        cert_file, key_file, ca_file = (
            directory / f"{case}.{suffix}" for suffix in ("pem", "key", "ca")
        )
        cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + intermediate)
        key_file.write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        ca_file.write_bytes(root.public_bytes(serialization.Encoding.PEM))
        result[case] = cert_file, key_file, ca_file
    return result


@contextlib.contextmanager
def broker(
    chain: tuple[Path, Path, Path], version: ssl.TLSVersion, *, client_auth: bool = False
) -> Iterator[tuple[int, dict[str, Any]]]:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = version
    context.set_ciphers("DEFAULT:@SECLEVEL=0")
    context.load_cert_chain(chain[0], chain[1])
    if client_auth:
        context.load_verify_locations(chain[2])
        context.verify_mode = ssl.CERT_REQUIRED
    observed: dict[str, Any] = {"bytes": b""}
    stop = threading.Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve() -> None:
            try:
                raw, _ = listener.accept()
                with raw:
                    raw.settimeout(5)
                    with context.wrap_socket(raw, server_side=True) as connection:
                        observed["tls"] = connection.version()
                        if client_auth:
                            observed["client_certificate"] = connection.getpeercert(
                                binary_form=True
                            )
                        header = connection.recv(1)
                        if not header:
                            return
                        observed["bytes"] = header
                        assert header == b"\x10"
                        length = 0
                        for shift in range(0, 28, 7):
                            value = connection.recv(1)
                            assert len(value) == 1
                            observed["bytes"] += value
                            length += (value[0] & 127) << shift
                            if value[0] < 128:
                                break
                        assert value[0] < 128, "Invalid CONNECT length"
                        assert length < 8192
                        data = b""
                        while len(data) < length:
                            part = connection.recv(length - len(data))
                            assert part
                            data += part
                            observed["bytes"] += part
                        assert data[6] == 4
                        connection.sendall(b"\x20\x02\x00\x00")
                        connection.settimeout(0.1)
                        while not stop.is_set():
                            try:
                                if not connection.recv(4096):
                                    break
                            except TimeoutError:
                                continue
            except (ssl.SSLError, ConnectionError) as error:
                observed["tls_error"] = str(error)
            except Exception as error:
                observed["unexpected"] = repr(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield listener.getsockname()[1], observed
        finally:
            stop.set()
            thread.join(6)
            assert not thread.is_alive()
            assert "unexpected" not in observed, observed


def calibrate(chain: tuple[Path, Path, Path], version: ssl.TLSVersion) -> None:
    # This oracle alone permits weak keys; normal CA and hostname checks remain.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = version
    context.set_ciphers("DEFAULT:@SECLEVEL=0")
    context.load_verify_locations(chain[2])
    with (
        broker(chain, version) as (port, observed),
        socket.create_connection(("localhost", port), timeout=5) as raw,
        context.wrap_socket(raw, server_hostname="localhost") as connection,
    ):
        assert connection.version() == version.name.replace("_", ".")
    assert observed["tls"] == version.name.replace("_", ".")
    assert not observed["bytes"]


async def connect_once(client: mqtt_client.MQTTClient, failures: list[Exception]) -> bool:
    task = asyncio.create_task(client.connect())
    try:
        for _ in range(600):
            if task.done():
                task.result()
                return True
            if failures:
                return False
            await asyncio.sleep(0.01)
        message = "No native TLS outcome before deadline"
        raise AssertionError(message)
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await client.disconnect()
        assert client.client is None
        assert client._worker is None
        assert client._loop_thread is None


@pytest.mark.parametrize("case", [*CHAIN_CASES, "untrusted", "wrong-host"])
@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
async def test_actual_mqtt_rejects_before_connect_credentials(
    chains: dict[str, tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    version: ssl.TLSVersion,
) -> None:
    chain = chains.get(case, chains["strong"])
    calibrate(chain, version)
    ca = chains["strong-ec"][2] if case == "untrusted" else chain[2]
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    failures: list[Exception] = []
    original = paho.Client._ssl_wrap_socket

    def observed_handshake(client: paho.Client, raw: socket.socket) -> ssl.SSLSocket:
        try:
            return original(client, raw)
        except ssl.SSLError as error:
            failures.append(error)
            raise

    monkeypatch.setattr(paho.Client, "_ssl_wrap_socket", observed_handshake)
    with broker(chain, version) as (port, observed):
        config = ServerConfig(
            mqtt=MQTTConfig(
                host="127.0.0.1" if case == "wrong-host" else "localhost",
                port=port,
                tls=True,
                username="synthetic-user",
                password="synthetic-password",
                portal_id="synthetic",
            )
        )
        monkeypatch.setattr(mqtt_client, "get_config", lambda: config)
        accepted = await connect_once(mqtt_client.MQTTClient(), failures)
    assert accepted == case.startswith("strong")
    assert bool(observed["bytes"]) == accepted
    assert (b"synthetic-password" in observed["bytes"]) == accepted
    assert bool(failures) != accepted
    if accepted:
        assert observed["tls"] == version.name.replace("_", ".")


@pytest.mark.parametrize("level", [1, 3])
def test_policy_preserves_explicit_cipher_and_protocol_restrictions(level: int) -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.set_ciphers(f"ECDHE-RSA-AES128-GCM-SHA256:@SECLEVEL={level}")
    names = [cipher["name"] for cipher in context.get_ciphers()]
    enforce_peer_key_policy(context)
    assert [cipher["name"] for cipher in context.get_ciphers()] == names
    assert context.minimum_version == ssl.TLSVersion.TLSv1_3
    assert context.maximum_version == ssl.TLSVersion.TLSv1_3
    assert context.security_level == max(level, 2)


def test_default_trust_matches_parameterless_paho(
    chains: dict[str, tuple[Path, Path, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(chains["strong"][2]))
    baseline = paho.Client(CallbackAPIVersion.VERSION2)
    baseline.tls_set()
    original = baseline._ssl_context
    assert original is not None
    actual = mqtt_context()
    assert actual.get_ca_certs(binary_form=True) == original.get_ca_certs(binary_form=True)
    assert actual.verify_mode == original.verify_mode
    assert actual.verify_flags == original.verify_flags
    assert actual.check_hostname == original.check_hostname
    assert actual.get_ciphers() == original.get_ciphers()
