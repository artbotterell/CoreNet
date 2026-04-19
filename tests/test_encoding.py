"""Tests for the MeshCore → LXMF encoding table (bridge/lxmf_layer/encoding.py).

Each test verifies that a given MeshCore message type produces an LxmfMessage
with the correct transport mode, destination scheme, and field content.
"""
from __future__ import annotations

import time

import pytest

from bridge.companion.protocol import (
    Advertisement,
    ChannelMessage,
    ContactMessage,
    ContactRecord,
)
from bridge.companion.types import LxmfDestType, LxmfTransport, PacketType
from bridge.lxmf_layer import encoding as enc
from bridge.lxmf_layer.transport import FIELD_APP_DATA, FIELD_RAW_BINARY, FIELD_TEXT


class TestContactMessageEncoding:
    def _make_contact_msg(self, snr: float | None = -12.5) -> ContactMessage:
        return ContactMessage(
            sender_prefix=bytes.fromhex("aabbccddeeff"),
            path_len=2,
            txt_type=1,
            sender_timestamp=1_700_000_000,
            text="Hello via CoreNet",
            snr=snr,
        )

    def test_v3_transport_is_propagated(self):
        msg = enc.encode_contact_msg_v3(self._make_contact_msg(), "local_hash")
        assert msg.transport == LxmfTransport.PROPAGATED

    def test_v3_destination_is_local_node(self):
        msg = enc.encode_contact_msg_v3(self._make_contact_msg(), "local_hash")
        assert msg.destination == "meshcore.node.local_hash"

    def test_v3_text_field_present(self):
        msg = enc.encode_contact_msg_v3(self._make_contact_msg(), "local_hash")
        assert msg.text == "Hello via CoreNet"

    def test_v3_app_data_has_snr(self):
        msg = enc.encode_contact_msg_v3(self._make_contact_msg(snr=-12.5), "local_hash")
        assert msg.app_data["snr"] == pytest.approx(-12.5)

    def test_v2_has_no_snr(self):
        msg = enc.encode_contact_msg_v2(self._make_contact_msg(snr=None), "local_hash")
        assert "snr" not in msg.app_data

    def test_app_data_has_sender_prefix_hex(self):
        msg = enc.encode_contact_msg_v3(self._make_contact_msg(), "local_hash")
        assert msg.app_data["sender_prefix"] == "aabbccddeeff"

    def test_app_data_has_ts(self):
        msg = enc.encode_contact_msg_v3(self._make_contact_msg(), "local_hash")
        assert msg.app_data["ts"] == 1_700_000_000


class TestChannelMessageEncoding:
    def _make_channel_msg(self) -> ChannelMessage:
        return ChannelMessage(
            channel_idx=1,
            path_len=1,
            txt_type=1,
            sender_timestamp=1_700_000_001,
            text="Broadcast to channel",
            snr=-8.0,
        )

    def test_transport_is_propagated(self):
        msg = enc.encode_channel_msg_v3(self._make_channel_msg(), "ch_hash")
        assert msg.transport == LxmfTransport.PROPAGATED

    def test_destination_is_channel(self):
        msg = enc.encode_channel_msg_v3(self._make_channel_msg(), "ch_hash")
        assert msg.destination == "meshcore.channel.ch_hash"

    def test_channel_idx_in_app_data(self):
        msg = enc.encode_channel_msg_v3(self._make_channel_msg(), "ch_hash")
        assert msg.app_data["ch_idx"] == 1

    def test_v2_no_snr(self):
        msg = enc.encode_channel_msg_v2(self._make_channel_msg(), "ch_hash")
        assert "snr" not in msg.app_data


class TestAdvertisementEncoding:
    def _make_advert(self) -> Advertisement:
        return Advertisement(
            prefix=bytes.fromhex("112233445566"),
            name="KD6O-Node",
            lat=37_774_000,
            lon=-122_431_000,
        )

    def test_transport_is_announce(self):
        msg = enc.encode_advertisement(self._make_advert())
        assert msg.transport == LxmfTransport.ANNOUNCE

    def test_destination_is_node(self):
        msg = enc.encode_advertisement(self._make_advert())
        assert msg.destination == "meshcore.node.112233445566"

    def test_display_name_in_app_data(self):
        msg = enc.encode_advertisement(self._make_advert())
        assert msg.app_data["display_name"] == "KD6O-Node"

    def test_coordinates_in_app_data(self):
        msg = enc.encode_advertisement(self._make_advert())
        assert msg.app_data["lat_udeg"] == 37_774_000
        assert msg.app_data["lon_udeg"] == -122_431_000

    def test_opt_in_flags_default_zero(self):
        msg = enc.encode_advertisement(self._make_advert())
        assert msg.app_data["opt_in_flags"] == 0x00


class TestContactRecordEncoding:
    def _make_contact(self) -> ContactRecord:
        return ContactRecord(
            public_key=bytes(32),
            contact_type=1,
            flags=0,
            path_len=2,
            out_path=b"",
            adv_name="Peer-A",
            last_advert=1_700_000_000,
            adv_lat=37_000_000,
            adv_lon=-120_000_000,
        )

    def test_transport_is_direct(self):
        msg = enc.encode_contact_record(self._make_contact(), "requester_hash")
        assert msg.transport == LxmfTransport.DIRECT

    def test_destination_is_requester(self):
        msg = enc.encode_contact_record(self._make_contact(), "requester_hash")
        assert msg.destination == "meshcore.node.requester_hash"

    def test_mc_type_field(self):
        msg = enc.encode_contact_record(self._make_contact(), "requester_hash")
        assert msg.app_data["mc_type"] == 0x03


class TestTelemetryEncoding:
    def test_lpp_in_raw_binary(self):
        lpp = b"\x01\x02\x03\x04"
        msg = enc.encode_telemetry_response(lpp, "requester")
        assert msg.raw_binary == lpp

    def test_lpp_length_in_app_data(self):
        lpp = b"\x00" * 20
        msg = enc.encode_telemetry_response(lpp, "requester")
        assert msg.app_data["lpp_len"] == 20

    def test_transport_is_direct(self):
        msg = enc.encode_telemetry_response(b"\x00", "requester")
        assert msg.transport == LxmfTransport.DIRECT


class TestPathEncoding:
    def test_path_update_goes_to_bridge(self):
        msg = enc.encode_path_update(b"\xAA\xBB\xCC\xDD\xEE\xFF", 3, b"\x01\x02\x03", "gw_hash")
        assert msg.dest_type == LxmfDestType.BRIDGE
        assert msg.destination == "meshcore.bridge.gw_hash"

    def test_path_update_has_mc_type(self):
        msg = enc.encode_path_update(b"\x00" * 6, 1, b"", "gw")
        assert msg.app_data["mc_type"] == 0x81


class TestEncodingTable:
    """Verify every PacketType in ENCODING_TABLE has a consistent mapping."""

    def test_private_key_is_always_internal(self):
        transport, _ = enc.ENCODING_TABLE[PacketType.PRIVATE_KEY]
        assert transport == LxmfTransport.INTERNAL, (
            "PrivateKey must never be relayed over Reticulum"
        )

    def test_channel_info_is_always_internal(self):
        transport, _ = enc.ENCODING_TABLE[PacketType.CHANNEL_INFO]
        assert transport == LxmfTransport.INTERNAL, (
            "ChannelInfo (contains secret) must not transit Reticulum"
        )

    def test_advertisement_is_announce(self):
        transport, _ = enc.ENCODING_TABLE[PacketType.ADVERTISEMENT]
        assert transport == LxmfTransport.ANNOUNCE

    def test_contact_msg_v3_is_propagated(self):
        transport, _ = enc.ENCODING_TABLE[PacketType.CONTACT_MSG_RECV_V3]
        assert transport == LxmfTransport.PROPAGATED

    def test_channel_msg_v3_goes_to_channel(self):
        _, dest = enc.ENCODING_TABLE[PacketType.CHANNEL_MSG_RECV_V3]
        assert dest == LxmfDestType.CHANNEL

    def test_no_internal_type_has_non_node_dest(self):
        """Internal types should not claim a non-NODE destination."""
        for ptype, (transport, dest) in enc.ENCODING_TABLE.items():
            if transport == LxmfTransport.INTERNAL:
                assert dest == LxmfDestType.NODE, (
                    f"{ptype.name} is INTERNAL but has dest {dest.name}"
                )
