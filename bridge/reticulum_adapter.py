"""Reticulum/LXMF adapter: concrete LxmfTransportBase backed by RNS and LXMF.

Layered so that the message-conversion logic is pure-Python and unit-testable
without a Reticulum runtime, and the live transport wraps it with actual
RNS+LXMF I/O.  Applications that don't install the `rns` or `lxmf` packages
should import only the `conversion` helpers from this module.

Reference:
  - Reticulum: https://reticulum.network/
  - LXMF:      https://github.com/markqvist/LXMF
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from bridge.companion.types import LxmfDestType, LxmfTransport
from bridge.conflicts import PeerAnnounce
from bridge.lxmf_layer.transport import (
    FIELD_APP_DATA,
    FIELD_RAW_BINARY,
    FIELD_TEXT,
    LxmfMessage,
    LxmfTransportBase,
    MessageCallback,
)

# Key used inside FIELD_APP_DATA to carry the CoreNet destination aspect
# (node / bridge / channel) when that dict is the whole custom_data payload.
_CORENET_ASPECT_KEY = "_corenet_aspect"

PeerAnnounceCallback = Callable[[PeerAnnounce], Awaitable[None]]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure conversion (unit-testable, no RNS import required)
# ---------------------------------------------------------------------------

_TRANSPORT_METHOD_MAP_FORWARD: dict[LxmfTransport, int] = {
    # Numeric values come from LXMF.LXMessage.{OPPORTUNISTIC,DIRECT,PROPAGATED}
    # but we hold them as ints here so this module doesn't need LXMF imported.
    LxmfTransport.DIRECT:     2,   # LXMessage.DIRECT
    LxmfTransport.PROPAGATED: 3,   # LXMessage.PROPAGATED
    LxmfTransport.ANNOUNCE:   1,   # LXMessage.OPPORTUNISTIC
}
_TRANSPORT_METHOD_MAP_REVERSE: dict[int, LxmfTransport] = {
    v: k for k, v in _TRANSPORT_METHOD_MAP_FORWARD.items()
}


def parse_coretnet_destination(s: str) -> tuple[str, bytes]:
    """Parse "meshcore.{aspect}.{hex_hash}" into (aspect, hash_bytes).

    Raises ValueError on a malformed destination string.
    """
    parts = s.split(".", 2)
    if len(parts) != 3 or parts[0] != "meshcore":
        raise ValueError(f"Invalid CoreNet destination: {s!r}")
    aspect = parts[1]
    try:
        hash_bytes = bytes.fromhex(parts[2])
    except ValueError as e:
        raise ValueError(f"Invalid hex hash in {s!r}: {e}") from None
    return aspect, hash_bytes


def aspect_to_dest_type(aspect: str) -> LxmfDestType:
    mapping = {
        "node":    LxmfDestType.NODE,
        "bridge":  LxmfDestType.BRIDGE,
        "channel": LxmfDestType.CHANNEL,
    }
    if aspect not in mapping:
        raise ValueError(f"Unknown destination aspect: {aspect!r}")
    return mapping[aspect]


def dest_type_to_aspect(dt: LxmfDestType) -> str:
    return {
        LxmfDestType.NODE:    "node",
        LxmfDestType.BRIDGE:  "bridge",
        LxmfDestType.CHANNEL: "channel",
    }[dt]


@dataclass(frozen=True)
class OutboundParams:
    """All the pieces the live transport needs to build an LXMF LXMessage.

    Kept as a dataclass so tests can assert the conversion without touching RNS.
    """
    dest_aspect: str
    dest_hash: bytes
    content: str
    title: str
    custom_data: Any | None
    desired_method: int          # LXMF.LXMessage delivery method code


def _compose_custom_data(params: "OutboundParams") -> Any | None:
    """Build the custom_data payload including the CoreNet aspect.

    Keeps dict/bytes payloads distinguishable so the receiver can tell
    them apart.  The CoreNet aspect lands under _CORENET_ASPECT_KEY when
    the payload is (or becomes) a dict.
    """
    existing = params.custom_data
    if existing is None:
        return {_CORENET_ASPECT_KEY: params.dest_aspect}
    if isinstance(existing, dict):
        out = dict(existing)
        out[_CORENET_ASPECT_KEY] = params.dest_aspect
        return out
    # Binary or other non-dict payload — wrap in a dict to preserve the aspect.
    return {_CORENET_ASPECT_KEY: params.dest_aspect, "raw": existing}


def _extract_corenet_aspect(custom_data: Any) -> str:
    """Pull the CoreNet aspect out of inbound custom_data; default to 'node'."""
    if isinstance(custom_data, dict):
        aspect = custom_data.get(_CORENET_ASPECT_KEY)
        if isinstance(aspect, str) and aspect in ("node", "bridge", "channel"):
            return aspect
    return "node"


def _strip_corenet_aspect(custom_data: Any) -> Any:
    """Return custom_data with the aspect key removed, for handing to callers."""
    if not isinstance(custom_data, dict):
        return custom_data
    if _CORENET_ASPECT_KEY not in custom_data:
        return custom_data
    stripped = {k: v for k, v in custom_data.items() if k != _CORENET_ASPECT_KEY}
    # If only "raw" remains and we had wrapped a bytes payload, unwrap it.
    if set(stripped.keys()) == {"raw"}:
        return stripped["raw"]
    return stripped or None


def to_outbound_params(msg: LxmfMessage) -> OutboundParams:
    """Convert an LxmfMessage (the abstract form) into parameters for LXMF."""
    aspect, dest_hash = parse_coretnet_destination(msg.destination)
    content = msg.fields.get(FIELD_TEXT, "") if msg.fields else ""
    if not isinstance(content, str):
        content = ""

    app_data = msg.fields.get(FIELD_APP_DATA) if msg.fields else None
    raw_binary = msg.fields.get(FIELD_RAW_BINARY) if msg.fields else None

    # CoreNet app_data takes precedence; raw_binary rides alongside as bytes.
    custom: Any | None
    if app_data is not None and raw_binary is not None:
        custom = {"app_data": app_data, "raw": raw_binary}
    elif app_data is not None:
        custom = app_data
    elif raw_binary is not None:
        custom = raw_binary
    else:
        custom = None

    method = _TRANSPORT_METHOD_MAP_FORWARD.get(msg.transport, 1)

    return OutboundParams(
        dest_aspect=aspect,
        dest_hash=dest_hash,
        content=content,
        title=msg.title or "",
        custom_data=custom,
        desired_method=method,
    )


@dataclass(frozen=True)
class InboundParams:
    """The subset of LXMF LXMessage fields we consume."""
    content: str
    title: str
    custom_data: Any | None
    source_hash: bytes
    destination_hash: bytes
    destination_aspect: str
    desired_method: int


def to_lxmf_message(params: InboundParams) -> LxmfMessage:
    """Convert inbound LXMF parameters into our abstract LxmfMessage."""
    fields: dict = {}
    if params.content:
        fields[FIELD_TEXT] = params.content

    if isinstance(params.custom_data, dict) and "raw" in params.custom_data:
        # Packed by to_outbound_params when both app_data and raw were set
        if "app_data" in params.custom_data:
            fields[FIELD_APP_DATA] = params.custom_data["app_data"]
        fields[FIELD_RAW_BINARY] = params.custom_data["raw"]
    elif isinstance(params.custom_data, (bytes, bytearray)):
        fields[FIELD_RAW_BINARY] = bytes(params.custom_data)
    elif params.custom_data is not None:
        fields[FIELD_APP_DATA] = params.custom_data

    transport = _TRANSPORT_METHOD_MAP_REVERSE.get(params.desired_method, LxmfTransport.DIRECT)
    dest_type = aspect_to_dest_type(params.destination_aspect)
    destination = f"meshcore.{params.destination_aspect}.{params.destination_hash.hex()}"

    return LxmfMessage(
        transport=transport,
        dest_type=dest_type,
        destination=destination,
        title=params.title,
        fields=fields,
        source=params.source_hash.hex(),
    )


# ---------------------------------------------------------------------------
# Live transport — only importable when RNS/LXMF are installed
# ---------------------------------------------------------------------------

try:
    import RNS
    import LXMF
    _HAS_RETICULUM = True
except ImportError:   # pragma: no cover
    _HAS_RETICULUM = False


def is_reticulum_available() -> bool:
    """True if the live transport can be instantiated on this system."""
    return _HAS_RETICULUM


class ReticulumLxmfTransport(LxmfTransportBase):
    """Live LxmfTransportBase backed by Reticulum + LXMF.

    Lifecycle:
      adapter = ReticulumLxmfTransport(config_dir=..., identity_path=...)
      await adapter.start()
      ... use it ...
      await adapter.stop()

    All networking happens in Reticulum's threads; inbound callbacks are
    dispatched onto the event loop captured at start() time.
    """

    def __init__(
        self,
        *,
        config_dir: str | Path | None = None,
        identity_path: str | Path | None = None,
        storage_path: str | Path | None = None,
        display_name: str = "CoreNet Bridge",
    ) -> None:
        if not _HAS_RETICULUM:
            raise ImportError(
                "Reticulum (rns) and LXMF are required for ReticulumLxmfTransport; "
                "install with `pip install rns lxmf`."
            )
        self._config_dir = str(config_dir) if config_dir else None
        self._identity_path = str(identity_path) if identity_path else None
        self._storage_path = str(storage_path) if storage_path else None
        self._display_name = display_name
        self._reticulum: Any = None
        self._identity: Any = None
        self._router: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbound_callbacks: list[MessageCallback] = []
        self._announce_callbacks: list[PeerAnnounceCallback] = []
        self._announce_handler: Any = None

    @property
    def identity_hash(self) -> bytes:
        """The bridge's Reticulum identity hash (truncated to destination length)."""
        if self._identity is None:
            raise RuntimeError("transport not started")
        return self._identity.hash

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        # Reticulum expects configdir as a positional or keyword; None means default.
        self._reticulum = RNS.Reticulum(configdir=self._config_dir)
        self._identity = self._load_or_create_identity()
        self._router = LXMF.LXMRouter(
            identity=self._identity,
            storagepath=self._storage_path,
        )
        self._router.register_delivery_identity(
            self._identity, display_name=self._display_name
        )
        self._router.register_delivery_callback(self._on_lxmf_received)

        # Listen for LXMF delivery announces so we can notify callers of new peers
        self._announce_handler = _PeerAnnounceHandler(self)
        RNS.Transport.register_announce_handler(self._announce_handler)

    async def stop(self) -> None:
        if self._announce_handler is not None:
            try:
                RNS.Transport.deregister_announce_handler(self._announce_handler)
            except Exception as e:   # pragma: no cover
                log.debug("error deregistering announce handler: %s", e)
            self._announce_handler = None
        if self._router is not None:
            try:
                self._router.exit_handler()
            except Exception as e:   # pragma: no cover
                log.warning("error on LXMF router shutdown: %s", e)

    async def send(self, msg: LxmfMessage) -> None:
        if self._router is None or self._identity is None:
            raise RuntimeError("transport not started")
        params = to_outbound_params(msg)
        dest_identity = RNS.Identity.recall(params.dest_hash)
        if dest_identity is None:
            log.info(
                "no cached identity for %s; requesting path and deferring",
                params.dest_hash.hex(),
            )
            RNS.Transport.request_path(params.dest_hash)
            # LXMF will queue and retry once the identity is learned via
            # announce. Caller's retry logic (if any) handles the wait.
            return

        # All LXMF traffic rides on the "lxmf.delivery" destination aspect
        # (spec §13.1); the CoreNet destination type (node / bridge / channel)
        # is carried in the message's custom_data.
        outbound_dest = RNS.Destination(
            dest_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            LXMF.APP_NAME,
            "delivery",
        )

        # Compose custom_data: always include the CoreNet aspect, plus any
        # caller-provided app_data / raw_binary.
        custom_data = _compose_custom_data(params)
        fields = {LXMF.FIELD_CUSTOM_DATA: custom_data} if custom_data is not None else None

        lxm = LXMF.LXMessage(
            destination=outbound_dest,
            source=self._identity,
            content=params.content,
            title=params.title,
            fields=fields,
            desired_method=params.desired_method,
        )
        self._router.handle_outbound(lxm)

    async def announce(self, destination: str, app_data: bytes) -> None:
        if self._router is None:
            raise RuntimeError("transport not started")
        # For v0.1 we only announce our own identity; delegate to the LXMF router.
        self._router.announce(app_data=app_data)

    def add_inbound_callback(self, cb: MessageCallback) -> None:
        self._inbound_callbacks.append(cb)

    def add_announce_callback(self, cb: PeerAnnounceCallback) -> None:
        """Register a coroutine to be called for each LXMF delivery announce."""
        self._announce_callbacks.append(cb)

    def _on_peer_announce(
        self,
        destination_hash: bytes,
        announced_identity: Any,
        app_data: bytes | None,
    ) -> None:
        """Called from an RNS thread by _PeerAnnounceHandler."""
        try:
            pubkey = announced_identity.get_public_key()
            # LXMF's display-name-from-app-data helper is tolerant of None/empty
            display_name = ""
            if app_data is not None:
                try:
                    display_name = LXMF.display_name_from_app_data(app_data) or ""
                except Exception:
                    display_name = ""

            announce = PeerAnnounce(
                identity_hash=destination_hash,
                public_key=pubkey,
                router_name=display_name or destination_hash.hex()[:8],
                observed_at=time.time(),
            )
        except Exception as e:   # pragma: no cover
            log.error("failed to build PeerAnnounce: %s", e)
            return

        if self._loop is None:
            return

        for cb in list(self._announce_callbacks):
            asyncio.run_coroutine_threadsafe(cb(announce), self._loop)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_or_create_identity(self) -> Any:
        if self._identity_path and Path(self._identity_path).exists():
            return RNS.Identity.from_file(self._identity_path)
        identity = RNS.Identity()
        if self._identity_path:
            Path(self._identity_path).parent.mkdir(parents=True, exist_ok=True)
            identity.to_file(self._identity_path)
        return identity

    def _on_lxmf_received(self, lxm: Any) -> None:
        """Called from an RNS thread; convert and dispatch to the event loop."""
        try:
            custom_data = None
            if getattr(lxm, "fields", None):
                custom_data = lxm.fields.get(LXMF.FIELD_CUSTOM_DATA)
            # Extract the CoreNet aspect the sender embedded, then strip it so
            # it doesn't leak into caller-visible app_data.
            aspect = _extract_corenet_aspect(custom_data)
            cleaned_custom = _strip_corenet_aspect(custom_data)

            # LXMF stores destination hash on the message in different attrs
            # across versions; be defensive.
            dest_hash = (
                getattr(lxm, "destination_hash", None)
                or (lxm.destination.hash if getattr(lxm, "destination", None) else b"")
            )
            source_hash = (
                getattr(lxm, "source_hash", None)
                or (lxm.source.hash if getattr(lxm, "source", None) else b"")
            )
            params = InboundParams(
                content=lxm.content_as_string() if hasattr(lxm, "content_as_string") else (lxm.content or ""),
                title=getattr(lxm, "title", "") or "",
                custom_data=cleaned_custom,
                source_hash=source_hash,
                destination_hash=dest_hash,
                destination_aspect=aspect,
                desired_method=getattr(lxm, "desired_method", 2),
            )
            msg = to_lxmf_message(params)
        except Exception as e:   # pragma: no cover
            log.error("error converting inbound LXMF message: %s", e)
            return

        if self._loop is None:
            log.warning("no event loop captured; dropping inbound message")
            return

        for cb in list(self._inbound_callbacks):
            asyncio.run_coroutine_threadsafe(cb(msg), self._loop)


# ---------------------------------------------------------------------------
# Announce handler (duck-typed per RNS convention)
# ---------------------------------------------------------------------------

if _HAS_RETICULUM:

    class _PeerAnnounceHandler:
        """Forwards LXMF delivery announces to ReticulumLxmfTransport callbacks.

        Registered with RNS.Transport.register_announce_handler; RNS invokes
        `received_announce` from its own thread when a matching announce
        arrives.
        """

        aspect_filter = f"{LXMF.APP_NAME}.delivery"
        receive_path_responses = True

        def __init__(self, transport: "ReticulumLxmfTransport") -> None:
            self._transport = transport

        def received_announce(
            self,
            destination_hash: bytes,
            announced_identity: Any,
            app_data: bytes | None,
        ) -> None:
            # Ignore announces for our own identity
            try:
                if self._transport._identity is not None:
                    if destination_hash == self._transport._identity.hash:
                        return
            except Exception:
                pass
            self._transport._on_peer_announce(
                destination_hash, announced_identity, app_data
            )
