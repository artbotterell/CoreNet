"""Tests for bridge/addressing.py — @callsign@region grammar per spec §5."""
from __future__ import annotations

import pytest

from bridge.addressing import (
    CoreNetAddress,
    format_inbound,
    is_valid_callsign,
    is_valid_router_name,
    parse_inbound,
    parse_outbound,
)


class TestParseOutbound:
    def test_short_tag(self):
        r = parse_outbound("@KD6O@SEA hello world")
        assert r is not None
        assert r.address.callsign == "KD6O"
        assert r.address.router_name == "SEA"
        assert r.body == "hello world"

    def test_fqrn(self):
        r = parse_outbound("@KD6O@bridge.sea.example.net hey")
        assert r is not None
        assert r.address.router_name == "bridge.sea.example.net"

    def test_no_prefix_returns_none(self):
        assert parse_outbound("just a normal message") is None

    def test_malformed_prefix_returns_none(self):
        # Single @ at front is the command convention, not an address
        assert parse_outbound("@invalid without second at") is None

    def test_missing_body_is_empty(self):
        r = parse_outbound("@KD6O@SEA")
        assert r is not None
        assert r.body == ""

    def test_preserves_utf8_body(self):
        r = parse_outbound("@KD6O@SEA héllo")
        assert r is not None
        assert r.body == "héllo"

    def test_multiline_body(self):
        r = parse_outbound("@KD6O@SEA line one\nline two")
        assert r is not None
        assert r.body == "line one\nline two"

    def test_hyphen_and_digit_in_callsign(self):
        r = parse_outbound("@W7ABC-1@PDX test")
        assert r is not None
        assert r.address.callsign == "W7ABC-1"

    def test_slash_in_callsign(self):
        # Hams use suffixes like KD6O/M for mobile
        r = parse_outbound("@KD6O/M@SEA test")
        assert r is not None
        assert r.address.callsign == "KD6O/M"

    def test_callsign_max_length(self):
        # Exactly 32 chars is valid
        c = "A" * 32
        r = parse_outbound(f"@{c}@SEA x")
        assert r is not None
        assert r.address.callsign == c

    def test_callsign_over_max_length_fails(self):
        c = "A" * 33
        r = parse_outbound(f"@{c}@SEA x")
        assert r is None

    def test_router_name_with_hyphens(self):
        r = parse_outbound("@KD6O@US-WA hey")
        assert r is not None
        assert r.address.router_name == "US-WA"

    def test_router_name_with_underscores(self):
        r = parse_outbound("@KD6O@bridge_lax hey")
        assert r is not None
        assert r.address.router_name == "bridge_lax"


class TestFormatInbound:
    def test_basic_format(self):
        addr = CoreNetAddress(callsign="W5XYZ", router_name="LAX")
        assert format_inbound(addr, "hi there") == "[@W5XYZ@LAX] hi there"

    def test_round_trip(self):
        original = "[@KD6O@SEA] hello from up north"
        parsed = parse_inbound(original)
        assert parsed is not None
        assert format_inbound(parsed.source, parsed.body) == original


class TestParseInbound:
    def test_basic(self):
        r = parse_inbound("[@KD6O@SEA] hey there")
        assert r is not None
        assert r.source.callsign == "KD6O"
        assert r.source.router_name == "SEA"
        assert r.body == "hey there"

    def test_no_brackets_returns_none(self):
        assert parse_inbound("@KD6O@SEA no brackets") is None

    def test_missing_space_after_bracket(self):
        # Spec uses "[@addr] body" with a space; tolerant parser also accepts no space
        r = parse_inbound("[@KD6O@SEA]body")
        assert r is not None
        assert r.body == "body"


class TestCaseSensitivity:
    def test_callsign_match_is_case_insensitive(self):
        addr = CoreNetAddress(callsign="KD6O", router_name="SEA")
        assert addr.matches_callsign("kd6o")
        assert addr.matches_callsign("Kd6O")
        assert not addr.matches_callsign("W7ABC")


class TestValidators:
    def test_valid_callsigns(self):
        for c in ["KD6O", "W7ABC", "W7ABC-1", "KD6O/M", "test_user", "abc"]:
            assert is_valid_callsign(c), c

    def test_invalid_callsigns(self):
        for c in ["", "A" * 33, "with space", "with.dot", "with@at"]:
            assert not is_valid_callsign(c), c

    def test_valid_router_names(self):
        for r in ["SEA", "US-WA", "bridge.lax.example.net", "a", "x" * 64]:
            assert is_valid_router_name(r), r

    def test_invalid_router_names(self):
        for r in ["", "x" * 65, "with space", "has@at"]:
            assert not is_valid_router_name(r), r
