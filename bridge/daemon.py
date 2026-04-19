"""CoreNet bridge daemon — wires config, transports, and router into a
runnable process.

The module is importable for test purposes; a thin `__main__.py` wrapper
hosts the CLI.  The daemon's main coroutine:

- Loads config
- Instantiates the Reticulum/LXMF transport (or a mock, per config)
- Instantiates the serial radio transport (or a mock)
- Constructs the Router with channels, peers, and control channel
- Activates any nailed-up bridges
- Posts the router-online announcement
- Runs until cancelled (Ctrl-C / SIGTERM)
"""
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from bridge.channel_state import ChannelRegistry
from bridge.companion.types import PacketType
from bridge.config import BridgeConfig, load_config
from bridge.conflicts import PeerAnnounce, PeerRegistry
from bridge.control_channel import MockControlChannel
from bridge.lxmf_layer.transport import LxmfTransportBase
from bridge.router import ContactRegistry, Router

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transport factories
# ---------------------------------------------------------------------------

async def _make_radio(config: BridgeConfig, frame_cb) -> object:
    """Construct the radio transport per config."""
    if config.radio.type == "serial":
        from bridge.companion.serial_transport import SerialRadioTransport
        return await SerialRadioTransport.open_serial(
            config.radio.port,
            baudrate=config.radio.baudrate,
            frame_cb=frame_cb,
        )
    if config.radio.type == "mock":
        from tests.doubles.mock_radio import MockRadio
        return MockRadio()
    raise ValueError(f"unknown radio type: {config.radio.type}")


async def _make_lxmf(config: BridgeConfig) -> LxmfTransportBase:
    """Construct the LXMF transport per config."""
    if config.reticulum.type == "mock":
        from tests.doubles.mock_lxmf import MockLxmfTransport
        t = MockLxmfTransport()
        await t.start()
        return t

    from bridge.reticulum_adapter import (
        ReticulumLxmfTransport,
        is_reticulum_available,
    )
    if not is_reticulum_available():
        log.warning("Reticulum/LXMF not available; using mock transport")
        from tests.doubles.mock_lxmf import MockLxmfTransport
        t = MockLxmfTransport()
        await t.start()
        return t

    transport = ReticulumLxmfTransport(
        config_dir=config.reticulum.config_dir,
        identity_path=config.reticulum.identity_path,
        storage_path=config.reticulum.storage_path,
        display_name=config.reticulum.display_name,
    )
    await transport.start()
    return transport


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------

class Daemon:
    """Composable CoreNet bridge daemon."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.radio: object | None = None
        self.lxmf: LxmfTransportBase | None = None
        self.router: Router | None = None
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        """Initialise transports, wire the router, start all subsystems."""
        contacts = ContactRegistry()
        channels = ChannelRegistry()
        peers = PeerRegistry(self.config.router.name)
        control = MockControlChannel()   # real control-channel transport is TBD

        # Remember expected peers from config so we can cross-check announces
        # against the operator's known-peer list.  We do NOT feed these into
        # the PeerRegistry with placeholder pubkeys — that would cause every
        # real announce to look like a conflict.  Real pubkeys arrive via
        # the announce callback (wired below).
        self._expected_peers = {
            p.hash_bytes(): p.router_name for p in self.config.peers
        }

        # Construct radio first so the frame-callback can close over the router
        # (we need to set up a forward reference).
        self.lxmf = await _make_lxmf(self.config)

        # Frame callback: dispatch inbound radio frames to the router once it's built
        async def _frame_cb(is_response: bool, payload: bytes) -> None:
            if self.router is None or not payload:
                return
            if not is_response:
                # Outbound frame echoed back — shouldn't happen, ignore.
                return
            pkt_type = PacketType.from_byte(payload[0])
            await self.router.handle_radio_push(pkt_type, payload[1:])

        self.radio = await _make_radio(self.config, _frame_cb)

        # Build the router
        self.router = Router(
            contacts=contacts,
            lxmf=self.lxmf,
            local_hash="",   # populated below from LXMF identity if available
            router_name=self.config.router.name,
            short_tag=self.config.router.short_tag,
            local_callsign=self.config.router.local_callsign,
            channels=channels,
            peers=peers,
            control_channel=control,
            radio=self.radio,
            app=None,   # no companion app in v0.1 daemon
        )

        # Update local_hash from live transport if available
        if hasattr(self.lxmf, "identity_hash"):
            try:
                self.router.local_hash = self.lxmf.identity_hash.hex()  # type: ignore[attr-defined]
            except Exception as e:
                log.debug("could not populate local_hash from transport: %s", e)

        # Wire peer announces from the LXMF transport into the router so new
        # peers are learned dynamically (spec §10; prerequisite for two-bridge
        # liveness without hardcoded identity hashes).
        if hasattr(self.lxmf, "add_announce_callback"):
            async def _on_announce(announce):
                if self.router is not None:
                    await self.router.observe_peer_announce(announce)
            self.lxmf.add_announce_callback(_on_announce)   # type: ignore[attr-defined]

        # Activate nailed-up bridges
        for b in self.config.bridges:
            self.router.activate_nailed_up_bridge(
                b.name, b.secret_bytes(), channel_idx=b.channel_idx
            )

        # Announce online
        self.router.announce_online(self.config.router.zone_description)

        log.info("bridge %s online", self.config.router.name)

    async def run(self) -> None:
        """Run until shutdown is signalled."""
        await self._shutdown.wait()

    async def stop(self) -> None:
        """Shut down transports cleanly."""
        if self.radio is not None and hasattr(self.radio, "stop"):
            await self.radio.stop()    # type: ignore[attr-defined]
        if self.lxmf is not None:
            await self.lxmf.stop()
        self._shutdown.set()

    def request_shutdown(self) -> None:
        """Signal to the main task that it should wind down."""
        self._shutdown.set()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main(config_path: str | Path) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(config_path)
    daemon = Daemon(config)

    # Wire SIGINT / SIGTERM to graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, daemon.request_shutdown)
        except NotImplementedError:   # pragma: no cover — Windows
            pass

    try:
        await daemon.start()
        await daemon.run()
    finally:
        await daemon.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="corenet-bridge",
        description="CoreNet v0.1 reference bridge daemon",
    )
    parser.add_argument(
        "--config",
        "-c",
        required=True,
        help="Path to YAML or TOML configuration file",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_main(args.config))
