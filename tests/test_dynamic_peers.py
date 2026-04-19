"""Tests for dynamic peer discovery via Reticulum announces.

When a peer's announce arrives, the daemon wires the LXMF transport's
announce callback into router.observe_peer_announce, which populates the
PeerRegistry.  These tests exercise that plumbing with a mock transport.
"""
from __future__ import annotations

import pytest

from bridge.conflicts import PeerAnnounce
from bridge.config import load_config_from_dict
from bridge.daemon import Daemon


def _config(**overrides):
    base = {
        "router": {
            "name": "bridge.test.example.net",
            "short_tag": "TEST",
            "local_callsign": "BRIDGE-TEST",
        },
        "radio": {"type": "mock"},
        "reticulum": {"type": "mock"},
    }
    for k, v in overrides.items():
        base[k] = v
    return load_config_from_dict(base)


class TestDynamicPeerLearning:
    async def test_new_announce_populates_registry(self):
        daemon = Daemon(_config())
        await daemon.start()

        assert len(daemon.router.peers.incumbents()) == 0

        announce = PeerAnnounce(
            identity_hash=b"\x01" * 16,
            public_key=b"\xa1" * 32,
            router_name="bridge.sea.example.net",
            observed_at=1_700_000_000.0,
        )
        await daemon.lxmf.inject_announce(announce)

        incumbents = daemon.router.peers.incumbents()
        assert b"\x01" * 16 in incumbents
        assert incumbents[b"\x01" * 16].router_name == "bridge.sea.example.net"

        await daemon.stop()

    async def test_repeat_announce_updates_timestamp(self):
        daemon = Daemon(_config())
        await daemon.start()

        first = PeerAnnounce(
            identity_hash=b"\x01" * 16,
            public_key=b"\xa1" * 32,
            router_name="bridge.sea.example.net",
            observed_at=1_700_000_000.0,
        )
        await daemon.lxmf.inject_announce(first)
        second = PeerAnnounce(
            identity_hash=b"\x01" * 16,
            public_key=b"\xa1" * 32,
            router_name="bridge.sea.example.net",
            observed_at=1_700_000_100.0,
        )
        await daemon.lxmf.inject_announce(second)

        incumbents = daemon.router.peers.incumbents()
        assert incumbents[b"\x01" * 16].observed_at == 1_700_000_100.0

        await daemon.stop()

    async def test_conflicting_announce_produces_report(self):
        daemon = Daemon(_config())
        await daemon.start()

        legitimate = PeerAnnounce(
            identity_hash=b"\x01" * 16,
            public_key=b"\xa1" * 32,
            router_name="bridge.alice.net",
            observed_at=1_700_000_000.0,
        )
        await daemon.lxmf.inject_announce(legitimate)

        collision = PeerAnnounce(
            identity_hash=b"\x01" * 16,
            public_key=b"\xa2" * 32,   # different pubkey, same hash
            router_name="bridge.bob.net",
            observed_at=1_700_000_100.0,
        )
        await daemon.lxmf.inject_announce(collision)

        from bridge.control_channel import ConflictReportPost
        reports = daemon.router.control_channel.posts_of_type(ConflictReportPost)
        assert len(reports) == 1

        await daemon.stop()

    async def test_expected_peer_announce_populates_cleanly(self):
        """An announce for a peer listed in config should populate the registry
        without producing a conflict (placeholders no longer pre-seeded)."""
        daemon = Daemon(_config(peers=[
            {
                "router_name": "bridge.pre.example.net",
                "identity_hash": "aa" * 16,
            },
        ]))
        await daemon.start()

        # Registry starts empty (per revised daemon behaviour)
        assert len(daemon.router.peers.incumbents()) == 0

        # Real announce arrives
        announce = PeerAnnounce(
            identity_hash=b"\xaa" * 16,
            public_key=b"\xbb" * 32,
            router_name="bridge.pre.example.net",
            observed_at=2_000_000_000.0,
        )
        await daemon.lxmf.inject_announce(announce)

        # Peer is now incumbent with its real pubkey and no conflict report
        incumbents = daemon.router.peers.incumbents()
        assert b"\xaa" * 16 in incumbents
        assert incumbents[b"\xaa" * 16].public_key == b"\xbb" * 32

        from bridge.control_channel import ConflictReportPost
        reports = daemon.router.control_channel.posts_of_type(ConflictReportPost)
        assert len(reports) == 0

        await daemon.stop()
