"""Tests for bridge/manifest.py — spec §7.4 manifest structure, §11 privacy."""
from __future__ import annotations

import pytest

from bridge.manifest import (
    DEFAULT_POSITION_PRECISION_UDEG,
    OPT_IN_POSITION,
    OPT_IN_RECENT_ONLY,
    OPT_IN_TELEMETRY,
    OPT_IN_WIDE_AREA,
    ContactInput,
    Manifest,
    ManifestEntry,
    build_manifest,
    reduce_position,
)


PUBKEY_A = b"\x01" * 32
PUBKEY_B = b"\x02" * 32
PUBKEY_C = b"\x03" * 32


class TestReducePosition:
    def test_default_precision_is_1km(self):
        # 37.774000°, -122.431000° with 5-digit precision (10 µdeg)
        lat, lon = reduce_position(37_774_123, -122_431_456)
        # Truncated to nearest 10 µdeg
        assert lat == 37_774_120
        assert lon == -122_431_460

    def test_100m_precision(self):
        lat, lon = reduce_position(37_774_123, -122_431_456, precision_udeg=1)
        # 6-digit precision keeps full µdeg
        assert lat == 37_774_123
        assert lon == -122_431_456

    def test_coarse_precision(self):
        lat, lon = reduce_position(37_774_123, -122_431_456, precision_udeg=100_000)
        # ~10km grid
        assert lat == 37_700_000
        assert lon == -122_500_000

    def test_invalid_precision_raises(self):
        with pytest.raises(ValueError):
            reduce_position(0, 0, precision_udeg=0)


class TestOptInGate:
    def test_wide_area_opt_out_excluded(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="PrivateNode",
                last_seen=1000,
                opt_in_flags=0,  # no wide-area flag
            )
        ]
        m = build_manifest(contacts, router_name="bridge", timestamp=2000)
        assert m.entries == ()

    def test_wide_area_opt_in_included(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="PublicNode",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA,
            )
        ]
        m = build_manifest(contacts, router_name="bridge", timestamp=2000)
        assert len(m.entries) == 1
        assert m.entries[0].display_name == "PublicNode"


class TestPositionOptIn:
    def test_position_excluded_without_flag(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="NoPos",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA,
                lat_udeg=37_774_123,
                lon_udeg=-122_431_456,
            )
        ]
        m = build_manifest(contacts, router_name="bridge", timestamp=2000)
        entry = m.entries[0]
        assert entry.lat_udeg is None
        assert entry.lon_udeg is None

    def test_position_included_with_flag_and_precision_reduced(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="Pos",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA | OPT_IN_POSITION,
                lat_udeg=37_774_123,
                lon_udeg=-122_431_456,
            )
        ]
        m = build_manifest(contacts, router_name="bridge", timestamp=2000)
        entry = m.entries[0]
        # Default precision is 10 µdeg
        assert entry.lat_udeg == 37_774_120
        assert entry.lon_udeg == -122_431_460

    def test_position_flag_without_coords(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="Pos",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA | OPT_IN_POSITION,
                lat_udeg=None,
                lon_udeg=None,
            )
        ]
        m = build_manifest(contacts, router_name="bridge", timestamp=2000)
        entry = m.entries[0]
        assert entry.lat_udeg is None


class TestRecentOnlyFilter:
    def test_recent_included(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="Recent",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA | OPT_IN_RECENT_ONLY,
            )
        ]
        # Manifest built 2 hours after last_seen — within default 24h
        m = build_manifest(contacts, router_name="bridge", timestamp=1000 + 7200)
        assert len(m.entries) == 1

    def test_stale_excluded(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="Stale",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA | OPT_IN_RECENT_ONLY,
            )
        ]
        # Manifest built 25 hours after last_seen — past default threshold
        m = build_manifest(
            contacts, router_name="bridge", timestamp=1000 + 25 * 3600
        )
        assert m.entries == ()

    def test_recent_only_off_includes_stale(self):
        contacts = [
            ContactInput(
                public_key=PUBKEY_A,
                display_name="Stale",
                last_seen=1000,
                opt_in_flags=OPT_IN_WIDE_AREA,
            )
        ]
        m = build_manifest(
            contacts, router_name="bridge", timestamp=1000 + 25 * 3600
        )
        assert len(m.entries) == 1


class TestManifestBuilderMixed:
    def test_filters_opt_out_keeps_opt_in(self):
        contacts = [
            ContactInput(PUBKEY_A, "OptIn", 1000, OPT_IN_WIDE_AREA),
            ContactInput(PUBKEY_B, "OptOut", 1000, 0),
            ContactInput(PUBKEY_C, "AlsoIn", 1000, OPT_IN_WIDE_AREA | OPT_IN_TELEMETRY),
        ]
        m = build_manifest(contacts, router_name="bridge", timestamp=2000)
        names = {e.display_name for e in m.entries}
        assert names == {"OptIn", "AlsoIn"}

    def test_router_name_set_on_entries(self):
        contacts = [
            ContactInput(PUBKEY_A, "Node", 1000, OPT_IN_WIDE_AREA),
        ]
        m = build_manifest(contacts, router_name="bridge.lax.example.net", timestamp=2000)
        assert m.entries[0].router_name == "bridge.lax.example.net"


class TestManifestFilter:
    def test_filter_by_region(self):
        m = Manifest(
            router_name="bridge.lax.example.net",
            timestamp=2000,
            entries=(
                ManifestEntry(PUBKEY_A, "KD6O",   "LAX", 1000, OPT_IN_WIDE_AREA),
                ManifestEntry(PUBKEY_B, "W7ABC",  "SEA", 1000, OPT_IN_WIDE_AREA),
                ManifestEntry(PUBKEY_C, "N2XYZ",  "LAX", 1000, OPT_IN_WIDE_AREA),
            ),
        )
        filtered = m.filter_by_region("LAX")
        assert len(filtered.entries) == 2
        assert all(e.router_name == "LAX" for e in filtered.entries)

    def test_filter_empty_for_unknown_region(self):
        m = Manifest(
            router_name="bridge.example.net",
            timestamp=2000,
            entries=(ManifestEntry(PUBKEY_A, "KD6O", "LAX", 1000, OPT_IN_WIDE_AREA),),
        )
        assert m.filter_by_region("UNKNOWN").entries == ()

    def test_filter_case_insensitive(self):
        m = Manifest(
            router_name="bridge.example.net",
            timestamp=2000,
            entries=(ManifestEntry(PUBKEY_A, "KD6O", "LAX", 1000, OPT_IN_WIDE_AREA),),
        )
        assert len(m.filter_by_region("lax").entries) == 1
