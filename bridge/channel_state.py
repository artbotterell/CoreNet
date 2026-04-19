"""Channel state tracking: publication state and loop prevention.

Per spec §8.3 (loop prevention) and §8.4 (publication state), this module
holds per-channel mutable state that the router consults when:

- Deciding whether to list a channel in a `channels` query response (publication state)
- Forwarding channel traffic between local RF and the wide-area transport (seen-tag set)

Publication state is driven by in-channel control messages of the form:
    ::corenet publish::
    ::corenet publish <duration>::
    ::corenet unpublish::
"""
from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Union


# ---------------------------------------------------------------------------
# Control message parsing (spec §8.4.1)
# ---------------------------------------------------------------------------

_PUBLISH_RE   = re.compile(r"^::corenet publish(?:\s+(\d+[mhd]?))?::$")
_UNPUBLISH_RE = re.compile(r"^::corenet unpublish::$")


@dataclass(frozen=True)
class PublishControl:
    """`::corenet publish::` or `::corenet publish <duration>::`."""
    duration_seconds: int | None = None   # None = persistent


@dataclass(frozen=True)
class UnpublishControl:
    """`::corenet unpublish::`."""
    pass


ControlMessage = Union[PublishControl, UnpublishControl]


def parse_control_message(text: str) -> ControlMessage | None:
    """Parse an in-channel control message; returns None for non-control text."""
    stripped = text.strip()

    m = _PUBLISH_RE.fullmatch(stripped)
    if m is not None:
        duration_str = m.group(1)
        if duration_str is None:
            return PublishControl(duration_seconds=None)
        from bridge.commands import parse_duration
        seconds = parse_duration(duration_str)
        if seconds is None:
            return None
        return PublishControl(duration_seconds=seconds)

    if _UNPUBLISH_RE.fullmatch(stripped):
        return UnpublishControl()

    return None


# ---------------------------------------------------------------------------
# Publication state (spec §8.4)
# ---------------------------------------------------------------------------

@dataclass
class PublicationState:
    """Current publication state of one channel.

    `expires_at` is a Unix timestamp; None means persistent.  When
    is_published() is queried and expiration has passed, state reverts to
    unpublished automatically (spec §8.4.2).

    `source_timestamp` is the clock time of the control message that
    established this state, used for convergence when two routers gossip
    their states (spec §8.5.2 — latest-timestamp wins).
    """
    published: bool
    set_at: float
    expires_at: float | None = None
    source_timestamp: float = 0.0

    def is_published(self, now: float | None = None) -> bool:
        if not self.published:
            return False
        if self.expires_at is None:
            return True
        current = time.time() if now is None else now
        return current < self.expires_at


class ChannelRegistry:
    """Tracks publication state and seen-tag sets for all bridged channels.

    Keyed by channel hash (bytes) per spec §8.1.  The channel name is tracked
    alongside the state because the router needs it to respond to `channels`
    queries and to post human-readable notices.
    """

    def __init__(self, seen_tag_ttl: float = 60.0, seen_tag_max: int = 10000) -> None:
        self._state: dict[bytes, PublicationState] = {}
        self._names: dict[bytes, str] = {}
        self._indices: dict[bytes, int] = {}
        self._seen: OrderedDict[bytes, float] = OrderedDict()
        self._seen_ttl = seen_tag_ttl
        self._seen_max = seen_tag_max

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def register(
        self,
        channel_hash: bytes,
        channel_name: str,
        channel_idx: int | None = None,
    ) -> None:
        """Register a channel as bridged (by the operator or ad-hoc command).

        `channel_idx` is the local MeshCore radio's slot index for this channel
        (0-255), used when the bridge posts notices back into the channel via
        pack_send_channel_msg.  None means the bridge isn't tracking a radio
        index yet (mock / unit-test case).
        """
        self._names[channel_hash] = channel_name
        if channel_idx is not None:
            self._indices[channel_hash] = channel_idx
        # Unpublished by default (spec §8.4)
        if channel_hash not in self._state:
            self._state[channel_hash] = PublicationState(
                published=False, set_at=time.time()
            )

    def unregister(self, channel_hash: bytes) -> None:
        """Remove a channel from the registry (e.g., nailed-up bridge torn down)."""
        self._state.pop(channel_hash, None)
        self._names.pop(channel_hash, None)
        self._indices.pop(channel_hash, None)

    def name_for(self, channel_hash: bytes) -> str | None:
        return self._names.get(channel_hash)

    def index_for(self, channel_hash: bytes) -> int | None:
        return self._indices.get(channel_hash)

    def is_registered(self, channel_hash: bytes) -> bool:
        return channel_hash in self._names

    # ------------------------------------------------------------------
    # Publication state
    # ------------------------------------------------------------------

    def apply_control(
        self,
        channel_hash: bytes,
        control: ControlMessage,
        *,
        now: float | None = None,
        source_timestamp: float | None = None,
    ) -> None:
        """Apply a publish or unpublish control message to a channel.

        Per spec §8.4.2, the most recent valid control message wins.
        `source_timestamp` is the message's internal timestamp (used for
        gossip convergence); if omitted, `now` is used.
        """
        t = time.time() if now is None else now
        src_ts = source_timestamp if source_timestamp is not None else t

        if not self.is_registered(channel_hash):
            # Unknown channel — we're not bridging it, so the control is moot.
            return

        if isinstance(control, PublishControl):
            expires_at = (
                None if control.duration_seconds is None else t + control.duration_seconds
            )
            self._state[channel_hash] = PublicationState(
                published=True, set_at=t, expires_at=expires_at,
                source_timestamp=src_ts,
            )
        elif isinstance(control, UnpublishControl):
            self._state[channel_hash] = PublicationState(
                published=False, set_at=t, expires_at=None,
                source_timestamp=src_ts,
            )

    def get_state(self, channel_hash: bytes) -> PublicationState | None:
        """Return the current publication state, or None if not tracked."""
        return self._state.get(channel_hash)

    def is_published(self, channel_hash: bytes, *, now: float | None = None) -> bool:
        state = self._state.get(channel_hash)
        if state is None:
            return False
        return state.is_published(now)

    def published_channels(self, *, now: float | None = None) -> list[tuple[bytes, str]]:
        """Return [(hash, name), ...] for channels currently published."""
        return [
            (h, self._names[h])
            for h, state in self._state.items()
            if state.is_published(now) and h in self._names
        ]

    # ------------------------------------------------------------------
    # Loop prevention (spec §8.3)
    # ------------------------------------------------------------------

    def should_forward(self, tag: bytes, *, now: float | None = None) -> bool:
        """Check a channel message's tag against the seen set.

        Returns True if the tag is new (forward this message and remember it),
        False if the tag was seen recently (drop, it's a loop).
        """
        t = time.time() if now is None else now
        self._evict_expired_seen(t)
        if tag in self._seen:
            return False
        self._seen[tag] = t
        # Cap memory use
        while len(self._seen) > self._seen_max:
            self._seen.popitem(last=False)
        return True

    def _evict_expired_seen(self, now: float) -> None:
        threshold = now - self._seen_ttl
        # OrderedDict insertion order = timestamp order for our use
        while self._seen:
            oldest_tag, oldest_ts = next(iter(self._seen.items()))
            if oldest_ts < threshold:
                self._seen.popitem(last=False)
            else:
                break

    def seen_count(self) -> int:
        return len(self._seen)
