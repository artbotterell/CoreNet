"""Routing logic for CoreNet bridges.

The Router holds no I/O — only decision logic — so it is fully testable
without a serial port or a Reticulum process.  It is the junction point where
MeshCore companion-protocol traffic, LXMF traffic, and CoreNet control-plane
events come together.

Responsibilities (per the v0.1 spec):

- Route outbound DMs either to the local radio or over LXMF (spec §9)
- Parse @callsign@region addresses in DMs sent to the bridge itself (§5, §9.1)
- Synthesise inbound LXMF deliveries as local radio DMs with [@source] prefix (§9.2)
- Dispatch router commands (`who`, `channels`, `bridge`, `unbridge`, `bridge-status`) (§7, §8.2.2)
- Intercept in-channel control messages (`::corenet publish::` / `::corenet unpublish::`) (§8.4)
- Enforce loop prevention on channel traffic (§8.3)
- Observe peer announces and detect identity conflicts (§10)
- Post signed notices to the control channel when appropriate (§6, §8.2.3, §10.3)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from bridge.addressing import (
    CoreNetAddress,
    format_inbound,
    parse_outbound,
)
from bridge.channel_state import (
    ChannelRegistry,
    PublishControl,
    UnpublishControl,
    parse_control_message,
)
from bridge.commands import (
    BridgeActivate,
    BridgeStatus,
    ChannelsQuery,
    Command,
    Unbridge,
    WhoQuery,
    parse_command,
)
from bridge.companion.protocol import (
    ChannelMessage,
    ContactMessage,
    pack_send_txt_msg,
)
from bridge.companion.types import CommandType, LxmfTransport, PacketType
from bridge.conflicts import PeerAnnounce, PeerRegistry
from bridge.control_channel import (
    BridgeActivationNotice,
    ConflictReportPost,
    MockControlChannel,
    RouterOnline,
)
from bridge.lxmf_layer import encoding as enc
from bridge.lxmf_layer.transport import LxmfMessage, LxmfTransportBase

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Contact registry
# ---------------------------------------------------------------------------

@dataclass
class ContactEntry:
    """One contact as seen by the router."""
    pubkey: bytes       # 32 bytes
    prefix: bytes       # first 6 bytes of pubkey
    display_name: str   # also serves as the CoreNet callsign
    lxmf_hash: str      # empty = local-only
    is_remote: bool
    router_name: str = ""   # for remote contacts: which peer router hosts them


class ContactRegistry:
    def __init__(self) -> None:
        self._by_prefix: dict[bytes, ContactEntry] = {}
        self._by_callsign: dict[str, ContactEntry] = {}  # case-folded key

    def add(self, entry: ContactEntry) -> None:
        self._by_prefix[entry.prefix] = entry
        self._by_callsign[entry.display_name.casefold()] = entry

    def get(self, prefix: bytes) -> ContactEntry | None:
        return self._by_prefix.get(prefix[:6])

    def by_callsign(self, callsign: str) -> ContactEntry | None:
        return self._by_callsign.get(callsign.casefold())

    def is_remote(self, prefix: bytes) -> bool:
        e = self.get(prefix)
        return e is not None and e.is_remote

    def lxmf_hash(self, prefix: bytes) -> str | None:
        e = self.get(prefix)
        return e.lxmf_hash if e and e.lxmf_hash else None

    def local_contacts(self) -> list[ContactEntry]:
        return [e for e in self._by_prefix.values() if not e.is_remote]

    def remote_contacts(self) -> list[ContactEntry]:
        return [e for e in self._by_prefix.values() if e.is_remote]


# ---------------------------------------------------------------------------
# Active bridge tracking
# ---------------------------------------------------------------------------

@dataclass
class ActiveBridge:
    """An active ad-hoc bridge; nailed-up bridges use expires_at=None."""
    channel_name: str
    channel_hash: bytes
    expires_at: float | None


# ---------------------------------------------------------------------------
# Transport protocols
# ---------------------------------------------------------------------------

class RadioTransport(Protocol):
    async def send_command(self, payload: bytes) -> None: ...


class AppTransport(Protocol):
    async def push_frame(self, payload: bytes) -> None: ...


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """Decision logic for a CoreNet bridge.

    Existing test suites drive this via `handle_app_command`, `handle_radio_push`,
    and inbound LXMF callbacks.  The CoreNet-specific mechanisms layer on as
    additional entry points: `handle_inbound_dm`, `handle_inbound_channel_msg`,
    `observe_peer_announce`, `activate_bridge`, and so on.
    """

    _PREFIX_COMMANDS = frozenset({
        CommandType.SEND_TXT_MSG,
        CommandType.ADD_UPDATE_CONTACT,
        CommandType.REMOVE_CONTACT,
        CommandType.RESET_PATH,
        CommandType.EXPORT_CONTACT,
        CommandType.SHARE_CONTACT,
    })

    def __init__(
        self,
        contacts: ContactRegistry,
        lxmf: LxmfTransportBase,
        local_hash: str,
        *,
        router_name: str = "bridge.local",
        short_tag: str | None = None,
        local_callsign: str = "BRIDGE",
        channels: ChannelRegistry | None = None,
        peers: PeerRegistry | None = None,
        control_channel: MockControlChannel | None = None,
        radio: RadioTransport | None = None,
        app: AppTransport | None = None,
        clock: "callable" = time.time,
    ) -> None:
        self.contacts = contacts
        self.lxmf = lxmf
        self.local_hash = local_hash
        self.router_name = router_name
        self.short_tag = short_tag or router_name
        self.local_callsign = local_callsign
        self.channels = channels if channels is not None else ChannelRegistry()
        self.peers = peers if peers is not None else PeerRegistry(router_name)
        self.control_channel = control_channel
        self.radio = radio
        self.app = app
        self._clock = clock
        self._active_bridges: dict[bytes, ActiveBridge] = {}
        lxmf.add_inbound_callback(self._on_lxmf_inbound)

    def attach(self, radio: RadioTransport, app: AppTransport) -> None:
        self.radio = radio
        self.app = app

    # ======================================================================
    # App → radio / LXMF path (existing behaviour; still used by current tests)
    # ======================================================================

    async def handle_app_command(self, payload: bytes) -> None:
        """Called for every frame received from the connected companion app."""
        if not payload:
            return
        cmd = CommandType(payload[0]) if payload[0] in CommandType._value2member_map_ else None

        if cmd == CommandType.SEND_TXT_MSG and len(payload) >= 7:
            dest_prefix = payload[1:7]
            text = payload[7:].decode("utf-8", errors="replace")
            if self.contacts.is_remote(dest_prefix):
                await self._route_dm_to_lxmf(dest_prefix, text)
                return

        if self.radio:
            await self.radio.send_command(payload)

    async def _route_dm_to_lxmf(self, dest_prefix: bytes, text: str) -> None:
        lxmf_hash = self.contacts.lxmf_hash(dest_prefix)
        if not lxmf_hash:
            log.warning("remote contact %s has no LXMF hash", dest_prefix.hex())
            return
        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=enc.LxmfDestType.NODE,
            destination=enc._node(lxmf_hash),
            fields={enc.FIELD_TEXT: text},
        )
        await self.lxmf.send(msg)
        log.debug("routed DM to LXMF: dest=%s", lxmf_hash)

    # ======================================================================
    # Radio → app path (existing pass-through; still used by current tests)
    # ======================================================================

    async def handle_radio_push(self, pkt_type: PacketType, payload: bytes) -> None:
        """Called for every push notification received from the local radio."""
        if self.app:
            frame = bytes([pkt_type]) + payload
            await self.app.push_frame(frame)

    # ======================================================================
    # CoreNet addressing & commands — DMs to the bridge itself
    # ======================================================================

    async def handle_inbound_dm(self, sender_prefix: bytes, text: str) -> str | None:
        """Process a DM received by the bridge from a local RF user.

        Returns:
            A reply DM body (str) if the router wants to respond inline,
            or None if the message was handled by routing onward (or silently).
        """
        # First check for a CoreNet address prefix
        parsed = parse_outbound(text)
        if parsed is not None:
            await self._forward_to_coretnet(sender_prefix, parsed.address, parsed.body)
            return None

        # Then check for a router command
        cmd = parse_command(text)
        if cmd is not None:
            return await self._handle_command(sender_prefix, cmd)

        # Not addressed to CoreNet and not a known command; no reply
        return None

    async def _forward_to_coretnet(
        self, sender_prefix: bytes, address: CoreNetAddress, body: str
    ) -> None:
        """Route a @callsign@region-addressed DM via LXMF (spec §9.1)."""
        sender = self.contacts.get(sender_prefix)
        sender_callsign = sender.display_name if sender else self.local_callsign

        # Look up the target peer router by name
        peer = self._find_peer(address.router_name)
        if peer is None:
            log.info("unknown destination router %r", address.router_name)
            return

        source_address = CoreNetAddress(
            callsign=sender_callsign, router_name=self.short_tag
        )

        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=enc.LxmfDestType.NODE,
            destination=enc._node(peer.identity_hash.hex()),
            fields={
                enc.FIELD_TEXT: body,
                enc.FIELD_APP_DATA: {
                    "target_callsign": address.callsign,
                    "source_callsign": source_address.callsign,
                    "source_router": source_address.router_name,
                },
            },
        )
        await self.lxmf.send(msg)
        log.debug(
            "forwarded CoreNet DM %s → %s", source_address.qualified(), address.qualified()
        )

    def _find_peer(self, router_name: str) -> PeerAnnounce | None:
        """Locate a known peer by its router_name (short tag or fqrn)."""
        candidates = [
            p for p in self.peers.incumbents().values()
            if p.router_name == router_name
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    async def _handle_command(
        self, sender_prefix: bytes, cmd: Command
    ) -> str | None:
        """Dispatch a parsed router command.  Returns the reply body."""
        if isinstance(cmd, WhoQuery):
            return self._format_who(cmd)
        if isinstance(cmd, ChannelsQuery):
            return self._format_channels(cmd)
        if isinstance(cmd, BridgeStatus):
            return self._format_bridge_status()
        if isinstance(cmd, BridgeActivate):
            return await self._handle_bridge_activate(sender_prefix, cmd)
        if isinstance(cmd, Unbridge):
            return await self._handle_unbridge(sender_prefix, cmd)
        return None

    # ------------------------------------------------------------------
    # Query formatters
    # ------------------------------------------------------------------

    def _format_who(self, cmd: WhoQuery) -> str:
        entries = self.contacts.remote_contacts()
        now = self._clock()
        if cmd.filter is not None:
            f = cmd.filter.casefold()
            entries = [
                e for e in entries
                if e.display_name.casefold() == f or e.router_name.casefold() == f
            ]
        if not entries:
            return "No matching remote nodes visible."
        lines = [f"{len(entries)} remote node{'s' if len(entries) != 1 else ''} visible:"]
        for e in entries:
            fp = e.pubkey.hex()[:8] if e.pubkey else "--"
            lines.append(f"  @{e.display_name}@{e.router_name}   [{fp}]")
        return "\n".join(lines)

    def _format_channels(self, cmd: ChannelsQuery) -> str:
        entries = self.channels.published_channels(now=self._clock())
        if not entries:
            return "No public channels at this bridge."
        lines = [
            f"{len(entries)} public channel{'s' if len(entries) != 1 else ''} "
            f"at {self.router_name}:"
        ]
        for h, name in entries:
            lines.append(f"  {name}")
        return "\n".join(lines)

    def _format_bridge_status(self) -> str:
        now = self._clock()
        active = list(self._active_bridges.values())
        if not active:
            return "No active bridges."
        lines = [f"{len(active)} active bridge{'s' if len(active) != 1 else ''}:"]
        for b in active:
            if b.expires_at is None:
                lines.append(f"  {b.channel_name} (persistent)")
            else:
                remaining = max(0, int(b.expires_at - now))
                lines.append(f"  {b.channel_name} ({remaining}s remaining)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Bridge activation / deactivation
    # ------------------------------------------------------------------

    async def _handle_bridge_activate(
        self, sender_prefix: bytes, cmd: BridgeActivate
    ) -> str:
        channel_hash = self._derive_channel_hash(cmd.channel_name)
        now = self._clock()
        expires_at = now + cmd.duration_seconds

        self.channels.register(channel_hash, cmd.channel_name)
        self._active_bridges[channel_hash] = ActiveBridge(
            channel_name=cmd.channel_name,
            channel_hash=channel_hash,
            expires_at=expires_at,
        )

        if self.control_channel:
            self.control_channel.publish(
                BridgeActivationNotice(
                    event="activate",
                    channel_hash=channel_hash,
                    router_name=self.router_name,
                    expires_at=expires_at,
                    timestamp=now,
                )
            )

        mins = cmd.duration_seconds // 60
        return f"Bridging #{cmd.channel_name} enabled for {mins} minute(s)."

    async def _handle_unbridge(self, sender_prefix: bytes, cmd: Unbridge) -> str:
        channel_hash = self._derive_channel_hash(cmd.channel_name)
        removed = self._active_bridges.pop(channel_hash, None)
        self.channels.unregister(channel_hash)

        if removed is not None and self.control_channel:
            self.control_channel.publish(
                BridgeActivationNotice(
                    event="expire",
                    channel_hash=channel_hash,
                    router_name=self.router_name,
                    expires_at=None,
                    timestamp=self._clock(),
                )
            )

        if removed is None:
            return f"#{cmd.channel_name} was not active."
        return f"Bridging #{cmd.channel_name} ended."

    def activate_nailed_up_bridge(
        self, channel_name: str, channel_secret: bytes
    ) -> bytes:
        """Operator-config entry point for a persistent bridge."""
        channel_hash = self._derive_channel_hash(channel_name, channel_secret)
        self.channels.register(channel_hash, channel_name)
        self._active_bridges[channel_hash] = ActiveBridge(
            channel_name=channel_name,
            channel_hash=channel_hash,
            expires_at=None,
        )
        if self.control_channel:
            self.control_channel.publish(
                BridgeActivationNotice(
                    event="activate",
                    channel_hash=channel_hash,
                    router_name=self.router_name,
                    expires_at=None,
                    timestamp=self._clock(),
                )
            )
        return channel_hash

    @staticmethod
    def _derive_channel_hash(name: str, secret: bytes = b"") -> bytes:
        """Spec §8.1: channel hash = H(name, secret).

        For v0.1 test purposes the hash is a simple SHA-256 of
        `name || 0x00 || secret`; real deployments will align with MeshCore's
        channel-hash derivation.
        """
        import hashlib
        h = hashlib.sha256()
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        h.update(secret)
        return h.digest()[:16]

    # ======================================================================
    # Channel message handling — loop prevention + in-channel controls
    # ======================================================================

    async def handle_inbound_channel_msg(
        self,
        channel_hash: bytes,
        tag: bytes,
        text: str,
        *,
        from_rf: bool,
    ) -> bool:
        """Handle one channel message passing through this bridge.

        `from_rf` is True when the message arrived from local RF (and thus
        should be forwarded to the wide-area transport) and False when it
        arrived from a wide-area peer (and should be re-emitted on local RF
        if not a duplicate).

        Returns True if the message should be forwarded, False if it was
        dropped (loop) or consumed as a control message.
        """
        # Control messages are consumed, not forwarded
        control = parse_control_message(text)
        if control is not None:
            self.channels.apply_control(channel_hash, control, now=self._clock())
            return False

        # Loop prevention
        if not self.channels.should_forward(tag, now=self._clock()):
            return False
        return True

    # ======================================================================
    # Peer announces — observe and detect conflicts
    # ======================================================================

    async def observe_peer_announce(self, announce: PeerAnnounce) -> None:
        """Called when a peer router's announce is observed on the wide-area transport."""
        result, report = self.peers.observe(announce)
        if result == "conflict" and report is not None:
            if self.peers.should_publish_report(announce.identity_hash, now=self._clock()):
                if self.control_channel:
                    self.control_channel.publish(ConflictReportPost(report=report))

    # ======================================================================
    # Lifecycle
    # ======================================================================

    def announce_online(self, zone_description: str = "") -> None:
        """Post a router-online notice to the control channel (spec §7.2)."""
        if self.control_channel is None:
            return
        fp = self.local_hash[:8] if self.local_hash else "00000000"
        self.control_channel.publish(
            RouterOnline(
                router_name=self.router_name,
                short_tag=self.short_tag if self.short_tag != self.router_name else None,
                identity_fingerprint=fp,
                zone_description=zone_description,
                timestamp=self._clock(),
            )
        )

    # ======================================================================
    # LXMF inbound → local delivery
    # ======================================================================

    async def _on_lxmf_inbound(self, msg: LxmfMessage) -> None:
        """Route an inbound LXMF message to its local destination."""
        if not self.app:
            return

        # Check whether this is a CoreNet-addressed DM (has target_callsign)
        app_data = msg.fields.get(enc.FIELD_APP_DATA, {}) or {}
        target_callsign = app_data.get("target_callsign")
        if target_callsign and isinstance(app_data, dict):
            await self._deliver_coretnet_dm(msg, app_data)
            return

        # Otherwise fall back to the existing synthesis paths
        dest = msg.destination
        if "channel" in dest:
            await self._synthesise_channel_push(msg)
        else:
            await self._synthesise_contact_push(msg)

    async def _deliver_coretnet_dm(
        self, msg: LxmfMessage, app_data: dict
    ) -> None:
        """Deliver a CoreNet-addressed LXMF DM to a local user (spec §9.2)."""
        target_callsign = app_data.get("target_callsign", "")
        source_callsign = app_data.get("source_callsign", "unknown")
        source_router = app_data.get("source_router", "unknown")
        body = msg.fields.get(enc.FIELD_TEXT, "")

        target = self.contacts.by_callsign(target_callsign)
        if target is None or target.is_remote:
            log.info("no local target for CoreNet DM to %s", target_callsign)
            return

        formatted = format_inbound(
            CoreNetAddress(callsign=source_callsign, router_name=source_router),
            body,
        )
        # Deliver as a DM via the local radio
        if self.radio:
            await self.radio.send_command(pack_send_txt_msg(target.prefix, formatted))

    # ------------------------------------------------------------------
    # Legacy synthesis paths (still used by existing tests)
    # ------------------------------------------------------------------

    async def _synthesise_contact_push(self, msg: LxmfMessage) -> None:
        text = msg.fields.get(enc.FIELD_TEXT, "")
        app_data = msg.fields.get(enc.FIELD_APP_DATA, {}) or {}

        sender_prefix_hex = app_data.get(
            "sender_prefix", msg.source[:12] if msg.source else "0" * 12
        )
        try:
            sender_prefix = bytes.fromhex(sender_prefix_hex.ljust(12, "0"))[:6]
        except ValueError:
            sender_prefix = b"\x00" * 6

        ts = int(app_data.get("ts", msg.timestamp))
        path_len = int(app_data.get("path_len", 0))

        contact_msg = ContactMessage(
            sender_prefix=sender_prefix,
            path_len=path_len,
            txt_type=1,
            sender_timestamp=ts,
            text=text,
            snr=float(app_data.get("snr") or 0.0),
        )
        push_payload = bytes([PacketType.CONTACT_MSG_RECV_V3]) + contact_msg.pack_v3()
        await self.app.push_frame(push_payload)

    async def _synthesise_channel_push(self, msg: LxmfMessage) -> None:
        text = msg.fields.get(enc.FIELD_TEXT, "")
        app_data = msg.fields.get(enc.FIELD_APP_DATA, {}) or {}
        ch_idx = int(app_data.get("ch_idx", 0))
        ts = int(app_data.get("ts", msg.timestamp))
        path_len = int(app_data.get("path_len", 0))

        channel_msg = ChannelMessage(
            channel_idx=ch_idx,
            path_len=path_len,
            txt_type=1,
            sender_timestamp=ts,
            text=text,
            snr=float(app_data.get("snr") or 0.0),
        )
        push_payload = bytes([PacketType.CHANNEL_MSG_RECV_V3]) + channel_msg.pack_v3()
        await self.app.push_frame(push_payload)
