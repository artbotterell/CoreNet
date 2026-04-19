"""Tests for bridge/conflicts.py — identity conflict detection per spec §10."""
from __future__ import annotations

import pytest

from bridge.conflicts import ConflictReport, PeerAnnounce, PeerRegistry


HASH_A = b"\xaa\xbb\xcc\xdd" + b"\x00" * 12
HASH_B = b"\x11\x22\x33\x44" + b"\x00" * 12

PUBKEY_ALICE = b"\x01" * 32
PUBKEY_BOB   = b"\x02" * 32
PUBKEY_EVE   = b"\xff" * 32


class TestFirstSeen:
    def test_new_peer_accepted(self):
        reg = PeerRegistry("self.example.net")
        announce = PeerAnnounce(
            identity_hash=HASH_A,
            public_key=PUBKEY_ALICE,
            router_name="bridge.alice.net",
            observed_at=1000.0,
        )
        result, report = reg.observe(announce)
        assert result == "first_seen"
        assert report is None
        assert HASH_A in reg.incumbents()


class TestReAnnounce:
    def test_same_peer_known(self):
        reg = PeerRegistry("self.example.net")
        a1 = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1000.0)
        a2 = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 2000.0)
        reg.observe(a1)
        result, report = reg.observe(a2)
        assert result == "known"
        assert report is None

    def test_timestamp_updated_on_reannounce(self):
        reg = PeerRegistry("self.example.net")
        a1 = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1000.0)
        a2 = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 2000.0)
        reg.observe(a1)
        reg.observe(a2)
        assert reg.incumbents()[HASH_A].observed_at == 2000.0


class TestConflict:
    def test_different_pubkey_same_hash_is_conflict(self):
        reg = PeerRegistry("self.example.net")
        incumbent = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1000.0)
        latecomer = PeerAnnounce(HASH_A, PUBKEY_BOB, "bridge.bob.net", 2000.0)
        reg.observe(incumbent)
        result, report = reg.observe(latecomer)
        assert result == "conflict"
        assert report is not None
        assert report.incumbent.public_key == PUBKEY_ALICE
        assert report.latecomer.public_key == PUBKEY_BOB

    def test_incumbent_retained_after_conflict(self):
        reg = PeerRegistry("self.example.net")
        incumbent = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1000.0)
        latecomer = PeerAnnounce(HASH_A, PUBKEY_BOB, "bridge.bob.net", 2000.0)
        reg.observe(incumbent)
        reg.observe(latecomer)
        # Incumbent unchanged
        assert reg.incumbents()[HASH_A].public_key == PUBKEY_ALICE
        # Latecomer recorded as refused
        assert HASH_A in reg.refused()
        assert reg.refused()[HASH_A].public_key == PUBKEY_BOB


class TestIndependentHashes:
    def test_different_hashes_are_independent(self):
        reg = PeerRegistry("self.example.net")
        a = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1000.0)
        b = PeerAnnounce(HASH_B, PUBKEY_BOB,   "bridge.bob.net",   2000.0)
        r1, _ = reg.observe(a)
        r2, _ = reg.observe(b)
        assert r1 == "first_seen"
        assert r2 == "first_seen"
        assert len(reg.incumbents()) == 2


class TestDedup:
    def test_first_report_publishes(self):
        reg = PeerRegistry("self.example.net")
        assert reg.should_publish_report(HASH_A, now=1000.0)

    def test_repeat_within_window_suppressed(self):
        reg = PeerRegistry("self.example.net")
        reg.should_publish_report(HASH_A, now=1000.0)
        # 30 minutes later — still within default hour window
        assert not reg.should_publish_report(HASH_A, now=1000.0 + 1800)

    def test_outside_window_publishes(self):
        reg = PeerRegistry("self.example.net", dedup_window=3600.0)
        reg.should_publish_report(HASH_A, now=1000.0)
        # Just past an hour
        assert reg.should_publish_report(HASH_A, now=1000.0 + 3700)


class TestReportFormat:
    def test_report_contains_key_fingerprints(self):
        incumbent = PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 1_700_000_000.0)
        latecomer = PeerAnnounce(HASH_A, PUBKEY_BOB,   "bridge.bob.net",   1_700_000_100.0)
        report = ConflictReport(
            identity_hash=HASH_A,
            incumbent=incumbent,
            latecomer=latecomer,
            reporting_router="self.example.net",
        )
        text = report.format_report()
        # Key properties: hash prefix, both pubkey fingerprints, retention status
        assert "aabbccdd" in text
        assert PUBKEY_ALICE.hex()[:8] in text
        assert PUBKEY_BOB.hex()[:8] in text
        assert "retained" in text
        assert "refused" in text
        assert "self.example.net" in text

    def test_report_identifies_both_routers(self):
        report = ConflictReport(
            identity_hash=HASH_A,
            incumbent=PeerAnnounce(HASH_A, PUBKEY_ALICE, "bridge.alice.net", 0.0),
            latecomer=PeerAnnounce(HASH_A, PUBKEY_BOB, "bridge.bob.net", 0.0),
            reporting_router="self.example.net",
        )
        text = report.format_report()
        assert "bridge.alice.net" in text
        assert "bridge.bob.net" in text
