"""CoreNet router command parser.

Parses DM bodies intended as commands to the router itself (rather than
addressed messages for remote peers).  Commands covered:

- `who` / `who <region>` / `who <callsign>`  — roster query (spec §7.1)
- `channels` / `channels <region>`           — channels query (spec §7.4)
- `bridge <name> <duration>`                 — ad-hoc bridge activation (spec §8.2.2)
- `bridge <name> <duration> to <regions>`    — scoped ad-hoc bridge
- `unbridge <name>`                          — early termination
- `bridge-status`                            — list active bridges

Returns typed dataclasses for each parsed command, or None when the text does
not match any known command.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union


# ---------------------------------------------------------------------------
# Command dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WhoQuery:
    """who / who <filter>  — spec §7.1.

    `filter` is None for a bare `who`, else a string that may be either a
    router-name or a callsign.  The router resolves the ambiguity by looking
    it up against known regions and callsigns.
    """
    filter: str | None = None


@dataclass(frozen=True)
class ChannelsQuery:
    """channels / channels <region>  — spec §7.4."""
    region: str | None = None


@dataclass(frozen=True)
class BridgeActivate:
    """bridge <channel> <duration> [to <region-list>]  — spec §8.2.2."""
    channel_name: str
    duration_seconds: int
    regions: tuple[str, ...] | None = None   # None means all


@dataclass(frozen=True)
class Unbridge:
    """unbridge <channel>  — spec §8.2.2."""
    channel_name: str


@dataclass(frozen=True)
class BridgeStatus:
    """bridge-status  — spec §8.2.2."""
    pass


Command = Union[WhoQuery, ChannelsQuery, BridgeActivate, Unbridge, BridgeStatus]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^(\d+)([mhd]?)$")


def parse_duration(s: str) -> int | None:
    """Parse a duration like `30m`, `2h`, `30d`, or bare number (minutes).

    Returns seconds, or None if unparseable.
    """
    m = _DURATION_RE.fullmatch(s.strip())
    if m is None:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "m"
    scale = {"m": 60, "h": 3600, "d": 86400}[unit]
    return n * scale


def parse_command(text: str) -> Command | None:
    """Parse a DM body as a router command.

    Returns the typed command dataclass on match, else None.  Case-insensitive
    on the command keyword; case-preserving on arguments.
    """
    stripped = text.strip()
    if not stripped:
        return None

    tokens = stripped.split()
    keyword = tokens[0].casefold()

    if keyword == "who":
        if len(tokens) == 1:
            return WhoQuery(filter=None)
        if len(tokens) == 2:
            return WhoQuery(filter=tokens[1])
        return None   # too many args

    if keyword == "channels":
        if len(tokens) == 1:
            return ChannelsQuery(region=None)
        if len(tokens) == 2:
            return ChannelsQuery(region=tokens[1])
        return None

    if keyword == "bridge-status":
        if len(tokens) == 1:
            return BridgeStatus()
        return None

    if keyword == "unbridge":
        if len(tokens) == 2:
            return Unbridge(channel_name=tokens[1])
        return None

    if keyword == "bridge":
        # Minimum: `bridge <channel> <duration>`
        if len(tokens) < 3:
            return None
        channel = tokens[1]
        duration = parse_duration(tokens[2])
        if duration is None:
            return None

        # Optional: `to <region-list>`
        regions: tuple[str, ...] | None = None
        if len(tokens) >= 5 and tokens[3].casefold() == "to":
            region_str = " ".join(tokens[4:])
            regions = tuple(r.strip() for r in region_str.split(",") if r.strip())
        elif len(tokens) > 3:
            return None   # unrecognised trailing tokens

        return BridgeActivate(
            channel_name=channel,
            duration_seconds=duration,
            regions=regions,
        )

    return None
