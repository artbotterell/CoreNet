"""CoreNet addressing: @callsign@region grammar per spec §5.

Parses and formats the canonical CoreNet address form used in DMs to routers
and in auto-prefixed inbound deliveries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Spec §5.2 grammar
_CALLSIGN    = r"[A-Za-z0-9_/\-]{1,32}"
_TAG         = r"[A-Za-z0-9_\-]{1,16}"
_FQRN        = r"[A-Za-z0-9_\-.]{1,64}"
_ROUTER_NAME = rf"(?:{_FQRN})"  # tag is a subset of fqrn so one regex handles both

# Outbound: "@callsign@router-name" at start of message, optional trailing space
_OUTBOUND_RE = re.compile(
    rf"^@({_CALLSIGN})@({_ROUTER_NAME})(?:\s(.*))?$",
    re.DOTALL,
)

# Inbound prefix: "[@callsign@router-name] " at start of message
_INBOUND_RE = re.compile(
    rf"^\[@({_CALLSIGN})@({_ROUTER_NAME})\]\s?(.*)$",
    re.DOTALL,
)


@dataclass(frozen=True)
class CoreNetAddress:
    """Parsed CoreNet address."""
    callsign: str
    router_name: str

    def qualified(self) -> str:
        """Canonical @callsign@router form."""
        return f"@{self.callsign}@{self.router_name}"

    def matches_callsign(self, other: str) -> bool:
        """Case-insensitive callsign match per spec §5.2."""
        return self.callsign.casefold() == other.casefold()


@dataclass(frozen=True)
class ParsedOutbound:
    """Result of parsing a user's outbound DM."""
    address: CoreNetAddress
    body: str


def parse_outbound(text: str) -> ParsedOutbound | None:
    """Parse an outbound DM for a leading `@callsign@router-name` prefix.

    Returns a ParsedOutbound if the message starts with a valid address, else
    None (in which case the text should be treated as a command or error per
    spec §9.1).
    """
    if not text.startswith("@"):
        return None
    m = _OUTBOUND_RE.match(text)
    if m is None:
        return None
    callsign, router_name, body = m.group(1), m.group(2), m.group(3) or ""
    return ParsedOutbound(
        address=CoreNetAddress(callsign=callsign, router_name=router_name),
        body=body,
    )


@dataclass(frozen=True)
class ParsedInbound:
    """Result of parsing an inbound delivery's auto-prefix."""
    source: CoreNetAddress
    body: str


def format_inbound(source: CoreNetAddress, body: str) -> str:
    """Format an inbound delivery with the `[@callsign@router]` prefix (spec §9.2)."""
    return f"[{source.qualified()}] {body}"


def parse_inbound(text: str) -> ParsedInbound | None:
    """Parse an inbound-formatted message; inverse of format_inbound.

    Used by CoreNet-aware clients (and tests) to extract the source address
    from a router-delivered DM.
    """
    m = _INBOUND_RE.match(text)
    if m is None:
        return None
    return ParsedInbound(
        source=CoreNetAddress(callsign=m.group(1), router_name=m.group(2)),
        body=m.group(3) or "",
    )


def is_valid_callsign(s: str) -> bool:
    return bool(re.fullmatch(_CALLSIGN, s))


def is_valid_router_name(s: str) -> bool:
    return bool(re.fullmatch(_ROUTER_NAME, s))
