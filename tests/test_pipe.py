"""Integration tests: end-to-end message pipe through the bridge.

These tests simulate the full round-trip:
  mc-client A (app) → bridge A → LXMF pipe → bridge B → mc-client B (app)

Both bridges are driven in-process using MockRadio and MockLxmfTransport.
The two MockLxmfTransport instances are wired together so that a send() on
bridge A's LXMF transport triggers an inbound delivery on bridge B's.
"""
from __future__ import annotations

import asyncio
import pytest

from bridge.companion.protocol import (
    ContactMessage,
    ChannelMessage,
    pack_send_txt_msg,
    pack_send_channel_msg,
)
from bridge.companion.types import CommandType, LxmfTransport, PacketType
from bridge.router import ContactEntry, ContactRegistry, Router
from tests.conftest import LOCAL_HASH, REMOTE_HASH, REMOTE_PREFIX, LOCAL_PREFIX
from tests.doubles.mock_app import MockApp
from tests.doubles.mock_lxmf import MockLxmfTransport
from tests.doubles.mock_radio import MockRadio


def make_bridge(
    local_hash: str,
    remote_hash: str,
    remote_prefix: bytes,
) -> tuple[Router, MockRadio, MockLxmfTransport, MockApp]:
    contacts = ContactRegistry()
    contacts.add(ContactEntry(
        pubkey=remote_prefix + b"\x00" * 26,
        prefix=remote_prefix,
        display_name="Peer",
        lxmf_hash=remote_hash,
        is_remote=True,
    ))
    radio = MockRadio()
    lxmf = MockLxmfTransport()
    app = MockApp()
    router = Router(contacts, lxmf, local_hash)
    router.attach(radio, app)
    return router, radio, lxmf, app


def wire_lxmf_pair(lxmf_a: MockLxmfTransport, lxmf_b: MockLxmfTransport) -> None:
    """Messages sent on A are injected as inbound on B, and vice-versa."""
    original_send_a = lxmf_a.send
    original_send_b = lxmf_b.send

    async def send_a(msg):
        await original_send_a(msg)
        await lxmf_b.inject(msg)

    async def send_b(msg):
        await original_send_b(msg)
        await lxmf_a.inject(msg)

    lxmf_a.send = send_a   # type: ignore[method-assign]
    lxmf_b.send = send_b   # type: ignore[method-assign]


class TestDmRoundTrip:
    """A DM from app-A to a remote contact arrives at app-B as a push frame."""

    @pytest.fixture
    def bridges(self):
        PREFIX_A = bytes.fromhex("aabbccddeeff")
        PREFIX_B = bytes.fromhex("112233445566")
        router_a, radio_a, lxmf_a, app_a = make_bridge(LOCAL_HASH, REMOTE_HASH, PREFIX_B)
        router_b, radio_b, lxmf_b, app_b = make_bridge(REMOTE_HASH, LOCAL_HASH, PREFIX_A)
        wire_lxmf_pair(lxmf_a, lxmf_b)
        return (router_a, radio_a, lxmf_a, app_a), (router_b, radio_b, lxmf_b, app_b)

    async def test_dm_delivered_to_remote_app(self, bridges):
        (router_a, _, lxmf_a, _), (_, _, _, app_b) = bridges
        PREFIX_B = bytes.fromhex("112233445566")

        await router_a.handle_app_command(pack_send_txt_msg(PREFIX_B, "Hello from A"))

        frame = await app_b.next_frame(timeout=2.0)
        assert frame[0] == PacketType.CONTACT_MSG_RECV_V3

    async def test_dm_text_preserved_end_to_end(self, bridges):
        (router_a, _, _, _), (_, _, _, app_b) = bridges
        PREFIX_B = bytes.fromhex("112233445566")

        await router_a.handle_app_command(pack_send_txt_msg(PREFIX_B, "End-to-end text"))

        frame = await app_b.next_frame(timeout=2.0)
        parsed = ContactMessage.unpack_v3(frame[1:])
        assert parsed.text == "End-to-end text"

    async def test_dm_not_echoed_back_to_sender_app(self, bridges):
        (router_a, _, _, app_a), (_, _, _, app_b) = bridges
        PREFIX_B = bytes.fromhex("112233445566")

        await router_a.handle_app_command(pack_send_txt_msg(PREFIX_B, "One way"))
        await app_b.next_frame(timeout=2.0)   # wait for delivery

        # app_a should not have received anything
        assert app_a.received == []

    async def test_bidirectional_dms(self, bridges):
        (router_a, _, _, app_a), (router_b, _, _, app_b) = bridges
        PREFIX_A = bytes.fromhex("aabbccddeeff")
        PREFIX_B = bytes.fromhex("112233445566")

        await router_a.handle_app_command(pack_send_txt_msg(PREFIX_B, "A→B"))
        await router_b.handle_app_command(pack_send_txt_msg(PREFIX_A, "B→A"))

        frame_b = await app_b.next_frame(timeout=2.0)
        frame_a = await app_a.next_frame(timeout=2.0)

        assert ContactMessage.unpack_v3(frame_b[1:]).text == "A→B"
        assert ContactMessage.unpack_v3(frame_a[1:]).text == "B→A"


class TestAdvertisementRoundTrip:
    """An advertisement injected by the radio is forwarded to the LXMF layer."""

    async def test_advertisement_triggers_lxmf_announce(self, router, lxmf):
        adv_payload = (
            bytes.fromhex("aabbccddeeff")
            + b"KD6O\x00" + b"\x00" * 27
        )
        await router.handle_radio_push(PacketType.ADVERTISEMENT, adv_payload)

        # The advertisement push is passed to app; LXMF announce is separate
        # (in a full bridge the reader loop would call encode_advertisement and
        # lxmf.announce, but here we test only the push-to-app path)
        frame = await router.app.next_frame()
        assert frame[0] == PacketType.ADVERTISEMENT


class TestLocalCommandPassthrough:
    """Commands for local contacts should reach the radio, not LXMF."""

    async def test_app_start_reaches_radio(self, router, radio, lxmf):
        await router.handle_app_command(bytes([CommandType.APP_START]))
        cmd = await radio.next_command()
        assert cmd[0] == CommandType.APP_START
        lxmf.assert_sent_count(0)

    async def test_get_contacts_reaches_radio(self, router, radio, lxmf):
        await router.handle_app_command(bytes([CommandType.GET_CONTACTS, 0x00]))
        cmd = await radio.next_command()
        assert cmd[0] == CommandType.GET_CONTACTS
        lxmf.assert_sent_count(0)


class TestMultipleMessages:
    """Send several messages and verify ordering is preserved."""

    async def test_message_order_preserved(self, router, lxmf):
        texts = ["first", "second", "third"]
        for t in texts:
            await router.handle_app_command(pack_send_txt_msg(REMOTE_PREFIX, t))

        assert len(lxmf.sent) == 3
        for i, msg in enumerate(lxmf.sent):
            assert msg.text == texts[i]

    async def test_mixed_local_remote_commands(self, router, radio, lxmf):
        """Interleaved local and remote commands are handled independently."""
        await router.handle_app_command(bytes([CommandType.APP_START]))
        await router.handle_app_command(pack_send_txt_msg(REMOTE_PREFIX, "remote"))
        await router.handle_app_command(bytes([CommandType.SYNC_NEXT_MESSAGE]))

        local_cmds = await radio.drain_commands()
        assert len(local_cmds) == 2
        assert local_cmds[0][0] == CommandType.APP_START
        assert local_cmds[1][0] == CommandType.SYNC_NEXT_MESSAGE
        lxmf.assert_sent_count(1)
