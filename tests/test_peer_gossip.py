"""Tests for peer publication-state gossip (spec §8.5)."""
from __future__ import annotations

import pytest

from bridge.channel_state import (
    ChannelRegistry,
    PublishControl,
    UnpublishControl,
)
from bridge.peer_gossip import (
    StateEntry,
    StateQuery,
    StateResponse,
    build_response,
    merge_response,
)


HASH_A = b"\xaa" * 16
HASH_B = b"\xbb" * 16


class TestBuildResponse:
    def test_empty_query(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        resp = build_response(reg, StateQuery(channel_hashes=()))
        assert resp.entries == ()

    def test_unknown_channels_omitted(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        resp = build_response(reg, StateQuery(channel_hashes=(HASH_B,)))
        assert resp.entries == ()

    def test_known_unpublished_returned(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        resp = build_response(reg, StateQuery(channel_hashes=(HASH_A,)))
        assert len(resp.entries) == 1
        entry = resp.entries[0]
        assert entry.channel_hash == HASH_A
        assert entry.published is False

    def test_published_persistent_returned(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.apply_control(HASH_A, PublishControl(None), now=1000.0)
        resp = build_response(reg, StateQuery(channel_hashes=(HASH_A,)))
        entry = resp.entries[0]
        assert entry.published is True
        assert entry.expires_at is None
        assert entry.source_timestamp == 1000.0

    def test_published_with_duration_returned(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.apply_control(HASH_A, PublishControl(3600), now=1000.0)
        resp = build_response(reg, StateQuery(channel_hashes=(HASH_A,)))
        entry = resp.entries[0]
        assert entry.published is True
        assert entry.expires_at == 4600.0


class TestMergeResponse:
    def test_peer_newer_state_adopted(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        # Local: unpublished at time 1000
        reg.apply_control(HASH_A, UnpublishControl(), now=1000.0)
        # Peer reports published at time 2000
        resp = StateResponse(entries=(
            StateEntry(HASH_A, published=True, source_timestamp=2000.0, expires_at=None),
        ))
        updated = merge_response(reg, resp)
        assert updated == [HASH_A]
        assert reg.is_published(HASH_A, now=3000.0)

    def test_peer_older_state_rejected(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        # Local: published at time 2000
        reg.apply_control(HASH_A, PublishControl(None), now=2000.0)
        # Peer reports unpublished at time 1000
        resp = StateResponse(entries=(
            StateEntry(HASH_A, published=False, source_timestamp=1000.0, expires_at=None),
        ))
        updated = merge_response(reg, resp)
        assert updated == []
        assert reg.is_published(HASH_A, now=3000.0)

    def test_unregistered_channel_ignored(self):
        reg = ChannelRegistry()
        # Not registered; peer reports published
        resp = StateResponse(entries=(
            StateEntry(HASH_A, published=True, source_timestamp=2000.0, expires_at=None),
        ))
        updated = merge_response(reg, resp)
        assert updated == []

    def test_mixed_updates(self):
        reg = ChannelRegistry()
        reg.register(HASH_A, "weather")
        reg.register(HASH_B, "emergency")
        reg.apply_control(HASH_A, UnpublishControl(), now=1000.0)   # older
        reg.apply_control(HASH_B, PublishControl(None), now=2000.0)  # newer than peer

        resp = StateResponse(entries=(
            StateEntry(HASH_A, published=True, source_timestamp=2000.0, expires_at=None),
            StateEntry(HASH_B, published=False, source_timestamp=1000.0, expires_at=None),
        ))
        updated = merge_response(reg, resp)
        assert updated == [HASH_A]
        assert reg.is_published(HASH_A, now=3000.0)
        assert reg.is_published(HASH_B, now=3000.0)


class TestConvergence:
    def test_both_routers_converge_to_latest(self):
        """Two routers each gossip to the other and end up agreeing."""
        reg_a = ChannelRegistry()
        reg_a.register(HASH_A, "weather")
        reg_a.apply_control(HASH_A, UnpublishControl(), now=1000.0)

        reg_b = ChannelRegistry()
        reg_b.register(HASH_A, "weather")
        reg_b.apply_control(HASH_A, PublishControl(None), now=2000.0)

        # A queries B
        resp_from_b = build_response(reg_b, StateQuery(channel_hashes=(HASH_A,)))
        merge_response(reg_a, resp_from_b)
        # B queries A (already-converged; A now matches B)
        resp_from_a = build_response(reg_a, StateQuery(channel_hashes=(HASH_A,)))
        merge_response(reg_b, resp_from_a)

        # Both see the same state
        assert reg_a.is_published(HASH_A, now=3000.0)
        assert reg_b.is_published(HASH_A, now=3000.0)

        assert reg_a.get_state(HASH_A).source_timestamp == 2000.0
        assert reg_b.get_state(HASH_A).source_timestamp == 2000.0
