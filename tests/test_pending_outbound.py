"""Tests for the outbound retry queue in bridge/reticulum_adapter.py.

Exercise the queue logic (enqueue, expire, flush) without needing live
Reticulum by manipulating the private fields directly.  Integration with
the live announce handler is covered by the hardware/demo smoke tests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pytest

from bridge.companion.types import LxmfDestType, LxmfTransport
from bridge.lxmf_layer.transport import FIELD_TEXT, LxmfMessage
from bridge.reticulum_adapter import is_reticulum_available


pytestmark = pytest.mark.skipif(
    not is_reticulum_available(),
    reason="Reticulum/LXMF required for the adapter under test",
)


HASH_A = b"\x01" * 16
HASH_B = b"\x02" * 16


def _msg(dest_hash: bytes, text: str) -> LxmfMessage:
    return LxmfMessage(
        transport=LxmfTransport.PROPAGATED,
        dest_type=LxmfDestType.NODE,
        destination=f"meshcore.node.{dest_hash.hex()}",
        fields={FIELD_TEXT: text},
    )


def _make_transport_without_running_rns():
    """Instantiate the adapter class without actually starting Reticulum.

    For queue-logic tests we only need the instance's pending-dict machinery.
    """
    from bridge.reticulum_adapter import ReticulumLxmfTransport
    return ReticulumLxmfTransport(display_name="Test")


class TestEnqueue:
    def test_starts_empty(self):
        t = _make_transport_without_running_rns()
        assert t.pending_count() == 0

    def test_enqueue_increments_count(self):
        t = _make_transport_without_running_rns()
        t._enqueue_pending(HASH_A, _msg(HASH_A, "hi"))
        assert t.pending_count(HASH_A) == 1
        assert t.pending_count() == 1

    def test_multiple_destinations_independent(self):
        t = _make_transport_without_running_rns()
        t._enqueue_pending(HASH_A, _msg(HASH_A, "a1"))
        t._enqueue_pending(HASH_A, _msg(HASH_A, "a2"))
        t._enqueue_pending(HASH_B, _msg(HASH_B, "b1"))
        assert t.pending_count(HASH_A) == 2
        assert t.pending_count(HASH_B) == 1
        assert t.pending_count() == 3


class TestExpiry:
    def test_messages_older_than_ttl_drop(self):
        t = _make_transport_without_running_rns()
        t._pending_ttl_seconds = 60.0
        # Enqueue a message "eight minutes ago" (past TTL)
        t._pending[HASH_A] = [(time.time() - 480.0, _msg(HASH_A, "stale"))]
        t._expire_pending()
        assert t.pending_count(HASH_A) == 0

    def test_fresh_messages_retained(self):
        t = _make_transport_without_running_rns()
        t._pending_ttl_seconds = 60.0
        t._pending[HASH_A] = [(time.time() - 10.0, _msg(HASH_A, "fresh"))]
        t._expire_pending()
        assert t.pending_count(HASH_A) == 1

    def test_mixed_fresh_and_stale(self):
        t = _make_transport_without_running_rns()
        t._pending_ttl_seconds = 60.0
        t._pending[HASH_A] = [
            (time.time() - 10.0, _msg(HASH_A, "fresh")),
            (time.time() - 480.0, _msg(HASH_A, "stale")),
            (time.time() - 5.0, _msg(HASH_A, "also fresh")),
        ]
        t._expire_pending()
        assert t.pending_count(HASH_A) == 2


class TestFlushPending:
    async def test_flush_with_no_identity_retains_queue(self):
        """If the peer's identity still isn't available, messages stay queued."""
        from unittest.mock import patch

        t = _make_transport_without_running_rns()
        t._enqueue_pending(HASH_A, _msg(HASH_A, "waiting"))

        # Patch RNS.Identity.recall to return None
        with patch("bridge.reticulum_adapter.RNS.Identity.recall", return_value=None):
            await t._flush_pending(HASH_A)

        assert t.pending_count(HASH_A) == 1

    async def test_flush_with_identity_clears_queue(self):
        """When the peer's identity is known, queue is drained on flush."""
        from unittest.mock import MagicMock, patch

        t = _make_transport_without_running_rns()
        t._identity = MagicMock()
        t._router = MagicMock()
        # Stub the delivery_destinations dict so the delivery_destination
        # property can return something LXMessage will accept (via the
        # patched LXMF.LXMessage stub below).
        mock_local_dest = MagicMock()
        t._router.delivery_destinations = {b"\xff" * 16: mock_local_dest}
        t._enqueue_pending(HASH_A, _msg(HASH_A, "deliver me"))

        mock_identity = MagicMock()
        with patch("bridge.reticulum_adapter.RNS.Identity.recall", return_value=mock_identity):
            with patch("bridge.reticulum_adapter.RNS.Destination", return_value=MagicMock()):
                with patch("bridge.reticulum_adapter.LXMF.LXMessage", return_value=MagicMock()):
                    await t._flush_pending(HASH_A)

        assert t.pending_count(HASH_A) == 0
        assert t._router.handle_outbound.called
