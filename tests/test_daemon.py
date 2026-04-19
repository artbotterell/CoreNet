"""Tests for the daemon wiring.

The daemon composes config + transports + router.  We test that it starts
correctly against mock transports (so no hardware or network is required)
and that nailed-up bridges and peer seeding work as specified.
"""
from __future__ import annotations

import asyncio

import pytest

from bridge.config import BridgeConfig, load_config_from_dict
from bridge.daemon import Daemon


def _config(**overrides) -> BridgeConfig:
    base = {
        "router": {
            "name": "bridge.test.example.net",
            "short_tag": "TEST",
            "local_callsign": "BRIDGE-TEST",
            "zone_description": "unit test zone",
        },
        "radio": {"type": "mock"},
        "reticulum": {"type": "mock"},
    }
    # Shallow merge
    for k, v in overrides.items():
        base[k] = v
    return load_config_from_dict(base)


class TestDaemonStart:
    async def test_starts_with_minimal_config(self):
        daemon = Daemon(_config())
        await daemon.start()
        assert daemon.router is not None
        assert daemon.router.router_name == "bridge.test.example.net"
        await daemon.stop()

    async def test_router_online_posted(self):
        daemon = Daemon(_config())
        await daemon.start()
        # Check that the control channel got a RouterOnline post
        from bridge.control_channel import RouterOnline
        posts = daemon.router.control_channel.posts_of_type(RouterOnline)
        assert len(posts) == 1
        assert posts[0].router_name == "bridge.test.example.net"
        assert posts[0].zone_description == "unit test zone"
        await daemon.stop()


class TestNailedUpBridges:
    async def test_bridges_activated_on_start(self):
        cfg = _config(bridges=[
            {"name": "weather", "secret": "aa" * 16, "channel_idx": 3},
            {"name": "emergency", "secret": "bb" * 16, "channel_idx": 4},
        ])
        daemon = Daemon(cfg)
        await daemon.start()

        # Both channels should be registered
        assert daemon.router.channels.is_registered(
            daemon.router._derive_channel_hash("weather", b"\xaa" * 16)
        )
        assert daemon.router.channels.is_registered(
            daemon.router._derive_channel_hash("emergency", b"\xbb" * 16)
        )
        # Indices should be recorded for in-channel notice routing
        weather_hash = daemon.router._derive_channel_hash("weather", b"\xaa" * 16)
        assert daemon.router.channels.index_for(weather_hash) == 3
        await daemon.stop()

    async def test_activation_notices_posted(self):
        cfg = _config(bridges=[
            {"name": "weather", "secret": "aa" * 16, "channel_idx": 3},
        ])
        daemon = Daemon(cfg)
        await daemon.start()

        from bridge.control_channel import BridgeActivationNotice
        notices = daemon.router.control_channel.posts_of_type(BridgeActivationNotice)
        assert len(notices) == 1
        assert notices[0].event == "activate"
        assert notices[0].expires_at is None   # nailed-up = persistent
        await daemon.stop()


class TestPeerSeeding:
    async def test_peers_from_config_in_registry(self):
        cfg = _config(peers=[
            {
                "router_name": "bridge.sea.example.net",
                "identity_hash": "aa" * 16,
            },
            {
                "router_name": "bridge.pdx.example.net",
                "identity_hash": "bb" * 16,
            },
        ])
        daemon = Daemon(cfg)
        await daemon.start()

        peers = daemon.router.peers.incumbents()
        assert len(peers) == 2
        assert bytes.fromhex("aa" * 16) in peers
        assert bytes.fromhex("bb" * 16) in peers
        await daemon.stop()


class TestShutdown:
    async def test_stop_cleanly_ends_run(self):
        daemon = Daemon(_config())
        await daemon.start()

        async def run_then_stop():
            await asyncio.sleep(0.01)
            await daemon.stop()

        await asyncio.gather(
            daemon.run(),
            run_then_stop(),
        )

    async def test_request_shutdown_signals_run_loop(self):
        daemon = Daemon(_config())
        await daemon.start()

        async def trigger():
            await asyncio.sleep(0.01)
            daemon.request_shutdown()

        # run() should return shortly after request_shutdown
        await asyncio.gather(daemon.run(), trigger())
        await daemon.stop()
