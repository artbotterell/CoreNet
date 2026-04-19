#!/usr/bin/env python3
"""Single-bridge cold-start smoke test over live Reticulum.

Brings up one CoreNet bridge using the real RNS + LXMF libraries, confirms
it receives an identity hash and shuts down cleanly.  This is the smallest
affirmative test that the adapter plumbing works end-to-end against a live
Reticulum runtime.

Run:
    python examples/single_bridge_smoke.py

Expected output includes an identity hash like 0d2892cbed7341d812f64f2dc7bf55f8.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        from bridge.reticulum_adapter import (
            ReticulumLxmfTransport,
            is_reticulum_available,
        )
    except ImportError:
        print("Reticulum/LXMF not importable. Install with: pip install rns lxmf")
        return 1

    if not is_reticulum_available():
        print("Reticulum/LXMF not available on this system.")
        return 1

    with tempfile.TemporaryDirectory(prefix="corenet-smoke-") as root:
        root_path = Path(root)
        (root_path / "reticulum").mkdir()
        (root_path / "lxmf").mkdir()

        print("=== Starting CoreNet bridge ===")
        transport = ReticulumLxmfTransport(
            config_dir=root_path / "reticulum",
            identity_path=root_path / "identity",
            storage_path=root_path / "lxmf",
            display_name="CoreNet-Smoke",
        )
        await transport.start()

        print(f"  identity hash:    {transport.identity_hash.hex()}")
        print(f"  identity file:    {(root_path / 'identity')}")
        print(f"  reticulum config: {(root_path / 'reticulum')}")
        print(f"  lxmf storage:     {(root_path / 'lxmf')}")

        # Brief pause so any startup housekeeping completes
        await asyncio.sleep(0.5)

        print("=== Shutting down ===")
        await transport.stop()

    print("=== Smoke test passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
