"""Control channel (`corenet-ctl`) message types and discipline.

Per spec §6, routers post signed messages to the control channel for:

- Router online announcement (§7.2)
- Roster summary (§7.3)
- Bridge activation notice (§8.2.3)
- Identity conflict report (§10.3)

This module defines the typed post dataclasses and a helper that enforces the
hash-only rule for channel references (§6.4, §11.6).  The actual wire
transport is delegated to the bridge's LXMF transport; tests use mock
channels to observe posts.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Union

from bridge.conflicts import ConflictReport


# ---------------------------------------------------------------------------
# Post types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouterOnline:
    """Spec §7.2 — posted when a router starts up or reconnects."""
    router_name: str
    short_tag: str | None
    identity_fingerprint: str
    zone_description: str
    timestamp: float = field(default_factory=time.time)

    def format(self) -> str:
        tag = f" ({self.short_tag})" if self.short_tag else ""
        return (
            f"[CoreNet] router online: {self.router_name}{tag} "
            f"[{self.identity_fingerprint}] — {self.zone_description}"
        )


@dataclass(frozen=True)
class BridgeActivationNotice:
    """Spec §8.2.3 — posted on bridge activation or expiration.

    Channel is identified by HASH only per §6.4 and §8.2.3.  Never by name.
    """
    event: str                     # "activate" or "expire"
    channel_hash: bytes            # spec: hash only, never name
    router_name: str               # posting router
    expires_at: float | None       # None or timestamp; "persistent" for nailed-up
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.event not in ("activate", "expire"):
            raise ValueError(f"event must be 'activate' or 'expire', got {self.event!r}")

    def format(self) -> str:
        hash_fp = self.channel_hash.hex()[:8]
        if self.event == "activate":
            if self.expires_at is None:
                trailer = "persistent"
            else:
                trailer = f"expires {_fmt_ts(self.expires_at)}"
            return (
                f"[CoreNet] activate: hash {hash_fp} by {self.router_name}, {trailer}"
            )
        return f"[CoreNet] expire: hash {hash_fp} by {self.router_name}"


@dataclass(frozen=True)
class RosterSummary:
    """Spec §7.3 — periodic push of roster count.

    Per §11.4, contains NO node callsigns and NO user identities.  Just counts
    and a pointer to the pull query for detail.
    """
    router_name: str
    visible_count: int
    timestamp: float = field(default_factory=time.time)

    def format(self) -> str:
        return (
            f"[CoreNet] roster at {self.router_name}: "
            f"{self.visible_count} remote nodes visible — DM 'who' for detail"
        )


@dataclass(frozen=True)
class ConflictReportPost:
    """Spec §10.3 — conflict report.  Wraps the ConflictReport from conflicts.py."""
    report: ConflictReport
    timestamp: float = field(default_factory=time.time)

    def format(self) -> str:
        return self.report.format_report()


ControlPost = Union[
    RouterOnline, BridgeActivationNotice, RosterSummary, ConflictReportPost
]


# ---------------------------------------------------------------------------
# Discipline enforcement
# ---------------------------------------------------------------------------

def post_contains_channel_name(post_text: str, channel_names: list[str]) -> bool:
    """Sanity-check that a post text does not embed any known channel name.

    Routers MUST NOT emit channel names on corenet-ctl (spec §6.4, §8.1, §11.6).
    This helper is used in tests and can be invoked by a strict router before
    publishing as a belt-and-suspenders guard.
    """
    for name in channel_names:
        if name and name in post_text:
            return True
    return False


# ---------------------------------------------------------------------------
# Mock control channel for tests
# ---------------------------------------------------------------------------

class MockControlChannel:
    """In-memory control channel for tests.

    Records all posts and validates discipline constraints:
      - Every post must be a ControlPost instance
      - Post text must not contain any registered channel name
    """

    def __init__(self) -> None:
        self.posts: list[ControlPost] = []
        self._known_channel_names: list[str] = []

    def register_channel_name(self, name: str) -> None:
        """Tell the mock about a channel name so it can guard against leaks."""
        self._known_channel_names.append(name)

    def publish(self, post: ControlPost) -> None:
        if not isinstance(
            post,
            (RouterOnline, BridgeActivationNotice, RosterSummary, ConflictReportPost),
        ):
            raise TypeError(f"Not a ControlPost: {type(post)}")

        text = post.format()
        if post_contains_channel_name(text, self._known_channel_names):
            leaked = [n for n in self._known_channel_names if n in text]
            raise AssertionError(
                f"Control-channel post leaked channel name(s) {leaked!r}: {text!r}"
            )
        self.posts.append(post)

    # Convenience accessors for tests
    def posts_of_type(self, cls) -> list:
        return [p for p in self.posts if isinstance(p, cls)]


def _fmt_ts(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
