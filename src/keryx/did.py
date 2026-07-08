"""PeerID <-> did:key conversion (AgentAnycast-compatible)."""

from __future__ import annotations

import base58

_ED25519_MULTICODEC_PREFIX = bytes([0xED, 0x01])
_IDENTITY_MULTIHASH_CODE = 0x00
_PROTOBUF_ED25519_TYPE = 1


def peer_id_to_did_key(peer_id: str) -> str:
    raw = base58.b58decode(peer_id)
    if len(raw) < 2 or raw[0] != _IDENTITY_MULTIHASH_CODE:
        raise ValueError(f"unsupported PeerID format (expected identity multihash): {peer_id}")
    length = raw[1]
    if len(raw) != 2 + length:
        raise ValueError("invalid PeerID identity multihash length")
    proto_bytes = raw[2:]
    pubkey = _parse_libp2p_pubkey_proto(proto_bytes)
    mc_bytes = _ED25519_MULTICODEC_PREFIX + pubkey
    return "did:key:z" + str(base58.b58encode(mc_bytes).decode("ascii"))


def _parse_libp2p_pubkey_proto(data: bytes) -> bytes:
    idx = 0
    key_type = None
    key_data = None
    while idx < len(data):
        tag = data[idx]
        idx += 1
        field_number = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:
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
        elif wire_type == 2:
            if idx >= len(data):
                raise ValueError("truncated protobuf length-delimited field")
            length = data[idx]
            idx += 1
            end = idx + length
            if end > len(data):
                raise ValueError("truncated protobuf length-delimited field")
            if field_number == 2:
                key_data = data[idx:end]
            idx = end
    if key_type != _PROTOBUF_ED25519_TYPE:
        raise ValueError(f"unsupported key type {key_type} (expected Ed25519=1)")
    if key_data is None or len(key_data) != 32:
        raise ValueError("invalid Ed25519 public key data")
    return key_data