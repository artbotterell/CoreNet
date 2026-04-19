"""Tests for routing decisions in bridge/router.py.

Verifies:
  - Local DMs pass through to the radio unchanged
  - Remote DMs are intercepted and forwarded via LXMF
  - Inbound LXMF text messages are synthesised as ContactMsgRecvV3 push frames
  - Inbound LXMF channel messages become ChannelMsgRecvV3 push frames
  - Radio push frames are forwarded to the app unchanged
"""
from __future__ import annotations

import pytest

from bridge.companion.protocol import pack_send_txt_msg
from bridge.companion.types import CommandType, PacketType
from bridge.lxmf_layer.transport import FIELD_APP_DATA, FIELD_TEXT
from tests.conftest import LOCAL_HASH, REMOTE_HASH, REMOTE_PREFIX, LOCAL_PREFIX


class TestLocalDmPassthrough:
    async def test_local_dm_sent_to_radio(self, router, radio, lxmf):
        payload = pack_send_txt_msg(LOCAL_PREFIX, "hello local")
        await router.handle_app_command(payload)

        cmd = await radio.next_command()
        assert cmd == payload

    async def test_local_dm_not_sent_to_lxmf(self, router, radio, lxmf):
        payload = pack_send_txt_msg(LOCAL_PREFIX, "hello local")
        await router.handle_app_command(payload)
        await radio.next_command()   # consume it
        lxmf.assert_sent_count(0)


class TestRemoteDmRouting:
    async def test_remote_dm_sent_to_lxmf(self, router, radio, lxmf):
        payload = pack_send_txt_msg(REMOTE_PREFIX, "hello remote")
        await router.handle_app_command(payload)

        lxmf.assert_sent_count(1)
        lxmf.assert_last_sent(dest_contains=REMOTE_HASH, text="hello remote")

    async def test_remote_dm_not_forwarded_to_radio(self, router, radio, lxmf):
        payload = pack_send_txt_msg(REMOTE_PREFIX, "hello remote")
        await router.handle_app_command(payload)
        radio.assert_no_pending_commands()

    async def test_remote_dm_transport_is_propagated(self, router, lxmf):
        from bridge.companion.types import LxmfTransport
        payload = pack_send_txt_msg(REMOTE_PREFIX, "test")
        await router.handle_app_command(payload)
        lxmf.assert_last_sent(transport=LxmfTransport.PROPAGATED)

    async def test_unknown_prefix_falls_through_to_radio(self, router, radio, lxmf):
        unknown_prefix = bytes.fromhex("ffeeddccbbaa")
        payload = pack_send_txt_msg(unknown_prefix, "to unknown")
        await router.handle_app_command(payload)
        # Falls through to radio since prefix is not in registry
        cmd = await radio.next_command()
        assert cmd[0] == CommandType.SEND_TXT_MSG


class TestNonDmCommandsPassThrough:
    async def test_app_start_passes_to_radio(self, router, radio):
        payload = bytes([CommandType.APP_START])
        await router.handle_app_command(payload)
        cmd = await radio.next_command()
        assert cmd[0] == CommandType.APP_START

    async def test_sync_next_message_passes_to_radio(self, router, radio):
        payload = bytes([CommandType.SYNC_NEXT_MESSAGE])
        await router.handle_app_command(payload)
        cmd = await radio.next_command()
        assert cmd[0] == CommandType.SYNC_NEXT_MESSAGE

    async def test_empty_payload_ignored(self, router, radio):
        await router.handle_app_command(b"")
        radio.assert_no_pending_commands()


class TestRadioPushForwarding:
    async def test_advertisement_pushed_to_app(self, router, app):
        adv_payload = (
            bytes.fromhex("aabbccddeeff")   # prefix
            + b"KD6O\x00" + b"\x00" * 27   # name padded to 32
        )
        await router.handle_radio_push(PacketType.ADVERTISEMENT, adv_payload)
        frame = await app.next_frame()
        assert frame[0] == PacketType.ADVERTISEMENT

    async def test_messages_waiting_pushed_to_app(self, router, app):
        await router.handle_radio_push(PacketType.MESSAGES_WAITING, b"")
        frame = await app.next_frame()
        assert frame[0] == PacketType.MESSAGES_WAITING

    async def test_push_payload_intact(self, router, app):
        payload = b"\x42\x43\x44"
        await router.handle_radio_push(PacketType.RAW_DATA, payload)
        frame = await app.next_frame()
        assert frame[1:] == payload


class TestLxmfInboundSynthesis:
    async def test_inbound_text_becomes_contact_push(self, router, lxmf, app):
        await lxmf.inject_text(
            "Hi from remote",
            source="aabbccddeeff",
            app_data={
                "sender_prefix": "aabbccddeeff",
                "ts": 1_700_000_000,
                "path_len": 1,
                "snr": -10.0,
            },
        )
        frame = await app.next_frame()
        assert frame[0] == PacketType.CONTACT_MSG_RECV_V3

    async def test_inbound_contact_push_contains_text(self, router, lxmf, app):
        from bridge.companion.protocol import ContactMessage
        text = "test message content"
        await lxmf.inject_text(
            text,
            source="aabbccddeeff",
            app_data={
                "sender_prefix": "aabbccddeeff",
                "ts": 1_700_000_001,
                "path_len": 0,
            },
        )
        frame = await app.next_frame()
        # Parse the v3 payload (skip the pkt_type byte)
        parsed = ContactMessage.unpack_v3(frame[1:])
        assert parsed.text == text

    async def test_inbound_channel_msg_becomes_channel_push(self, router, lxmf, app):
        await lxmf.inject_channel_text("Channel announcement", ch_idx=2)
        frame = await app.next_frame()
        assert frame[0] == PacketType.CHANNEL_MSG_RECV_V3

    async def test_inbound_channel_push_has_correct_index(self, router, lxmf, app):
        from bridge.companion.protocol import ChannelMessage
        await lxmf.inject_channel_text("test", ch_idx=3)
        frame = await app.next_frame()
        parsed = ChannelMessage.unpack_v3(frame[1:])
        assert parsed.channel_idx == 3
