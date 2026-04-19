"""Tests for the Reticulum/LXMF adapter.

Two tiers:
  - Conversion-only tests (no RNS runtime)
  - Live-integration test (skipped if RNS/LXMF not installed, or if the
    environment doesn't permit opening a Reticulum instance)
"""
from __future__ import annotations

import pytest

from bridge.companion.types import LxmfDestType, LxmfTransport
from bridge.lxmf_layer.transport import (
    FIELD_APP_DATA,
    FIELD_RAW_BINARY,
    FIELD_TEXT,
    LxmfMessage,
)
from bridge.reticulum_adapter import (
    InboundParams,
    aspect_to_dest_type,
    dest_type_to_aspect,
    is_reticulum_available,
    parse_coretnet_destination,
    to_lxmf_message,
    to_outbound_params,
)


HEX_HASH = "aabbccddeeff00112233445566778899"


class TestParseDestination:
    def test_node_destination(self):
        aspect, h = parse_coretnet_destination(f"meshcore.node.{HEX_HASH}")
        assert aspect == "node"
        assert h == bytes.fromhex(HEX_HASH)

    def test_bridge_destination(self):
        aspect, h = parse_coretnet_destination(f"meshcore.bridge.{HEX_HASH}")
        assert aspect == "bridge"

    def test_channel_destination(self):
        aspect, h = parse_coretnet_destination(f"meshcore.channel.{HEX_HASH}")
        assert aspect == "channel"

    def test_bad_prefix_rejected(self):
        with pytest.raises(ValueError):
            parse_coretnet_destination(f"notmeshcore.node.{HEX_HASH}")

    def test_too_few_parts(self):
        with pytest.raises(ValueError):
            parse_coretnet_destination("meshcore.node")

    def test_invalid_hex(self):
        with pytest.raises(ValueError):
            parse_coretnet_destination("meshcore.node.not-hex")


class TestAspectMapping:
    def test_roundtrip(self):
        for dt in (LxmfDestType.NODE, LxmfDestType.BRIDGE, LxmfDestType.CHANNEL):
            aspect = dest_type_to_aspect(dt)
            assert aspect_to_dest_type(aspect) == dt

    def test_unknown_aspect_rejected(self):
        with pytest.raises(ValueError):
            aspect_to_dest_type("something")


class TestOutboundConversion:
    def test_text_goes_to_content(self):
        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{HEX_HASH}",
            fields={FIELD_TEXT: "hello"},
        )
        params = to_outbound_params(msg)
        assert params.content == "hello"
        assert params.custom_data is None

    def test_app_data_goes_to_custom_data(self):
        msg = LxmfMessage(
            transport=LxmfTransport.DIRECT,
            dest_type=LxmfDestType.BRIDGE,
            destination=f"meshcore.bridge.{HEX_HASH}",
            fields={FIELD_APP_DATA: {"request": "status"}},
        )
        params = to_outbound_params(msg)
        assert params.content == ""
        assert params.custom_data == {"request": "status"}

    def test_raw_binary_goes_to_custom_data(self):
        msg = LxmfMessage(
            transport=LxmfTransport.DIRECT,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{HEX_HASH}",
            fields={FIELD_RAW_BINARY: b"\x01\x02\x03"},
        )
        params = to_outbound_params(msg)
        assert params.custom_data == b"\x01\x02\x03"

    def test_mixed_app_data_and_raw(self):
        msg = LxmfMessage(
            transport=LxmfTransport.DIRECT,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{HEX_HASH}",
            fields={
                FIELD_APP_DATA: {"lpp_len": 20},
                FIELD_RAW_BINARY: b"\xaa" * 20,
            },
        )
        params = to_outbound_params(msg)
        assert isinstance(params.custom_data, dict)
        assert params.custom_data["app_data"] == {"lpp_len": 20}
        assert params.custom_data["raw"] == b"\xaa" * 20

    def test_transport_maps_to_desired_method(self):
        for t, code in [
            (LxmfTransport.DIRECT, 2),
            (LxmfTransport.PROPAGATED, 3),
            (LxmfTransport.ANNOUNCE, 1),
        ]:
            msg = LxmfMessage(
                transport=t,
                dest_type=LxmfDestType.NODE,
                destination=f"meshcore.node.{HEX_HASH}",
                fields={},
            )
            assert to_outbound_params(msg).desired_method == code

    def test_dest_hash_extracted(self):
        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{HEX_HASH}",
            fields={},
        )
        assert to_outbound_params(msg).dest_hash == bytes.fromhex(HEX_HASH)

    def test_title_preserved(self):
        msg = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{HEX_HASH}",
            title="hello subject",
            fields={},
        )
        assert to_outbound_params(msg).title == "hello subject"


class TestInboundConversion:
    def test_content_goes_to_text(self):
        params = InboundParams(
            content="from peer",
            title="",
            custom_data=None,
            source_hash=b"\xaa" * 16,
            destination_hash=bytes.fromhex(HEX_HASH),
            destination_aspect="node",
            desired_method=2,
        )
        msg = to_lxmf_message(params)
        assert msg.fields[FIELD_TEXT] == "from peer"

    def test_custom_dict_goes_to_app_data(self):
        params = InboundParams(
            content="",
            title="",
            custom_data={"foo": "bar"},
            source_hash=b"\xaa" * 16,
            destination_hash=bytes.fromhex(HEX_HASH),
            destination_aspect="node",
            desired_method=3,
        )
        msg = to_lxmf_message(params)
        assert msg.fields[FIELD_APP_DATA] == {"foo": "bar"}

    def test_custom_bytes_goes_to_raw_binary(self):
        params = InboundParams(
            content="",
            title="",
            custom_data=b"\xde\xad\xbe\xef",
            source_hash=b"\xaa" * 16,
            destination_hash=bytes.fromhex(HEX_HASH),
            destination_aspect="node",
            desired_method=2,
        )
        msg = to_lxmf_message(params)
        assert msg.fields[FIELD_RAW_BINARY] == b"\xde\xad\xbe\xef"

    def test_mixed_custom_data(self):
        params = InboundParams(
            content="",
            title="",
            custom_data={"app_data": {"lpp_len": 20}, "raw": b"\xaa" * 20},
            source_hash=b"\xaa" * 16,
            destination_hash=bytes.fromhex(HEX_HASH),
            destination_aspect="node",
            desired_method=2,
        )
        msg = to_lxmf_message(params)
        assert msg.fields[FIELD_APP_DATA] == {"lpp_len": 20}
        assert msg.fields[FIELD_RAW_BINARY] == b"\xaa" * 20

    def test_destination_reconstructed(self):
        params = InboundParams(
            content="x",
            title="",
            custom_data=None,
            source_hash=b"\xaa" * 16,
            destination_hash=bytes.fromhex(HEX_HASH),
            destination_aspect="node",
            desired_method=2,
        )
        msg = to_lxmf_message(params)
        assert msg.destination == f"meshcore.node.{HEX_HASH}"

    def test_source_preserved_as_hex(self):
        source = b"\x12\x34\x56\x78"
        params = InboundParams(
            content="",
            title="",
            custom_data=None,
            source_hash=source,
            destination_hash=bytes.fromhex(HEX_HASH),
            destination_aspect="node",
            desired_method=2,
        )
        msg = to_lxmf_message(params)
        assert msg.source == source.hex()


class TestRoundTrip:
    def test_outbound_then_inbound_preserves_fields(self):
        original = LxmfMessage(
            transport=LxmfTransport.PROPAGATED,
            dest_type=LxmfDestType.NODE,
            destination=f"meshcore.node.{HEX_HASH}",
            title="subject",
            fields={
                FIELD_TEXT: "hello",
                FIELD_APP_DATA: {"ts": 12345},
            },
        )
        out = to_outbound_params(original)
        # Simulate the live transport: pass out params across as inbound params
        reconstructed_params = InboundParams(
            content=out.content,
            title=out.title,
            custom_data=out.custom_data,
            source_hash=b"\x00" * 16,
            destination_hash=out.dest_hash,
            destination_aspect=out.dest_aspect,
            desired_method=out.desired_method,
        )
        inbound = to_lxmf_message(reconstructed_params)

        assert inbound.fields[FIELD_TEXT] == "hello"
        assert inbound.fields[FIELD_APP_DATA] == {"ts": 12345}
        assert inbound.transport == LxmfTransport.PROPAGATED
        assert inbound.destination == original.destination


# ---------------------------------------------------------------------------
# Live integration — requires RNS/LXMF; skipped otherwise
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not is_reticulum_available(),
    reason="Reticulum/LXMF not installed",
)
def test_live_adapter_importable():
    """Smoke test: the live adapter class is importable when RNS/LXMF are present.

    Does not attempt to start a Reticulum instance (that would require a
    configured transport and network state beyond the test environment's
    control).  Verifies only that the module imports cleanly and the adapter
    class can be instantiated without side effects.
    """
    from bridge.reticulum_adapter import ReticulumLxmfTransport
    # Construction itself does not open Reticulum — only start() does.
    adapter = ReticulumLxmfTransport(display_name="CoreNet-Test")
    assert adapter is not None
