"""Bidirectional conversion between libp2p PeerIDs and W3C DID identifiers.

The did:key method encodes an Ed25519 public key as::

    did:key:z<base58btc(multicodec_prefix + raw_public_key)>

where the multicodec prefix for Ed25519 is ``0xed01`` (varint-encoded 0xed).

This module also provides helpers for the ``did:web`` method, which maps
a DID to an HTTPS URL hosting the DID document.

Pure-Python implementations that produce identical output to the Go
daemon's ``crypto.PeerIDToDIDKey`` / ``DIDKeyToPeerID``.
"""

from __future__ import annotations

from urllib.parse import quote as _pct_encode
from urllib.parse import unquote as _pct_decode

import base58

# Ed25519 multicodec varint prefix.
_ED25519_MULTICODEC_PREFIX = bytes([0xED, 0x01])

# libp2p identity multihash code (used for Ed25519 PeerIDs).
_IDENTITY_MULTIHASH_CODE = 0x00

# Protobuf field tag for Ed25519 public key in libp2p's crypto.pb.
# PeerID = multihash(identity, protobuf(type=Ed25519, data=pubkey))
_PROTOBUF_ED25519_TYPE = 1
_PROTOBUF_DATA_FIELD = 2


def peer_id_to_did_key(peer_id: str) -> str:
    """Convert a libp2p PeerID (base58btc-encoded) to a ``did:key`` string.

    Only Ed25519-based PeerIDs are supported. These are encoded with the
    identity multihash and directly embed the public key.

    Args:
        peer_id: Base58btc-encoded libp2p PeerID (e.g., ``12D3KooW...``).

    Returns:
        A ``did:key:z...`` string.

    Raises:
        ValueError: If the PeerID is not a valid Ed25519-based identity.
    """
    raw = base58.b58decode(peer_id)

    # libp2p PeerIDs for Ed25519 use identity multihash:
    # <varint:0x00> <varint:length> <protobuf-encoded-public-key>
    if len(raw) < 2 or raw[0] != _IDENTITY_MULTIHASH_CODE:
        raise ValueError(f"unsupported PeerID format (expected identity multihash): {peer_id}")

    # Read varint length (single byte is safe: Ed25519 protobuf is 36 bytes, always < 128).
    length = raw[1]
    proto_bytes = raw[2 : 2 + length]

    # Parse the minimal protobuf: field 1 (type) = Ed25519 (1), field 2 (data) = raw key.
    pubkey = _parse_libp2p_pubkey_proto(proto_bytes)

    # Encode as did:key.
    mc_bytes = _ED25519_MULTICODEC_PREFIX + pubkey
    return "did:key:z" + str(base58.b58encode(mc_bytes).decode("ascii"))


def did_key_to_peer_id(did_key: str) -> str:
    """Convert a ``did:key`` string back to a libp2p PeerID.

    Args:
        did_key: A ``did:key:z...`` string (Ed25519 only).

    Returns:
        Base58btc-encoded libp2p PeerID.

    Raises:
        ValueError: If the did:key is malformed or uses an unsupported key type.
    """
    if not did_key.startswith("did:key:z"):
        raise ValueError(f"invalid did:key format: {did_key}")

    encoded = did_key[len("did:key:z") :]
    decoded = base58.b58decode(encoded)

    if len(decoded) < len(_ED25519_MULTICODEC_PREFIX) + 32:
        raise ValueError("did:key payload too short")

    prefix = decoded[: len(_ED25519_MULTICODEC_PREFIX)]
    if prefix != _ED25519_MULTICODEC_PREFIX:
        raise ValueError("unsupported multicodec prefix (only Ed25519 supported)")

    pubkey = decoded[len(_ED25519_MULTICODEC_PREFIX) :]

    # Reconstruct the libp2p protobuf-encoded public key.
    proto_bytes = _encode_libp2p_pubkey_proto(pubkey)

    # Wrap in identity multihash: <0x00> <length> <data>
    mh = bytes([_IDENTITY_MULTIHASH_CODE, len(proto_bytes)]) + proto_bytes
    return str(base58.b58encode(mh).decode("ascii"))


def _parse_libp2p_pubkey_proto(data: bytes) -> bytes:
    """Parse a minimal libp2p crypto.pb.PublicKey protobuf to extract the raw key."""
    # Field 1 (KeyType): varint, should be 1 (Ed25519)
    # Field 2 (Data): length-delimited, the raw public key bytes
    idx = 0
    key_type = None
    key_data = None

    while idx < len(data):
        # Read field tag.
        tag = data[idx]
        idx += 1
        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:  # varint
            val = 0
            shift = 0
            while idx < len(data):
                b = data[idx]
                idx += 1
                val |= (b & 0x7F) << shift
                if b < 0x80:
                    break
                shift += 7
            if field_number == 1:
                key_type = val
        elif wire_type == 2:  # length-delimited
            length = data[idx]
            idx += 1
            if field_number == 2:
                key_data = data[idx : idx + length]
            idx += length

    if key_type != _PROTOBUF_ED25519_TYPE:
        raise ValueError(f"unsupported key type {key_type} (expected Ed25519=1)")
    if key_data is None or len(key_data) != 32:
        raise ValueError("invalid Ed25519 public key data")

    return key_data


def _encode_libp2p_pubkey_proto(pubkey: bytes) -> bytes:
    """Encode a raw Ed25519 public key as libp2p crypto.pb.PublicKey protobuf."""
    # Field 1 (KeyType=Ed25519=1): tag=0x08, value=0x01
    # Field 2 (Data): tag=0x12, length, data
    return bytes([0x08, 0x01, 0x12, len(pubkey)]) + pubkey


# ── did:web helpers ──────────────────────────────────────────────────


def did_web_to_url(did_web: str) -> str:
    """Convert a ``did:web`` identifier to its HTTPS resolution URL.

    Follows the `did:web Method Specification
    <https://w3c-ccg.github.io/did-method-web/>`_:

    * ``did:web:example.com`` → ``https://example.com/.well-known/did.json``
    * ``did:web:example.com:agents:myagent`` →
      ``https://example.com/agents/myagent/did.json``

    Percent-encoded characters in the DID are decoded for the URL path.

    Args:
        did_web: A ``did:web:...`` string.

    Returns:
        The HTTPS URL where the DID document should be hosted.

    Raises:
        ValueError: If *did_web* does not start with ``did:web:``.
    """
    if not did_web.startswith("did:web:"):
        raise ValueError(f"invalid did:web format: {did_web}")

    # Everything after "did:web:" is colon-separated path segments.
    specific_id = did_web[len("did:web:") :]
    parts = specific_id.split(":")

    # First segment is the domain (percent-decoded).
    domain = _pct_decode(parts[0])

    if len(parts) == 1:
        # Domain-only → /.well-known/did.json
        return f"https://{domain}/.well-known/did.json"

    # Additional segments form the path, each percent-decoded.
    path = "/".join(_pct_decode(p) for p in parts[1:])
    return f"https://{domain}/{path}/did.json"


def url_to_did_web(url: str) -> str:
    """Convert an HTTPS URL to a ``did:web`` identifier.

    Reverse of :func:`did_web_to_url`. The URL must use ``https://`` and
    the path must end with ``did.json`` (either at ``/.well-known/did.json``
    for domain-only DIDs or at ``<path>/did.json`` for path-based DIDs).

    Args:
        url: An HTTPS URL pointing to a DID document.

    Returns:
        The corresponding ``did:web:...`` string.

    Raises:
        ValueError: If the URL is not a valid ``did:web`` resolution URL.
    """
    if not url.startswith("https://"):
        raise ValueError(f"did:web URLs must use HTTPS: {url}")

    # Strip scheme.
    rest = url[len("https://") :]

    # Split domain and path.
    slash_idx = rest.find("/")
    if slash_idx == -1:
        raise ValueError(f"URL missing path component: {url}")

    domain = rest[:slash_idx]
    path = rest[slash_idx + 1 :]

    # Percent-encode the domain (colons in port become %3A).
    encoded_domain = _pct_encode(domain, safe="")

    if path == ".well-known/did.json":
        # Domain-only DID.
        return f"did:web:{encoded_domain}"

    if not path.endswith("/did.json"):
        raise ValueError(f"URL path must end with /did.json: {url}")

    # Strip trailing /did.json, split into segments.
    path_part = path[: -len("/did.json")]
    segments = path_part.split("/")
    encoded_segments = [_pct_encode(s, safe="") for s in segments]

    return f"did:web:{encoded_domain}:" + ":".join(encoded_segments)
