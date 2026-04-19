"""MeshCore → LXMF encoding table (executable form of meshcore-lxmf-encoding.md).

Each public function takes a parsed MeshCore message and returns an LxmfMessage
(or None for bridge-internal types that have no wire encoding).  The router
calls these; tests assert against the returned LxmfMessage.
"""
from __future__ import annotations

import time

from bridge.companion.protocol import (
    Advertisement,
    ChannelMessage,
    ContactMessage,
    ContactRecord,
)
from bridge.companion.types import LxmfDestType, LxmfTransport
from bridge.lxmf_layer.transport import (
    FIELD_APP_DATA,
    FIELD_RAW_BINARY,
    FIELD_TEXT,
    LxmfMessage,
)


def _node(h: str) -> str:
    return f"meshcore.node.{h}"


def _bridge(h: str) -> str:
    return f"meshcore.bridge.{h}"


def _channel(h: str) -> str:
    return f"meshcore.channel.{h}"


# ---------------------------------------------------------------------------
# Text messaging
# ---------------------------------------------------------------------------

def encode_contact_msg_v3(msg: ContactMessage, local_hash: str) -> LxmfMessage:
    """ContactMsgRecvV3 → propagated LXMF to meshcore.node.<local_node>."""
    return LxmfMessage(
        transport=LxmfTransport.PROPAGATED,
        dest_type=LxmfDestType.NODE,
        destination=_node(local_hash),
        fields={
            FIELD_TEXT: msg.text,
            FIELD_APP_DATA: {
                "sender_prefix": msg.sender_prefix.hex(),
                "path_len": msg.path_len,
                "ts": msg.sender_timestamp,
                "snr": msg.snr,
            },
        },
    )


def encode_contact_msg_v2(msg: ContactMessage, local_hash: str) -> LxmfMessage:
    """ContactMsgRecv (v2) — same transport, snr absent."""
    lxmf = encode_contact_msg_v3(msg, local_hash)
    lxmf.fields[FIELD_APP_DATA].pop("snr", None)
    return lxmf


def encode_channel_msg_v3(msg: ChannelMessage, channel_hash: str) -> LxmfMessage:
    """ChannelMsgRecvV3 → propagated LXMF to meshcore.channel.<hash>."""
    return LxmfMessage(
        transport=LxmfTransport.PROPAGATED,
        dest_type=LxmfDestType.CHANNEL,
        destination=_channel(channel_hash),
        fields={
            FIELD_TEXT: msg.text,
            FIELD_APP_DATA: {
                "ch_idx": msg.channel_idx,
                "path_len": msg.path_len,
                "ts": msg.sender_timestamp,
                "snr": msg.snr,
            },
        },
    )


def encode_channel_msg_v2(msg: ChannelMessage, channel_hash: str) -> LxmfMessage:
    lxmf = encode_channel_msg_v3(msg, channel_hash)
    lxmf.fields[FIELD_APP_DATA].pop("snr", None)
    return lxmf


# ---------------------------------------------------------------------------
# Advertisements
# ---------------------------------------------------------------------------

def encode_advertisement(adv: Advertisement, opt_in_flags: int = 0x00) -> LxmfMessage:
    """Advertisement / PushCodeNewAdvert → Reticulum announce."""
    announce_data = {
        "display_name": adv.name,
        "lat_udeg": adv.lat,
        "lon_udeg": adv.lon,
        "opt_in_flags": opt_in_flags,
    }
    return LxmfMessage(
        transport=LxmfTransport.ANNOUNCE,
        dest_type=LxmfDestType.NODE,
        destination=_node(adv.prefix.hex()),
        fields={FIELD_APP_DATA: announce_data},
    )


def encode_advert_response(
    tag: bytes,
    pubkey: bytes,
    node_type: int,
    display_name: str,
    lat: int,
    lon: int,
    requester_hash: str,
) -> LxmfMessage:
    """AdvertResponse → direct LXMF reply to requester."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(requester_hash),
        fields={
            FIELD_APP_DATA: {
                "tag": tag.hex(),
                "pubkey": pubkey.hex(),
                "node_type": node_type,
                "display_name": display_name,
                "lat_udeg": lat,
                "lon_udeg": lon,
            }
        },
    )


# ---------------------------------------------------------------------------
# Contact management
# ---------------------------------------------------------------------------

def encode_contact_record(c: ContactRecord, requester_hash: str) -> LxmfMessage:
    """Single Contact record (0x03) in a manifest response sequence."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(requester_hash),
        fields={
            FIELD_APP_DATA: {
                "mc_type": 0x03,
                "pubkey": c.public_key.hex(),
                "display_name": c.adv_name,
                "flags": c.flags,
                "path_len": c.path_len,
                "lat_udeg": c.adv_lat,
                "lon_udeg": c.adv_lon,
                "last_seen": c.last_advert,
            }
        },
    )


def encode_get_contacts_request(
    gateway_hash: str, region_tag: str = "", since_ts: int = 0
) -> LxmfMessage:
    """CMD_GET_CONTACTS → direct request to meshcore.bridge."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.BRIDGE,
        destination=_bridge(gateway_hash),
        fields={
            FIELD_APP_DATA: {
                "request": "contacts",
                "region_tag": region_tag,
                "since_ts": since_ts,
            }
        },
    )


def encode_contact_uri(uri: str, recipient_hash: str) -> LxmfMessage:
    """ContactUri → direct LXMF with plain-text URI."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(recipient_hash),
        fields={FIELD_TEXT: uri},
    )


# ---------------------------------------------------------------------------
# Device status / telemetry
# ---------------------------------------------------------------------------

def encode_status_response(status: dict, requester_hash: str) -> LxmfMessage:
    """StatusResponse → direct LXMF with status dict."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(requester_hash),
        fields={FIELD_APP_DATA: status},
    )


def encode_telemetry_response(lpp_bytes: bytes, requester_hash: str) -> LxmfMessage:
    """TelemetryResponse → direct LXMF; LPP bytes in f[FC], length in f[FB]."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(requester_hash),
        fields={
            FIELD_RAW_BINARY: lpp_bytes,
            FIELD_APP_DATA: {"lpp_len": len(lpp_bytes)},
        },
    )


def encode_keepalive(gateway_hash: str) -> LxmfMessage:
    """BinaryReqType::KeepAlive → direct heartbeat to bridge."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.BRIDGE,
        destination=_bridge(gateway_hash),
        fields={FIELD_APP_DATA: {"request": "keepalive", "ts": int(time.time())}},
    )


# ---------------------------------------------------------------------------
# Path & diagnostics
# ---------------------------------------------------------------------------

def encode_path_update(
    node_prefix: bytes, path_len: int, path_bytes: bytes, gateway_hash: str
) -> LxmfMessage:
    """PathUpdate → direct to meshcore.bridge."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.BRIDGE,
        destination=_bridge(gateway_hash),
        fields={
            FIELD_APP_DATA: {
                "mc_type": 0x81,
                "node_prefix": node_prefix.hex(),
                "path_len": path_len,
                "path_bytes": path_bytes.hex(),
            }
        },
    )


def encode_trace_data(hops: list[dict], requester_hash: str) -> LxmfMessage:
    """TraceData → direct with hop list [{prefix, snr_db}]."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(requester_hash),
        fields={FIELD_APP_DATA: {"hops": hops}},
    )


# ---------------------------------------------------------------------------
# Signatures / crypto
# ---------------------------------------------------------------------------

def encode_signature(sig_bytes: bytes, signed_hash: bytes, recipient_hash: str) -> LxmfMessage:
    """Signature → direct with Ed25519 sig bytes in f[FC]."""
    return LxmfMessage(
        transport=LxmfTransport.DIRECT,
        dest_type=LxmfDestType.NODE,
        destination=_node(recipient_hash),
        fields={
            FIELD_RAW_BINARY: sig_bytes,
            FIELD_APP_DATA: {"signed_hash": signed_hash.hex()},
        },
    )


# ---------------------------------------------------------------------------
# Lookup table: PacketType → encoder metadata
# Used by the router to decide how to handle each type without a big if-chain.
# ---------------------------------------------------------------------------

from bridge.companion.types import PacketType  # noqa: E402 (avoid circular at module level)


ENCODING_TABLE: dict[PacketType, tuple[LxmfTransport, LxmfDestType]] = {
    # Text messaging
    PacketType.CONTACT_MSG_RECV:     (LxmfTransport.PROPAGATED, LxmfDestType.NODE),
    PacketType.CONTACT_MSG_RECV_V3:  (LxmfTransport.PROPAGATED, LxmfDestType.NODE),
    PacketType.CHANNEL_MSG_RECV:     (LxmfTransport.PROPAGATED, LxmfDestType.CHANNEL),
    PacketType.CHANNEL_MSG_RECV_V3:  (LxmfTransport.PROPAGATED, LxmfDestType.CHANNEL),
    PacketType.MSG_SENT:             (LxmfTransport.RECEIPT,    LxmfDestType.NODE),
    PacketType.ACK:                  (LxmfTransport.RECEIPT,    LxmfDestType.NODE),
    PacketType.MESSAGES_WAITING:     (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
    PacketType.NO_MORE_MSGS:         (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
    # Advertisements
    PacketType.ADVERTISEMENT:        (LxmfTransport.ANNOUNCE,   LxmfDestType.NODE),
    PacketType.PUSH_CODE_NEW_ADVERT: (LxmfTransport.ANNOUNCE,   LxmfDestType.NODE),
    PacketType.ADVERT_RESPONSE:      (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    # Contacts
    PacketType.CONTACT_START:        (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.CONTACT:              (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.CONTACT_END:          (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.CONTACT_URI:          (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    # Device info / status
    PacketType.SELF_INFO:            (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.DEVICE_INFO:          (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.BATTERY:              (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.STATUS_RESPONSE:      (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.STATS:                (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.TELEMETRY_RESPONSE:   (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    # Path / diagnostics
    PacketType.PATH_UPDATE:          (LxmfTransport.DIRECT,     LxmfDestType.BRIDGE),
    PacketType.PATH_DISCOVERY:       (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.PATH_DISCOVERY_RESP:  (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.TRACE_DATA:           (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.LOG_DATA:             (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.BINARY_RESPONSE:      (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    # Crypto
    PacketType.SIGNATURE:            (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    # Raw / control
    PacketType.RAW_DATA:             (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.CONTROL_DATA:         (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.SEND_CONTROL_DATA:    (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.DISABLED:             (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.ERROR:                (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    # Bridge-internal — no wire encoding
    PacketType.OK:                   (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
    PacketType.CONTACT_START:        (LxmfTransport.DIRECT,     LxmfDestType.NODE),
    PacketType.PRIVATE_KEY:          (LxmfTransport.INTERNAL,   LxmfDestType.NODE),  # NEVER relay
    PacketType.CHANNEL_INFO:         (LxmfTransport.INTERNAL,   LxmfDestType.NODE),  # secret — local only
    PacketType.LOGIN_SUCCESS:        (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
    PacketType.LOGIN_FAILED:         (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
    PacketType.FACTORY_RESET:        (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
    PacketType.UNKNOWN:              (LxmfTransport.INTERNAL,   LxmfDestType.NODE),
}
