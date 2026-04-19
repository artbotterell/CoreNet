"""Tests for bridge/control_channel.py — post discipline and format per spec §6, §8.2.3, §10.3."""
from __future__ import annotations

import pytest

from bridge.conflicts import ConflictReport, PeerAnnounce
from bridge.control_channel import (
    BridgeActivationNotice,
    ConflictReportPost,
    MockControlChannel,
    RosterSummary,
    RouterOnline,
)


HASH_A = b"\xaa\xbb\xcc\xdd" + b"\x00" * 28
PUBKEY_ALICE = b"\x01" * 32
PUBKEY_BOB   = b"\x02" * 32


class TestRouterOnline:
    def test_format_includes_name_and_fingerprint(self):
        post = RouterOnline(
            router_name="bridge.lax.example.net",
            short_tag="LAX",
            identity_fingerprint="a1b2c3d4",
            zone_description="Los Angeles metro",
        )
        text = post.format()
        assert "bridge.lax.example.net" in text
        assert "a1b2c3d4" in text
        assert "Los Angeles metro" in text
        assert "LAX" in text

    def test_format_without_short_tag(self):
        post = RouterOnline(
            router_name="bridge.lax.example.net",
            short_tag=None,
            identity_fingerprint="a1b2c3d4",
            zone_description="LA",
        )
        text = post.format()
        # Should not include an empty parenthetical
        assert "()" not in text


class TestBridgeActivationNotice:
    def test_activate_with_expiry(self):
        notice = BridgeActivationNotice(
            event="activate",
            channel_hash=HASH_A,
            router_name="bridge.lax.example.net",
            expires_at=1_700_000_000.0,
        )
        text = notice.format()
        assert "activate" in text
        assert HASH_A.hex()[:8] in text
        assert "bridge.lax.example.net" in text
        assert "expires" in text

    def test_activate_persistent(self):
        notice = BridgeActivationNotice(
            event="activate",
            channel_hash=HASH_A,
            router_name="bridge.lax.example.net",
            expires_at=None,
        )
        text = notice.format()
        assert "persistent" in text

    def test_expire_event(self):
        notice = BridgeActivationNotice(
            event="expire",
            channel_hash=HASH_A,
            router_name="bridge.lax.example.net",
            expires_at=None,
        )
        text = notice.format()
        assert "expire" in text
        assert HASH_A.hex()[:8] in text

    def test_invalid_event_rejected(self):
        with pytest.raises(ValueError, match="event must be"):
            BridgeActivationNotice(
                event="whatever",
                channel_hash=HASH_A,
                router_name="bridge.example.net",
                expires_at=None,
            )

    def test_format_uses_only_hash_prefix_not_full_hash(self):
        notice = BridgeActivationNotice(
            event="activate",
            channel_hash=HASH_A,
            router_name="bridge.lax.example.net",
            expires_at=None,
        )
        text = notice.format()
        # Full hash (68 hex chars total) shouldn't appear — just a short prefix
        assert HASH_A.hex() not in text
        assert HASH_A.hex()[:8] in text


class TestRosterSummary:
    def test_contains_count(self):
        summary = RosterSummary(
            router_name="bridge.lax.example.net",
            visible_count=42,
        )
        text = summary.format()
        assert "42" in text
        assert "bridge.lax.example.net" in text

    def test_no_individual_callsigns(self):
        # Spec §11.4 and §7.3: summaries carry counts, not individual identities
        summary = RosterSummary(
            router_name="bridge.lax.example.net",
            visible_count=3,
        )
        text = summary.format()
        # No obvious callsign shapes in the text
        assert "@" not in text


class TestConflictReportPost:
    def test_wraps_conflict_report(self):
        report = ConflictReport(
            identity_hash=HASH_A,
            incumbent=PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1000.0),
            latecomer=PeerAnnounce(HASH_A, PUBKEY_BOB, "bridge.bob.net", 2000.0),
            reporting_router="self.example.net",
        )
        post = ConflictReportPost(report=report)
        text = post.format()
        assert "aabbccdd" in text
        assert PUBKEY_ALICE.hex()[:8] in text
        assert PUBKEY_BOB.hex()[:8] in text


class TestMockControlChannel:
    def test_records_posts_in_order(self):
        ch = MockControlChannel()
        p1 = RouterOnline("r1", None, "aa00", "zone 1")
        p2 = RouterOnline("r2", None, "bb00", "zone 2")
        ch.publish(p1)
        ch.publish(p2)
        assert ch.posts == [p1, p2]

    def test_filter_posts_by_type(self):
        ch = MockControlChannel()
        ch.publish(RouterOnline("r1", None, "aa00", "zone"))
        ch.publish(
            BridgeActivationNotice(
                event="activate",
                channel_hash=HASH_A,
                router_name="r1",
                expires_at=None,
            )
        )
        assert len(ch.posts_of_type(RouterOnline)) == 1
        assert len(ch.posts_of_type(BridgeActivationNotice)) == 1

    def test_rejects_non_post_types(self):
        ch = MockControlChannel()
        with pytest.raises(TypeError):
            ch.publish("not a post")   # type: ignore[arg-type]

    def test_channel_name_leak_raises(self):
        """If a post's text contains a registered channel name, we catch it."""
        ch = MockControlChannel()
        ch.register_channel_name("corenet-wa")
        # Construct a pathological post that would leak a name
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class LeakyPost(RouterOnline):
            def format(self) -> str:
                return "leaks channel corenet-wa in its text"

        # LeakyPost IS a RouterOnline subclass, so isinstance passes and the
        # text-leak guard fires with AssertionError.
        with pytest.raises(AssertionError, match="leaked channel name"):
            ch.publish(LeakyPost("r1", None, "aa", "z"))

    def test_legitimate_post_with_channel_name_absent(self):
        ch = MockControlChannel()
        ch.register_channel_name("corenet-wa")
        # Normal activation notice uses hash, not name — passes leak check
        ch.publish(
            BridgeActivationNotice(
                event="activate",
                channel_hash=HASH_A,
                router_name="r1",
                expires_at=None,
            )
        )
        assert len(ch.posts) == 1


class TestDiscipline:
    def test_activation_notice_never_contains_name(self):
        # Even if the name is similar to a hash prefix, the notice uses hash bytes
        notice = BridgeActivationNotice(
            event="activate",
            channel_hash=HASH_A,
            router_name="bridge.lax.example.net",
            expires_at=None,
        )
        text = notice.format()
        # No conceivable channel name should appear
        for name in ["corenet-wa", "weather", "emergency", "firehouse-tac"]:
            assert name not in text
