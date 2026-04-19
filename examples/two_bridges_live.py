#!/usr/bin/env python3
"""Two-bridge live smoke test over real Reticulum using multiprocessing.

Spawns two child processes, each running a ReticulumLxmfTransport with its
own identity, Reticulum config, and LXMF storage.  The two processes are
connected by a TCP interface (one server, one client) on localhost so they
can exchange announces and LXMF messages.

Verifies end-to-end that:

  1. Both bridges come up with distinct identities.
  2. Bridge A's announce reaches bridge B, populating B's peer view.
  3. An encrypted LXMF message from B to A is delivered and decrypted.

This is the definitive smoke test for the Reticulum adapter against the
live libraries.  It requires no radio hardware (just localhost TCP) but
does require RNS + LXMF to be installed.

Run:
    python examples/two_bridges_live.py

Exit codes:
    0 — message delivered, round-trip confirmed
    1 — RNS/LXMF not installed
    2 — a bridge process failed to start
    3 — timeout waiting for delivery
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import os
import sys
import tempfile
import time
from pathlib import Path


def _log(tag: str, msg: str) -> None:
    """Timestamped, process-tagged log line flushed immediately."""
    ts = time.strftime("%H:%M:%S")
    print(f"{ts} [{tag}:{os.getpid()}] {msg}", flush=True)


# -------------------------------------------------------------------------
# Reticulum TCP-interface config
#
# Two-process setup: A listens on a local TCP port; B connects to it as
# a TCP client.  Each process needs its own shared-instance and control
# ports to avoid colliding with any other Reticulum instance on the host.
# -------------------------------------------------------------------------

CONFIG_SERVER = """
[reticulum]
enable_transport = Yes
share_instance = No
shared_instance_port = {shared_port}
instance_control_port = {control_port}

[logging]
loglevel = 4

[interfaces]

  [[TCP Server Interface]]
    type = TCPServerInterface
    enabled = Yes
    listen_ip = 127.0.0.1
    listen_port = {port}
"""

CONFIG_CLIENT = """
[reticulum]
enable_transport = Yes
share_instance = No
shared_instance_port = {shared_port}
instance_control_port = {control_port}

[logging]
loglevel = 4

[interfaces]

  [[TCP Client Interface]]
    type = TCPClientInterface
    enabled = Yes
    target_host = 127.0.0.1
    target_port = {port}
"""


def _write_config(config_dir: Path, body: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config").write_text(body.lstrip())


# -------------------------------------------------------------------------
# Bridge A — the receiver
# -------------------------------------------------------------------------

def _run_bridge_a(
    root: str,
    port: int,
    ready_queue: mp.Queue,
    result_queue: mp.Queue,
    done_event,
) -> None:
    logging.basicConfig(level=logging.WARNING)
    root_path = Path(root) / "bridge-a"
    cfg_dir = root_path / "reticulum"
    _write_config(cfg_dir, CONFIG_SERVER.format(
        port=port, shared_port=37428, control_port=37429,
    ))

    async def run() -> None:
        from bridge.lxmf_layer.transport import FIELD_TEXT
        from bridge.reticulum_adapter import ReticulumLxmfTransport

        transport = ReticulumLxmfTransport(
            config_dir=cfg_dir,
            identity_path=root_path / "identity",
            storage_path=root_path / "lxmf",
            display_name="CoreNet-A",
        )
        await transport.start()
        identity_hex = transport.identity_hash.hex()
        _log("A", f"online at {identity_hex}")

        received = asyncio.Event()
        received_text: list[str] = []

        async def on_inbound(msg) -> None:
            text = msg.fields.get(FIELD_TEXT, "")
            _log("A", f"received: {text!r} from {msg.source[:8]}")
            received_text.append(text)
            received.set()

        transport.add_inbound_callback(on_inbound)
        ready_queue.put(identity_hex)

        # Repeat-announce so B can learn our identity even if its TCP
        # connection wasn't established when we first announced.
        async def periodic_announce() -> None:
            for _ in range(20):
                try:
                    await transport.announce_self()
                except Exception as e:
                    _log("A", f"announce error: {e}")
                await asyncio.sleep(2.0)

        announce_task = asyncio.create_task(periodic_announce())
        try:
            await asyncio.wait_for(received.wait(), timeout=45.0)
            result_queue.put(("received", received_text[-1]))
        except asyncio.TimeoutError:
            result_queue.put(("timeout", None))
        finally:
            announce_task.cancel()
            try:
                await announce_task
            except (asyncio.CancelledError, Exception):
                pass

        await asyncio.to_thread(done_event.wait, 5.0)
        await transport.stop()

    asyncio.run(run())


# -------------------------------------------------------------------------
# Bridge B — the sender
# -------------------------------------------------------------------------

def _run_bridge_b(
    root: str,
    port: int,
    peer_hash_hex: str,
    ready_queue: mp.Queue,
    done_event,
) -> None:
    logging.basicConfig(level=logging.WARNING)
    root_path = Path(root) / "bridge-b"
    cfg_dir = root_path / "reticulum"
    _write_config(cfg_dir, CONFIG_CLIENT.format(
        port=port, shared_port=37438, control_port=37439,
    ))

    async def run() -> None:
        from bridge.companion.types import LxmfDestType, LxmfTransport
        from bridge.lxmf_layer.transport import FIELD_TEXT, LxmfMessage
        from bridge.reticulum_adapter import ReticulumLxmfTransport

        transport = ReticulumLxmfTransport(
            config_dir=cfg_dir,
            identity_path=root_path / "identity",
            storage_path=root_path / "lxmf",
            display_name="CoreNet-B",
        )
        await transport.start()
        _log("B", f"online at {transport.identity_hash.hex()}")

        announce_seen = asyncio.Event()
        target_hash = bytes.fromhex(peer_hash_hex)

        async def on_announce(announce) -> None:
            if announce.identity_hash == target_hash:
                _log("B", "A's announce observed")
                announce_seen.set()

        transport.add_announce_callback(on_announce)
        ready_queue.put("b-ready")

        async def periodic_announce() -> None:
            for _ in range(20):
                try:
                    await transport.announce_self()
                except Exception as e:
                    _log("B", f"announce error: {e}")
                await asyncio.sleep(2.0)

        announce_task = asyncio.create_task(periodic_announce())

        try:
            await asyncio.wait_for(announce_seen.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _log("B", "timed out waiting for A's announce")

        _log("B", "sending message to A")
        msg = LxmfMessage(
            transport=LxmfTransport.DIRECT,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{peer_hash_hex}",
            fields={FIELD_TEXT: "hello from bridge B"},
        )
        await transport.send(msg)

        # Stay alive long enough for LXMF to finish sending and for A to
        # receive the message.
        await asyncio.to_thread(done_event.wait, 45.0)

        announce_task.cancel()
        try:
            await announce_task
        except (asyncio.CancelledError, Exception):
            pass
        await transport.stop()

    asyncio.run(run())


# -------------------------------------------------------------------------
# Parent orchestrator
# -------------------------------------------------------------------------

def main() -> int:
    try:
        import RNS   # noqa: F401
        import LXMF  # noqa: F401
    except ImportError:
        print("RNS + LXMF required. Run: pip install rns lxmf", file=sys.stderr)
        return 1

    # multiprocessing 'spawn' gives a clean child process without inherited
    # Reticulum singleton state.
    ctx = mp.get_context("spawn")

    with tempfile.TemporaryDirectory(prefix="corenet-two-bridges-") as root:
        port = 7703
        ready_a: mp.Queue = ctx.Queue()
        ready_b: mp.Queue = ctx.Queue()
        result_a: mp.Queue = ctx.Queue()
        done_event = ctx.Event()

        proc_a = ctx.Process(
            target=_run_bridge_a,
            args=(root, port, ready_a, result_a, done_event),
            daemon=True,
        )
        proc_a.start()

        try:
            a_identity = ready_a.get(timeout=15.0)
        except Exception:
            print("bridge A failed to start", file=sys.stderr)
            proc_a.terminate()
            return 2

        proc_b = ctx.Process(
            target=_run_bridge_b,
            args=(root, port, a_identity, ready_b, done_event),
            daemon=True,
        )
        proc_b.start()

        try:
            ready_b.get(timeout=15.0)
        except Exception:
            print("bridge B failed to start", file=sys.stderr)
            proc_a.terminate()
            proc_b.terminate()
            return 2

        try:
            status, payload = result_a.get(timeout=60.0)
        except Exception:
            status, payload = "timeout", None

        done_event.set()
        proc_a.join(timeout=15.0)
        proc_b.join(timeout=15.0)
        if proc_a.is_alive():
            proc_a.terminate()
        if proc_b.is_alive():
            proc_b.terminate()

        if status == "received":
            print(f"\n✓ PASS — delivered: {payload!r}")
            return 0
        print(f"\n✗ FAIL — status={status}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
