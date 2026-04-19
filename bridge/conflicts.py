"""Identity conflict detection (spec §10).

Tracks peer router identities by hash.  A conflict exists when two peer
announcements share the same identity hash but have different identity public
keys.  On detection, the incumbent is retained, the latecomer is refused, and
a signed conflict report is produced for publication on the control channel.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class PeerAnnounce:
    """One router's announce: the minimum the conflict detector needs."""
    identity_hash: bytes          # truncated hash of the pubkey
    public_key: bytes             # full public key (distinguishes collisions)
    router_name: str              # fqrn or tag
    observed_at: float = 0.0      # Unix timestamp


@dataclass(frozen=True)
class ConflictReport:
    """Structured conflict event ready to be published on the control channel."""
    identity_hash: bytes
    incumbent: PeerAnnounce
    latecomer: PeerAnnounce
    reporting_router: str         # posting router's name

    def fingerprint_hex(self, pubkey: bytes, chars: int = 8) -> str:
        """Short hex fingerprint of a pubkey for human comparison."""
        return pubkey.hex()[:chars]

    def format_report(self) -> str:
        """Human-readable form per spec §10.3 example."""
        hash_fp = self.identity_hash.hex()[:8]
        inc_fp = self.fingerprint_hex(self.incumbent.public_key)
        late_fp = self.fingerprint_hex(self.latecomer.public_key)
        return (
            f"[CoreNet] Identity conflict at {self.reporting_router}:\n"
            f"  hash {hash_fp} —\n"
            f"    pubkey fp {inc_fp} "
            f"(seen {_fmt_ts(self.incumbent.observed_at)} via {self.incumbent.router_name}) "
            f"[retained]\n"
            f"    pubkey fp {late_fp} "
            f"(seen {_fmt_ts(self.latecomer.observed_at)} via {self.latecomer.router_name}) "
            f"[refused]"
        )


def _fmt_ts(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%H:%M:%SZ")


class PeerRegistry:
    """Tracks incumbent peers by hash and detects conflicts on new announces.

    On `observe()`, returns the current state:
      - `first_seen` — new peer; accept and federate
      - `known` — re-observing an incumbent; update timestamp
      - `conflict` — another pubkey claims the same hash; refuse
    """

    def __init__(self, reporting_router: str, dedup_window: float = 3600.0) -> None:
        self._incumbents: dict[bytes, PeerAnnounce] = {}
        self._refused: dict[bytes, PeerAnnounce] = {}
        self._reported: dict[bytes, float] = {}     # hash → last report timestamp
        self.reporting_router = reporting_router
        self.dedup_window = dedup_window

    def observe(self, announce: PeerAnnounce) -> tuple[str, ConflictReport | None]:
        """Record an observed announce.

        Returns:
          ("first_seen", None)   — first time we've seen this hash; incumbent set.
          ("known", None)        — incumbent re-observed; nothing to do.
          ("conflict", report)   — hash collision with a different pubkey; caller
                                   should refuse federation with the latecomer
                                   and publish the report if not deduped.
        """
        incumbent = self._incumbents.get(announce.identity_hash)
        if incumbent is None:
            self._incumbents[announce.identity_hash] = announce
            return "first_seen", None

        if incumbent.public_key == announce.public_key:
            # Same identity — just a re-announce.  Update timestamp.
            self._incumbents[announce.identity_hash] = PeerAnnounce(
                identity_hash=incumbent.identity_hash,
                public_key=incumbent.public_key,
                router_name=incumbent.router_name,
                observed_at=announce.observed_at or time.time(),
            )
            return "known", None

        # Conflict: same hash, different pubkey
        self._refused[announce.identity_hash] = announce
        report = ConflictReport(
            identity_hash=announce.identity_hash,
            incumbent=incumbent,
            latecomer=announce,
            reporting_router=self.reporting_router,
        )
        return "conflict", report

    def should_publish_report(self, h: bytes, *, now: float | None = None) -> bool:
        """Dedup check per spec §10.3: don't re-publish the same conflict within the window."""
        t = time.time() if now is None else now
        last = self._reported.get(h)
        if last is None or (t - last) >= self.dedup_window:
            self._reported[h] = t
            return True
        return False

    def incumbents(self) -> dict[bytes, PeerAnnounce]:
        return dict(self._incumbents)

    def refused(self) -> dict[bytes, PeerAnnounce]:
        return dict(self._refused)
