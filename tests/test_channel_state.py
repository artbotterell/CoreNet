"""Tests for bridge/channel_state.py — publication state (§8.4) and loop prevention (§8.3)."""
from __future__ import annotations

import pytest

from bridge.channel_state import (
    ChannelRegistry,
    PublishControl,
    UnpublishControl,
    parse_control_message,
)


HASH_A = b"\xaa" * 32
HASH_B = b"\xbb" * 32


class TestParseControlMessage:
    def test_publish_persistent(self):
        assert parse_control_message("::corenet publish::") == PublishControl(None)

    def test_publish_with_duration_minutes(self):
        assert parse_control_message("::corenet publish 30m::") == PublishControl(30 * 60)

    def test_publish_with_duration_hours(self):
        assert parse_control_message("::corenet publish 2h::") == PublishControl(2 * 3600)

    def test_publish_with_duration_days(self):
        assert parse_control_message("::corenet publish 7d::") == PublishControl(7 * 86400)

    def test_publish_bare_number(self):
        assert parse_control_message("::corenet publish 30::") == PublishControl(30 * 60)

    def test_unpublish(self):
        assert parse_control_message("::corenet unpublish::") == UnpublishControl()

    def test_whitespace_tolerated(self):
        assert parse_control_message("  ::corenet publish::  ") == PublishControl(None)

    def test_not_a_control_message(self):
        for text in [
            "hello world",
            "::corenet foo::",
            "::publish::",
            "corenet publish",
            "",
            "::corenet publish invalid::",
        ]:
            assert parse_control_message(text) is None, text

    def test_case_sensitive(self):
        # Spec specifies lowercase keywords
        assert parse_control_message("::CoreNet publish::") is None
        assert parse_control_message("::corenet PUBLISH::") is None


class TestPublicationState:
    def test_unregistered_channel_not_published(self):
        reg = ChannelRegistry()
        assert not reg.is_published(HASH_A)

    def test_registered_but_not_published_returns_false(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        assert not reg.is_published(HASH_A)

    def test_publish_persistent(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.apply_control(HASH_A, PublishControl(None), now=1000.0)
        assert reg.is_published(HASH_A, now=1000.0)
        assert reg.is_published(HASH_A, now=1_000_000.0)   # far future

    def test_publish_with_duration(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.apply_control(HASH_A, PublishControl(3600), now=1000.0)
        assert reg.is_published(HASH_A, now=1000.0)
        assert reg.is_published(HASH_A, now=4000.0)          # within window
        assert not reg.is_published(HASH_A, now=5000.0)      # expired

    def test_unpublish_overrides_publish(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.apply_control(HASH_A, PublishControl(None), now=1000.0)
        reg.apply_control(HASH_A, UnpublishControl(), now=1100.0)
        assert not reg.is_published(HASH_A, now=1200.0)

    def test_publish_replaces_earlier_publish(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.apply_control(HASH_A, PublishControl(3600), now=1000.0)
        reg.apply_control(HASH_A, PublishControl(None), now=1500.0)
        # Now persistent; far-future check succeeds
        assert reg.is_published(HASH_A, now=1_000_000.0)

    def test_control_on_unregistered_channel_is_noop(self):
        reg = ChannelRegistry()
        reg.apply_control(HASH_A, PublishControl(None), now=1000.0)
        assert not reg.is_published(HASH_A, now=1000.0)

    def test_published_channels_listing(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.register(HASH_B, "emergency")
        reg.apply_control(HASH_A, PublishControl(None), now=1000.0)
        # B stays unpublished
        listed = reg.published_channels(now=1500.0)
        assert listed == [(HASH_A, "weather")]

    def test_published_channels_excludes_expired(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.register(HASH_B, "emergency")
        reg.apply_control(HASH_A, PublishControl(100), now=1000.0)
        reg.apply_control(HASH_B, PublishControl(None), now=1000.0)
        # After A's TTL, only B remains
        listed = reg.published_channels(now=2000.0)
        assert listed == [(HASH_B, "emergency")]


class TestLoopPrevention:
    def test_new_tag_forwards(self):
        reg = ChannelRegistry()
        assert reg.should_forward(b"\x01\x02\x03\x04", now=1000.0)

    def test_repeated_tag_drops(self):
        reg = ChannelRegistry()
        tag = b"\x01\x02\x03\x04"
        assert reg.should_forward(tag, now=1000.0)
        assert not reg.should_forward(tag, now=1001.0)

    def test_different_tags_independent(self):
        reg = ChannelRegistry()
        assert reg.should_forward(b"tag1" + b"\x00" * 0, now=1000.0)
        assert reg.should_forward(b"tag2" + b"\x00" * 0, now=1000.0)

    def test_tag_expires_after_ttl(self):
        reg = ChannelRegistry(seen_tag_ttl=60.0)
        tag = b"\x01\x02\x03\x04"
        assert reg.should_forward(tag, now=1000.0)
        # Just past the TTL
        assert reg.should_forward(tag, now=1061.0)

    def test_tag_not_expired_within_ttl(self):
        reg = ChannelRegistry(seen_tag_ttl=60.0)
        tag = b"\x01\x02\x03\x04"
        assert reg.should_forward(tag, now=1000.0)
        # 59 seconds later — still blocked
        assert not reg.should_forward(tag, now=1059.0)

    def test_memory_cap_evicts_oldest(self):
        reg = ChannelRegistry(seen_tag_max=3)
        reg.should_forward(b"\x00\x00\x00\x01", now=1000.0)
        reg.should_forward(b"\x00\x00\x00\x02", now=1001.0)
        reg.should_forward(b"\x00\x00\x00\x03", now=1002.0)
        reg.should_forward(b"\x00\x00\x00\x04", now=1003.0)
        # First tag was evicted, so it's "new" again
        assert reg.should_forward(b"\x00\x00\x00\x01", now=1004.0)
        # Latest tag is still seen
        assert not reg.should_forward(b"\x00\x00\x00\x04", now=1005.0)

    def test_seen_count_after_evictions(self):
        reg = ChannelRegistry(seen_tag_ttl=60.0)
        reg.should_forward(b"a" * 4, now=1000.0)
        reg.should_forward(b"b" * 4, now=1001.0)
        assert reg.seen_count() == 2
        # Trigger eviction by a query past TTL
        reg.should_forward(b"c" * 4, now=1100.0)
        assert reg.seen_count() == 1
