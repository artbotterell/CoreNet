"""Peer publication-state gossip (spec §8.5).

When two routers federate, they exchange current publication state for any
channels both of them bridge, so a late-joining router learns the state
without waiting for the next in-channel control message.

The protocol is a simple query/response pair carried over the wide-area
transport; this module defines the typed messages and a merge function
implementing the "latest timestamp wins" convergence rule (§8.5.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from bridge.channel_state import ChannelRegistry, PublicationState


@dataclass(frozen=True)
class StateQuery:
    """Sent from one router to a peer to request current state for channels."""
    channel_hashes: tuple[bytes, ...]


@dataclass(frozen=True)
class StateEntry:
    """One channel's current state, as reported by a peer."""
    channel_hash: bytes
    published: bool
    source_timestamp: float
    expires_at: float | None


@dataclass(frozen=True)
class StateResponse:
    """Response to a StateQuery.  Only channels the peer knows about are included."""
    entries: tuple[StateEntry, ...]


def build_response(
    registry: ChannelRegistry, query: StateQuery
) -> StateResponse:
    """Construct a StateResponse from a registry's current state."""
    entries: list[StateEntry] = []
    for h in query.channel_hashes:
        state = registry.get_state(h)
        if state is None:
            continue
        entries.append(StateEntry(
            channel_hash=h,
            published=state.published,
            source_timestamp=state.source_timestamp,
            expires_at=state.expires_at,
        ))
    return StateResponse(entries=tuple(entries))


def merge_response(
    registry: ChannelRegistry, response: StateResponse
) -> list[bytes]:
    """Merge a gossip response into the local registry.

    Returns the list of channel hashes whose state was updated (because the
    peer's source_timestamp was newer than ours).  Per spec §8.5.2, the
    router with the latest-timestamp control message wins.
    """
    updated: list[bytes] = []
    for entry in response.entries:
        if not registry.is_registered(entry.channel_hash):
            # We're not bridging this channel; can't verify or apply.
            continue
        local = registry.get_state(entry.channel_hash)
        local_ts = local.source_timestamp if local is not None else 0.0
        if entry.source_timestamp <= local_ts:
            continue
        # Peer's state is newer; adopt it
        registry._state[entry.channel_hash] = PublicationState(
            published=entry.published,
            set_at=entry.source_timestamp,
            expires_at=entry.expires_at,
            source_timestamp=entry.source_timestamp,
        )
        updated.append(entry.channel_hash)
    return updated
