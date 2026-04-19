"""Manifest publisher / consumer per spec §7.4, §11 (privacy).

A manifest is a router's list of local contacts that have opted in to
wide-area visibility.  Each entry carries:

- public_key
- display_name (callsign)
- position (precision-reduced, if opt-in bit is set)
- last_seen timestamp
- region_tag / router_name
- opt_in_flags

Manifests are published at `meshcore.bridge.<hash>` and pulled by peer
routers in response to a CMD_GET_CONTACTS equivalent.  This module handles
construction, filtering, and precision reduction; wire format and signature
are handled by the transport layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Opt-in flag bits (spec §7.3, §11.2)
OPT_IN_WIDE_AREA    = 0x01   # list callsign in wide-area manifests
OPT_IN_POSITION     = 0x02   # include position data
OPT_IN_TELEMETRY    = 0x04   # permit telemetry forwarding
OPT_IN_RECENT_ONLY  = 0x08   # include only if recently active


@dataclass(frozen=True)
class ManifestEntry:
    """One contact as published in the manifest."""
    public_key: bytes                 # 32 bytes
    display_name: str                 # up to 32 bytes
    router_name: str                  # the publishing router's fqrn or tag
    last_seen: int                    # Unix timestamp
    opt_in_flags: int
    lat_udeg: int | None = None       # microdegrees; None if position not shared
    lon_udeg: int | None = None


@dataclass(frozen=True)
class Manifest:
    """A router's complete set of published contacts."""
    router_name: str
    timestamp: int                    # when this manifest was built
    entries: tuple[ManifestEntry, ...] = field(default_factory=tuple)

    def filter_by_region(self, region: str) -> "Manifest":
        """Return a manifest whose entries all have the given region tag."""
        f = region.casefold()
        kept = tuple(
            e for e in self.entries
            if e.router_name.casefold() == f
        )
        return Manifest(
            router_name=self.router_name,
            timestamp=self.timestamp,
            entries=kept,
        )


# ---------------------------------------------------------------------------
# Position precision reduction (spec §11.3)
# ---------------------------------------------------------------------------

# Recommended default per spec §11.3: 5 decimal digits = ~1km resolution.
# 1 degree = 10^6 microdegrees; 5 digits = 10 microdegrees
DEFAULT_POSITION_PRECISION_UDEG = 10


def reduce_position(
    lat_udeg: int, lon_udeg: int, precision_udeg: int = DEFAULT_POSITION_PRECISION_UDEG
) -> tuple[int, int]:
    """Round coordinates to the given microdegree grid.

    With precision_udeg=10, this produces ~1km resolution (5 decimal digits).
    With precision_udeg=1, 6 decimal digits (~100m resolution, spec §11.3 max).
    """
    if precision_udeg <= 0:
        raise ValueError("precision_udeg must be positive")
    q = int(precision_udeg)
    return (
        (lat_udeg // q) * q,
        (lon_udeg // q) * q,
    )


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------

@dataclass
class ContactInput:
    """The minimum a contact source must provide to be considered for inclusion."""
    public_key: bytes
    display_name: str
    last_seen: int
    opt_in_flags: int
    lat_udeg: int | None = None
    lon_udeg: int | None = None


def build_manifest(
    contacts: list[ContactInput],
    *,
    router_name: str,
    timestamp: int,
    position_precision_udeg: int = DEFAULT_POSITION_PRECISION_UDEG,
    recent_threshold_seconds: int = 24 * 3600,
) -> Manifest:
    """Construct a Manifest from a list of local contacts.

    Enforces the privacy rules in spec §11:
      - Only contacts with OPT_IN_WIDE_AREA appear (§11.2).
      - Position included only if OPT_IN_POSITION, precision-reduced (§11.3).
      - OPT_IN_RECENT_ONLY drops contacts not seen within the threshold.
    """
    entries: list[ManifestEntry] = []
    for c in contacts:
        # Opt-in check (§11.2)
        if not (c.opt_in_flags & OPT_IN_WIDE_AREA):
            continue

        # Recent-only filter
        if c.opt_in_flags & OPT_IN_RECENT_ONLY:
            if (timestamp - c.last_seen) > recent_threshold_seconds:
                continue

        # Position handling (§11.3)
        lat_out: int | None = None
        lon_out: int | None = None
        if (c.opt_in_flags & OPT_IN_POSITION) and c.lat_udeg is not None and c.lon_udeg is not None:
            lat_out, lon_out = reduce_position(
                c.lat_udeg, c.lon_udeg, precision_udeg=position_precision_udeg
            )

        entries.append(ManifestEntry(
            public_key=c.public_key,
            display_name=c.display_name,
            router_name=router_name,
            last_seen=c.last_seen,
            opt_in_flags=c.opt_in_flags,
            lat_udeg=lat_out,
            lon_udeg=lon_out,
        ))

    return Manifest(
        router_name=router_name,
        timestamp=timestamp,
        entries=tuple(entries),
    )
