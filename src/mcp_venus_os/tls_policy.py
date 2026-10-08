# SPDX-License-Identifier: MIT
# Copyright (c) 2026 victron-venus
# Adapted from the reviewed inverter-dashboard / fastapi-mqtt-gateway TLS policy.
"""Check exact peer keys on Paho's verified socket before MQTT application bytes."""

import ssl

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa


def _certificate_key_ok(der: bytes) -> bool:
    try:
        key = x509.load_der_x509_certificate(der).public_key()
    except (ValueError, UnsupportedAlgorithm):
        message = "TLS certificate uses an unsupported public key"
        raise ssl.SSLError(message) from None
    if isinstance(key, rsa.RSAPublicKey):
        return key.public_numbers().n.bit_length() >= 2048
    if isinstance(key, ec.EllipticCurvePublicKey):
        return key.key_size >= 224
    if isinstance(key, dsa.DSAPublicKey):
        parameters = key.public_numbers().parameter_numbers
        return parameters.p.bit_length() >= 2048 and parameters.q.bit_length() >= 224
    return isinstance(key, ed25519.Ed25519PublicKey | ed448.Ed448PublicKey)


def _certificate_der(item: object) -> bytes:
    if isinstance(item, bytes):
        return item
    encode = getattr(item, "public_bytes", None)
    pem = encode() if callable(encode) else None
    if not isinstance(pem, str):
        message = "TLS runtime returned an unsupported certificate format"
        raise ssl.SSLError(message)
    return ssl.PEM_cert_to_DER_cert(pem)


def _check_verified_keys(connection: ssl.SSLSocket) -> None:
    get_chain = getattr(connection, "get_verified_chain", None)
    if not callable(get_chain):
        # CPython 3.11/3.12 expose this through the socket's internal SSL object.
        get_chain = getattr(getattr(connection, "_sslobj", None), "get_verified_chain", None)
    if not callable(get_chain):
        message = "TLS runtime does not expose its verified certificate chain"
        raise ssl.SSLError(message)
    chain = get_chain()
    if not isinstance(chain, list) or not chain:
        message = "TLS peer has no verified certificate chain"
        raise ssl.SSLError(message)
    for item in chain:
        der = _certificate_der(item)
        if not _certificate_key_ok(der):
            message = "TLS certificate key is below the supported security minimum"
            raise ssl.SSLError(message)


class _VerifiedSocket(ssl.SSLSocket):
    def do_handshake(self, block: bool = False) -> None:
        super().do_handshake(block)
        try:
            _check_verified_keys(self)
        except Exception:
            self.close()
            raise


def enforce_peer_key_policy(context: ssl.SSLContext) -> ssl.SSLContext:
    """Preserve trust and stricter settings on an owned client context."""
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        message = "TLS context must verify certificates and hostnames"
        raise ValueError(message)
    context.minimum_version = max(context.minimum_version, ssl.TLSVersion.TLSv1_2)
    if context.security_level < 2:
        selected = [
            cipher["name"] for cipher in context.get_ciphers() if cipher["protocol"] != "TLSv1.3"
        ]
        context.set_ciphers(":".join([*selected, "@SECLEVEL=2"]))
    context.sslsocket_class = _VerifiedSocket
    return context


def mqtt_context() -> ssl.SSLContext:
    """Keep the default CA/hostname behavior of Paho's parameterless tls_set."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    return enforce_peer_key_policy(context)
