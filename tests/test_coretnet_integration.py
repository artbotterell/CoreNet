"""Integration tests for the CoreNet-specific router mechanisms.

Covers:
  - @callsign@region DM parsing and LXMF forwarding (spec §5, §9.1)
  - Inbound DM delivery with [@source] prefix (§9.2)
  - Router commands: who, channels, bridge, unbridge, bridge-status (§7, §8.2.2)
  - In-channel publish/unpublish handling (§8.4)
  - Channel loop prevention (§8.3)
  - Identity conflict detection and control-channel reporting (§10)
  - Bridge activation notices on the control channel (§8.2.3)
"""
from __future__ import annotations

import pytest

from bridge.addressing import CoreNetAddress, format_inbound, parse_inbound
from bridge.channel_state import ChannelRegistry
from bridge.conflicts import PeerAnnounce, PeerRegistry
from bridge.control_channel import (
    BridgeActivationNotice,
    ConflictReportPost,
    MockControlChannel,
    RouterOnline,
)
from bridge.lxmf_layer.transport import FIELD_APP_DATA, FIELD_TEXT
from bridge.router import ContactEntry, ContactRegistry, Router
from tests.doubles.mock_app import MockApp
from tests.doubles.mock_lxmf import MockLxmfTransport
from tests.doubles.mock_radio import MockRadio


LOCAL_CALLSIGN = "BRIDGE-LAX"
LOCAL_HASH = "deadbeefcafe"
LOCAL_PREFIX = bytes.fromhex("aaaaaaaaaaaa")

USER_A_PREFIX = bytes.fromhex("111111111111")
USER_A_CALLSIGN = "W5XYZ"

PEER_HASH = b"\xbb\xcc\xdd\xee\xff\x00\x11\x22\x33\x44\x55\x66"
PEER_PUBKEY = b"\xa1" * 32


@pytest.fixture
def contacts_with_user_a() -> ContactRegistry:
    reg = ContactRegistry()
    reg.add(ContactEntry(
        pubkey=USER_A_PREFIX + b"\x00" * 26,
        prefix=USER_A_PREFIX,
        display_name=USER_A_CALLSIGN,
        lxmf_hash="",
        is_remote=False,
    ))
    return reg


@pytest.fixture
def router(contacts_with_user_a):
    radio = MockRadio()
    lxmf = MockLxmfTransport()
    app = MockApp()
    channels = ChannelRegistry()
    peers = PeerRegistry("bridge.lax.example.net")
    control = MockControlChannel()
    # Register a peer router so address resolution works
    peers.observe(PeerAnnounce(
        identity_hash=PEER_HASH,
        public_key=PEER_PUBKEY,
        router_name="SEA",
        observed_at=1000.0,
    ))
    r = Router(
        contacts=contacts_with_user_a,
        lxmf=lxmf,
        local_hash=LOCAL_HASH,
        router_name="bridge.lax.example.net",
        short_tag="LAX",
        local_callsign=LOCAL_CALLSIGN,
        channels=channels,
        peers=peers,
        control_channel=control,
        radio=radio,
        app=app,
        clock=lambda: 1_700_000_000.0,
    )
    return r


# ---------------------------------------------------------------------------
# @callsign@region outbound routing
# ---------------------------------------------------------------------------

class TestCoreNetAddressForwarding:
    async def test_valid_address_forwarded_to_lxmf(self, router):
        reply = await router.handle_inbound_dm(
            USER_A_PREFIX, "@KD6O@SEA hello up there"
        )
        assert reply is None   # forwarded, no inline reply
        assert len(router.lxmf.sent) == 1

    async def test_forwarded_message_has_stripped_body(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "@KD6O@SEA hello up there")
        sent = router.lxmf.sent[0]
        assert sent.fields[FIELD_TEXT] == "hello up there"

    async def test_forwarded_message_carries_source_address(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "@KD6O@SEA hello")
        app_data = router.lxmf.sent[0].fields[FIELD_APP_DATA]
        assert app_data["source_callsign"] == USER_A_CALLSIGN
        assert app_data["source_router"] == "LAX"
        assert app_data["target_callsign"] == "KD6O"

    async def test_unknown_router_drops_message(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "@KD6O@UNKNOWN hello")
        assert len(router.lxmf.sent) == 0

    async def test_non_address_text_not_forwarded(self, router):
        # Looks like casual text, not an address
        await router.handle_inbound_dm(USER_A_PREFIX, "hello world")
        assert len(router.lxmf.sent) == 0


# ---------------------------------------------------------------------------
# Inbound LXMF delivery with [@source] prefix
# ---------------------------------------------------------------------------

class TestCoreNetAddressInbound:
    async def test_inbound_delivered_with_source_prefix(self, router):
        # Simulate an LXMF arrival addressed to user_A via CoreNet
        from bridge.lxmf_layer.transport import LxmfMessage
        from bridge.companion.types import LxmfDestType, LxmfTransport

        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.NODE,
            destination="meshcore.node.deadbeefcafe",
            source="peer",
            fields={
                FIELD_TEXT: "hi there",
                FIELD_APP_DATA: {
                    "target_callsign": USER_A_CALLSIGN,
                    "source_callsign": "KD6O",
                    "source_router": "SEA",
                },
            },
        )
        await router.lxmf.inject(msg)

        # The router should have sent a SEND_TXT_MSG on the radio targeted to user_A
        cmd = await router.radio.next_command()
        assert cmd[0] == 0x02   # CMD_SEND_TXT_MSG
        assert cmd[1:7] == USER_A_PREFIX
        body = cmd[7:].decode("utf-8")
        parsed = parse_inbound(body)
        assert parsed is not None
        assert parsed.source.callsign == "KD6O"
        assert parsed.source.router_name == "SEA"
        assert parsed.body == "hi there"

    async def test_inbound_to_unknown_callsign_dropped(self, router):
        from bridge.lxmf_layer.transport import LxmfMessage
        from bridge.companion.types import LxmfDestType, LxmfTransport

        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.NODE,
            destination="meshcore.node.deadbeefcafe",
            source="peer",
            fields={
                FIELD_TEXT: "orphan",
                FIELD_APP_DATA: {
                    "target_callsign": "NOSUCH",
                    "source_callsign": "KD6O",
                    "source_router": "SEA",
                },
            },
        )
        await router.lxmf.inject(msg)
        # No radio command should have been issued
        cmds = await router.radio.drain_commands()
        assert cmds == []


# ---------------------------------------------------------------------------
# Router commands
# ---------------------------------------------------------------------------

class TestWhoCommand:
    async def test_who_empty_roster(self, router):
        reply = await router.handle_inbound_dm(USER_A_PREFIX, "who")
        assert "No matching" in reply or "0" in reply

    async def test_who_with_remote_contact(self, router):
        router.contacts.add(ContactEntry(
            pubkey=b"\x01" * 32,
            prefix=b"\x01" * 6,
            display_name="KD6O",
            lxmf_hash="deadbeef",
            is_remote=True,
            router_name="SEA",
        ))
        reply = await router.handle_inbound_dm(USER_A_PREFIX, "who")
        assert "KD6O" in reply
        assert "SEA" in reply

    async def test_who_with_callsign_filter(self, router):
        router.contacts.add(ContactEntry(
            pubkey=b"\x01" * 32, prefix=b"\x01" * 6, display_name="KD6O",
            lxmf_hash="d", is_remote=True, router_name="SEA",
        ))
        router.contacts.add(ContactEntry(
            pubkey=b"\x02" * 32, prefix=b"\x02" * 6, display_name="W7ABC",
            lxmf_hash="e", is_remote=True, router_name="PDX",
        ))
        reply = await router.handle_inbound_dm(USER_A_PREFIX, "who KD6O")
        assert "KD6O" in reply
        assert "W7ABC" not in reply


class TestChannelsCommand:
    async def test_no_published_channels(self, router):
        reply = await router.handle_inbound_dm(USER_A_PREFIX, "channels")
        assert "No public channels" in reply

    async def test_published_channel_listed(self, router):
        router.activate_nailed_up_bridge("weather", b"secret")
        # Simulate a publish control message arriving in the channel
        from bridge.channel_state import PublishControl
        channel_hash = router._derive_channel_hash("weather", b"secret")
        router.channels.apply_control(channel_hash, PublishControl(None), now=1_700_000_000.0)

        reply = await router.handle_inbound_dm(USER_A_PREFIX, "channels")
        assert "weather" in reply


class TestBridgeCommands:
    async def test_activate_and_status(self, router):
        reply = await router.handle_inbound_dm(USER_A_PREFIX, "bridge weather 30m")
        assert "weather" in reply
        assert "30" in reply

        status = await router.handle_inbound_dm(USER_A_PREFIX, "bridge-status")
        assert "weather" in status

    async def test_unbridge(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "bridge weather 30m")
        reply = await router.handle_inbound_dm(USER_A_PREFIX, "unbridge weather")
        assert "ended" in reply

        status = await router.handle_inbound_dm(USER_A_PREFIX, "bridge-status")
        assert "No active" in status

    async def test_activation_posts_control_notice(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "bridge weather 30m")
        notices = router.control_channel.posts_of_type(BridgeActivationNotice)
        assert len(notices) == 1
        assert notices[0].event == "activate"

    async def test_unbridge_posts_expire_notice(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "bridge weather 30m")
        await router.handle_inbound_dm(USER_A_PREFIX, "unbridge weather")
        notices = router.control_channel.posts_of_type(BridgeActivationNotice)
        assert len(notices) == 2
        assert notices[-1].event == "expire"

    async def test_activation_notice_uses_hash_only(self, router):
        await router.handle_inbound_dm(USER_A_PREFIX, "bridge weather 30m")
        notice = router.control_channel.posts_of_type(BridgeActivationNotice)[0]
        # The notice's formatted text should contain the hash prefix but
        # never the channel name (spec §8.2.3)
        text = notice.format()
        assert "weather" not in text

    async def test_nailed_up_posts_persistent_notice(self, router):
        router.activate_nailed_up_bridge("emergency-coord", b"secret")
        notices = router.control_channel.posts_of_type(BridgeActivationNotice)
        assert len(notices) == 1
        assert notices[0].expires_at is None


# ---------------------------------------------------------------------------
# Channel message handling: loop prevention + in-channel controls
# ---------------------------------------------------------------------------

class TestInChannelControls:
    async def test_publish_message_applies_state(self, router):
        channel_hash = router.activate_nailed_up_bridge("weather", b"s")
        forwarded = await router.handle_inbound_channel_msg(
            channel_hash, b"tag1", "::corenet publish::", from_rf=True
        )
        assert forwarded is False   # control messages are consumed, not forwarded
        assert router.channels.is_published(channel_hash, now=1_700_000_000.0)

    async def test_unpublish_reverts_state(self, router):
        channel_hash = router.activate_nailed_up_bridge("weather", b"s")
        await router.handle_inbound_channel_msg(
            channel_hash, b"tag1", "::corenet publish::", from_rf=True
        )
        await router.handle_inbound_channel_msg(
            channel_hash, b"tag2", "::corenet unpublish::", from_rf=True
        )
        assert not router.channels.is_published(channel_hash, now=1_700_000_000.0)

    async def test_publish_with_duration(self, router):
        channel_hash = router.activate_nailed_up_bridge("weather", b"s")
        await router.handle_inbound_channel_msg(
            channel_hash, b"tag1", "::corenet publish 1h::", from_rf=True
        )
        # Well past one hour
        assert not router.channels.is_published(channel_hash, now=1_700_000_000.0 + 3700)


class TestLoopPrevention:
    async def test_duplicate_tag_dropped(self, router):
        channel_hash = router.activate_nailed_up_bridge("weather", b"s")
        tag = b"\x01\x02\x03\x04"
        first = await router.handle_inbound_channel_msg(
            channel_hash, tag, "hello", from_rf=True
        )
        second = await router.handle_inbound_channel_msg(
            channel_hash, tag, "hello", from_rf=False
        )
        assert first is True     # new, forward
        assert second is False   # seen, drop


# ---------------------------------------------------------------------------
# Identity conflict detection
# ---------------------------------------------------------------------------

class TestConflictDetection:
    async def test_new_peer_no_conflict(self, router):
        await router.observe_peer_announce(PeerAnnounce(
            identity_hash=b"\x01" * 12,
            public_key=b"\xa1" * 32,
            router_name="bridge.new.net",
            observed_at=1_700_000_000.0,
        ))
        assert router.control_channel.posts_of_type(ConflictReportPost) == []

    async def test_collision_triggers_report(self, router):
        # First observation
        await router.observe_peer_announce(PeerAnnounce(
            identity_hash=b"\x01" * 12,
            public_key=b"\xa1" * 32,
            router_name="bridge.alice.net",
            observed_at=1_700_000_000.0,
        ))
        # Second observation with same hash but different pubkey
        await router.observe_peer_announce(PeerAnnounce(
            identity_hash=b"\x01" * 12,
            public_key=b"\xa2" * 32,
            router_name="bridge.bob.net",
            observed_at=1_700_000_100.0,
        ))
        reports = router.control_channel.posts_of_type(ConflictReportPost)
        assert len(reports) == 1

    async def test_dedup_within_window(self, router):
        await router.observe_peer_announce(PeerAnnounce(
            identity_hash=b"\x01" * 12, public_key=b"\xa1" * 32,
            router_name="A", observed_at=1_700_000_000.0,
        ))
        # Duplicate conflict — should dedupe and not produce a second report
        await router.observe_peer_announce(PeerAnnounce(
            identity_hash=b"\x01" * 12, public_key=b"\xa2" * 32,
            router_name="B", observed_at=1_700_000_100.0,
        ))
        await router.observe_peer_announce(PeerAnnounce(
            identity_hash=b"\x01" * 12, public_key=b"\xa2" * 32,
            router_name="B", observed_at=1_700_000_200.0,
        ))
        reports = router.control_channel.posts_of_type(ConflictReportPost)
        assert len(reports) == 1


# ---------------------------------------------------------------------------
# Router-online announcement
# ---------------------------------------------------------------------------

class TestRouterOnlineAnnouncement:
    async def test_announce_online_posts_notice(self, router):
        router.announce_online(zone_description="Los Angeles metro")
        notices = router.control_channel.posts_of_type(RouterOnline)
        assert len(notices) == 1
        assert notices[0].router_name == "bridge.lax.example.net"
        assert notices[0].zone_description == "Los Angeles metro"


# ---------------------------------------------------------------------------
# End-to-end two-bridge CoreNet DM round-trip
# ---------------------------------------------------------------------------

class TestTwoBridgeCoreNetPipe:
    async def test_end_to_end_addressed_dm(self):
        """A DM sent to @TARGET@PEER from bridge-A's RF user arrives at the
        corresponding user on bridge-B's RF with [@source] prefix."""

        # Bridge A
        contacts_a = ContactRegistry()
        contacts_a.add(ContactEntry(
            pubkey=USER_A_PREFIX + b"\x00" * 26,
            prefix=USER_A_PREFIX,
            display_name=USER_A_CALLSIGN,
            lxmf_hash="",
            is_remote=False,
        ))
        radio_a = MockRadio()
        lxmf_a = MockLxmfTransport()
        app_a = MockApp()
        control_a = MockControlChannel()
        peers_a = PeerRegistry("bridge.lax")
        peer_b = PeerAnnounce(
            identity_hash=PEER_HASH,
            public_key=PEER_PUBKEY,
            router_name="SEA",
            observed_at=1000.0,
        )
        peers_a.observe(peer_b)
        router_a = Router(
            contacts=contacts_a,
            lxmf=lxmf_a,
            local_hash="lax-self",
            router_name="bridge.lax.example.net",
            short_tag="LAX",
            local_callsign="BRIDGE-LAX",
            peers=peers_a,
            control_channel=control_a,
            radio=radio_a,
            app=app_a,
            clock=lambda: 1_700_000_000.0,
        )

        # Bridge B
        TARGET_PREFIX = bytes.fromhex("222222222222")
        TARGET_CALLSIGN = "KD6O"
        contacts_b = ContactRegistry()
        contacts_b.add(ContactEntry(
            pubkey=TARGET_PREFIX + b"\x00" * 26,
            prefix=TARGET_PREFIX,
            display_name=TARGET_CALLSIGN,
            lxmf_hash="",
            is_remote=False,
        ))
        radio_b = MockRadio()
        lxmf_b = MockLxmfTransport()
        app_b = MockApp()
        control_b = MockControlChannel()
        router_b = Router(
            contacts=contacts_b,
            lxmf=lxmf_b,
            local_hash="sea-self",
            router_name="bridge.sea.example.net",
            short_tag="SEA",
            local_callsign="BRIDGE-SEA",
            control_channel=control_b,
            radio=radio_b,
            app=app_b,
            clock=lambda: 1_700_000_000.0,
        )

        # Wire the two mock LXMF transports: send on A → inject on B and vice-versa
        original_send_a = lxmf_a.send
        async def send_a(msg):
            await original_send_a(msg)
            await lxmf_b.inject(msg)
        lxmf_a.send = send_a   # type: ignore[method-assign]

        # Drive: user_A sends DM to bridge_A with "@KD6O@SEA hey"
        await router_a.handle_inbound_dm(USER_A_PREFIX, "@KD6O@SEA hey there")

        # Bridge_A should have sent one LXMF message to bridge_B
        assert len(lxmf_a.sent) == 1

        # Bridge_B should have received it and emitted a SEND_TXT_MSG on its radio
        cmd = await radio_b.next_command(timeout=2.0)
        assert cmd[0] == 0x02   # CMD_SEND_TXT_MSG
        assert cmd[1:7] == TARGET_PREFIX

        # The body should carry the [@source] prefix per spec §9.2
        body = cmd[7:].decode("utf-8")
        parsed = parse_inbound(body)
        assert parsed is not None
        assert parsed.source.callsign == USER_A_CALLSIGN
        assert parsed.source.router_name == "LAX"
        assert parsed.body == "hey there"
