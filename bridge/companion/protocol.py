"""Message dataclasses and pack/unpack helpers for the MeshCore companion protocol.

Byte layouts are verified against meshcore-rs/src/parsing.rs.  All multi-byte
integers are little-endian; SNR is a signed i8 divided by 4.0 to get dBm.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Inbound messages (radio → app)
# ---------------------------------------------------------------------------

@dataclass
class ContactMessage:
    """Parsed ContactMsgRecv (v2) or ContactMsgRecvV3 payload.

    v2 layout: sender_prefix[6] path_len[1] txt_type[1] ts[4u32le]
               [sig[4] if txt_type==2] text[...]
    v3 layout: snr[1i8] reserved[2] sender_prefix[6] path_len[1] txt_type[1]
               ts[4u32le] [sig[4] if txt_type==2] text[...]
    """
    sender_prefix: bytes        # 6 bytes
    path_len: int
    txt_type: int
    sender_timestamp: int       # Unix seconds
    text: str
    snr: float | None = None    # dBm; None for v2
    signature: bytes | None = None  # 4-byte tag if txt_type == 2

    @classmethod
    def unpack_v2(cls, data: bytes) -> "ContactMessage":
        if len(data) < 12:
            raise ValueError(f"ContactMsgRecv too short: {len(data)}")
        sender_prefix = data[0:6]
        path_len = data[6]
        txt_type = data[7]
        ts = struct.unpack_from("<I", data, 8)[0]
        sig, text_start = (data[12:16], 16) if txt_type == 2 and len(data) >= 16 else (None, 12)
        text = data[text_start:].decode("utf-8", errors="replace")
        return cls(sender_prefix, path_len, txt_type, ts, text, None, sig)

    @classmethod
    def unpack_v3(cls, data: bytes) -> "ContactMessage":
        if len(data) < 15:
            raise ValueError(f"ContactMsgRecvV3 too short: {len(data)}")
        snr = struct.unpack_from("b", data, 0)[0] / 4.0
        sender_prefix = data[3:9]
        path_len = data[9]
        txt_type = data[10]
        ts = struct.unpack_from("<I", data, 11)[0]
        sig, text_start = (data[15:19], 19) if txt_type == 2 and len(data) >= 19 else (None, 15)
        text = data[text_start:].decode("utf-8", errors="replace")
        return cls(sender_prefix, path_len, txt_type, ts, text, snr, sig)

    def pack_v3(self) -> bytes:
        """Re-serialise as v3 for injecting into a mock radio stream."""
        snr_byte = int((self.snr or 0.0) * 4) & 0xFF
        sig_bytes = self.signature if self.txt_type == 2 and self.signature else b""
        return (
            bytes([snr_byte, 0, 0])
            + self.sender_prefix
            + struct.pack("<BBI", self.path_len, self.txt_type, self.sender_timestamp)
            + sig_bytes
            + self.text.encode("utf-8")
        )


@dataclass
class ChannelMessage:
    """Parsed ChannelMsgRecv (v2) or ChannelMsgRecvV3 payload.

    v2 layout: ch_idx[1] path_len[1] txt_type[1] ts[4u32le] text[...]
    v3 layout: snr[1i8] reserved[2] ch_idx[1] path_len[1] txt_type[1]
               ts[4u32le] text[...]
    """
    channel_idx: int
    path_len: int
    txt_type: int
    sender_timestamp: int
    text: str
    snr: float | None = None

    @classmethod
    def unpack_v2(cls, data: bytes) -> "ChannelMessage":
        if len(data) < 8:
            raise ValueError(f"ChannelMsgRecv too short: {len(data)}")
        ch_idx, path_len, txt_type = data[0], data[1], data[2]
        ts = struct.unpack_from("<I", data, 3)[0]
        text = data[7:].decode("utf-8", errors="replace")
        return cls(ch_idx, path_len, txt_type, ts, text)

    @classmethod
    def unpack_v3(cls, data: bytes) -> "ChannelMessage":
        if len(data) < 11:
            raise ValueError(f"ChannelMsgRecvV3 too short: {len(data)}")
        snr = struct.unpack_from("b", data, 0)[0] / 4.0
        ch_idx, path_len, txt_type = data[3], data[4], data[5]
        ts = struct.unpack_from("<I", data, 6)[0]
        text = data[10:].decode("utf-8", errors="replace")
        return cls(ch_idx, path_len, txt_type, ts, text, snr)

    def pack_v3(self) -> bytes:
        snr_byte = int((self.snr or 0.0) * 4) & 0xFF
        return (
            bytes([snr_byte, 0, 0, self.channel_idx, self.path_len, self.txt_type])
            + struct.pack("<I", self.sender_timestamp)
            + self.text.encode("utf-8")
        )


@dataclass
class Advertisement:
    """Parsed Advertisement (0x80) or PushCodeNewAdvert (0x8A) payload.

    Layout: prefix[6] name[32 null-term] ... lat[4i32le]@38 lon[4i32le]@42
    """
    prefix: bytes       # 6 bytes
    name: str
    lat: int = 0        # microdegrees
    lon: int = 0

    @classmethod
    def unpack(cls, data: bytes) -> "Advertisement":
        if len(data) < 14:
            raise ValueError(f"Advertisement too short: {len(data)}")
        prefix = data[0:6]
        raw_name = data[6:38]
        name = raw_name.split(b"\x00")[0].decode("utf-8", errors="replace").strip()
        lat = struct.unpack_from("<i", data, 38)[0] if len(data) >= 42 else 0
        lon = struct.unpack_from("<i", data, 42)[0] if len(data) >= 46 else 0
        return cls(prefix, name, lat, lon)

    def pack(self) -> bytes:
        name_b = self.name.encode("utf-8")[:32].ljust(32, b"\x00")
        return (
            self.prefix[:6]
            + name_b
            + b"\x00" * 0           # no reserved bytes between name and coords
            + struct.pack("<ii", self.lat, self.lon)
        )


@dataclass
class ContactRecord:
    """Parsed Contact (0x03) payload — 145-149 bytes.

    Mirrors meshcore-rs parse_contact.
    """
    public_key: bytes           # 32 bytes
    contact_type: int
    flags: int
    path_len: int
    out_path: bytes             # up to 64 bytes
    adv_name: str               # up to 32 bytes
    last_advert: int
    adv_lat: int
    adv_lon: int
    last_modification_ts: int = 0

    @classmethod
    def unpack(cls, data: bytes) -> "ContactRecord":
        if len(data) < 145:
            raise ValueError(f"Contact too short: {len(data)}")
        pubkey = data[0:32]
        ctype, flags, path_len = data[32], data[33], data[34]
        out_path = data[35:99].split(b"\x00")[0]
        adv_name = data[99:131].split(b"\x00")[0].decode("utf-8", errors="replace").strip()
        last_advert = struct.unpack_from("<I", data, 131)[0]
        lat = struct.unpack_from("<i", data, 135)[0]
        lon = struct.unpack_from("<i", data, 139)[0]
        lastmod = struct.unpack_from("<I", data, 143)[0] if len(data) >= 149 else 0
        return cls(pubkey, ctype, flags, path_len, out_path, adv_name, last_advert, lat, lon, lastmod)


# ---------------------------------------------------------------------------
# Outbound commands (app → radio)
# ---------------------------------------------------------------------------

def pack_send_txt_msg(dest_prefix: bytes, text: str) -> bytes:
    """Build payload for CMD_SEND_TXT_MSG (0x02).

    Layout: cmd[1] dest_prefix[6] text[utf-8]
    """
    return bytes([0x02]) + dest_prefix[:6] + text.encode("utf-8")


def pack_send_channel_msg(channel_idx: int, text: str) -> bytes:
    """Build payload for CMD_SEND_CHANNEL_TXT_MSG (0x03).

    Layout: cmd[1] ch_idx[1] text[utf-8]
    """
    return bytes([0x03, channel_idx & 0xFF]) + text.encode("utf-8")


def pack_app_start() -> bytes:
    return bytes([0x01])


def pack_get_contacts(page: int = 0) -> bytes:
    return bytes([0x04, page & 0xFF])


def pack_sync_next_message() -> bytes:
    return bytes([0x0A])


def pack_send_self_advert() -> bytes:
    return bytes([0x07])
