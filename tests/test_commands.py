"""Tests for bridge/commands.py — router command parser per spec §7, §8.2.2."""
from __future__ import annotations

import pytest

from bridge.commands import (
    BridgeActivate,
    BridgeStatus,
    ChannelsQuery,
    Unbridge,
    WhoQuery,
    parse_command,
    parse_duration,
)


class TestParseDuration:
    def test_bare_number_is_minutes(self):
        assert parse_duration("30") == 30 * 60

    def test_minutes_suffix(self):
        assert parse_duration("30m") == 30 * 60

    def test_hours_suffix(self):
        assert parse_duration("2h") == 2 * 3600

    def test_days_suffix(self):
        assert parse_duration("30d") == 30 * 86400

    def test_zero(self):
        assert parse_duration("0") == 0

    def test_invalid_returns_none(self):
        for bad in ["", "abc", "30s", "m30", "30 m", "-5m"]:
            assert parse_duration(bad) is None, bad


class TestWhoQuery:
    def test_bare(self):
        assert parse_command("who") == WhoQuery(filter=None)

    def test_with_filter(self):
        assert parse_command("who SEA") == WhoQuery(filter="SEA")

    def test_callsign_filter(self):
        assert parse_command("who KD6O") == WhoQuery(filter="KD6O")

    def test_case_insensitive_keyword(self):
        assert parse_command("WHO") == WhoQuery(filter=None)
        assert parse_command("Who SEA") == WhoQuery(filter="SEA")

    def test_preserves_arg_case(self):
        # Callsigns are compared case-insensitively by the resolver, but
        # the parser preserves case as typed.
        assert parse_command("who kd6o") == WhoQuery(filter="kd6o")

    def test_too_many_args(self):
        assert parse_command("who SEA extra") is None


class TestChannelsQuery:
    def test_bare(self):
        assert parse_command("channels") == ChannelsQuery(region=None)

    def test_with_region(self):
        assert parse_command("channels SEA") == ChannelsQuery(region="SEA")

    def test_too_many_args(self):
        assert parse_command("channels SEA extra") is None


class TestBridgeActivate:
    def test_basic(self):
        cmd = parse_command("bridge corenet-wa 30m")
        assert cmd == BridgeActivate(
            channel_name="corenet-wa", duration_seconds=30 * 60, regions=None
        )

    def test_hours(self):
        cmd = parse_command("bridge weather 2h")
        assert cmd == BridgeActivate(
            channel_name="weather", duration_seconds=2 * 3600, regions=None
        )

    def test_bare_number_is_minutes(self):
        cmd = parse_command("bridge weather 30")
        assert cmd == BridgeActivate(
            channel_name="weather", duration_seconds=30 * 60, regions=None
        )

    def test_scoped_single_region(self):
        cmd = parse_command("bridge emergency 1h to SEA")
        assert cmd == BridgeActivate(
            channel_name="emergency",
            duration_seconds=3600,
            regions=("SEA",),
        )

    def test_scoped_multiple_regions(self):
        cmd = parse_command("bridge emergency 1h to SEA,PDX,NYC")
        assert cmd == BridgeActivate(
            channel_name="emergency",
            duration_seconds=3600,
            regions=("SEA", "PDX", "NYC"),
        )

    def test_scoped_with_spaces(self):
        cmd = parse_command("bridge emergency 1h to SEA, PDX")
        assert cmd == BridgeActivate(
            channel_name="emergency",
            duration_seconds=3600,
            regions=("SEA", "PDX"),
        )

    def test_missing_duration(self):
        assert parse_command("bridge weather") is None

    def test_malformed_duration(self):
        assert parse_command("bridge weather foo") is None

    def test_unknown_trailing_tokens(self):
        assert parse_command("bridge weather 30m foo") is None


class TestUnbridge:
    def test_basic(self):
        assert parse_command("unbridge corenet-wa") == Unbridge(channel_name="corenet-wa")

    def test_missing_arg(self):
        assert parse_command("unbridge") is None

    def test_too_many_args(self):
        assert parse_command("unbridge foo bar") is None


class TestBridgeStatus:
    def test_basic(self):
        assert parse_command("bridge-status") == BridgeStatus()

    def test_no_args_allowed(self):
        assert parse_command("bridge-status foo") is None


class TestNonMatches:
    def test_empty(self):
        assert parse_command("") is None

    def test_whitespace(self):
        assert parse_command("   ") is None

    def test_unknown_keyword(self):
        assert parse_command("hello world") is None

    def test_addressing_prefix_not_a_command(self):
        # @callsign@region should be handled by the addressing parser, not here
        assert parse_command("@KD6O@SEA hello") is None
