"""Unit tests for the companion protocol frame codec (bridge/companion/frames.py)."""
from __future__ import annotations

import pytest

from bridge.companion.frames import (
    FRAME_RESP,
    FRAME_START,
    FrameReader,
    pack,
    unpack_one,
)


class TestPack:
    def test_command_marker(self):
        frame = pack(b"\x01\x02")
        assert frame[0] == FRAME_START

    def test_response_marker(self):
        frame = pack(b"\x00", response=True)
        assert frame[0] == FRAME_RESP

    def test_length_little_endian(self):
        payload = b"\xAA" * 300
        frame = pack(payload)
        assert frame[1] == 300 & 0xFF
        assert frame[2] == 300 >> 8

    def test_payload_preserved(self):
        payload = bytes(range(256))
        frame = pack(payload)
        assert frame[3:] == payload

    def test_empty_payload(self):
        frame = pack(b"")
        assert len(frame) == 3
        assert frame[1] == 0
        assert frame[2] == 0

    def test_single_byte(self):
        frame = pack(b"\xFF")
        assert frame == bytes([FRAME_START, 0x01, 0x00, 0xFF])

    def test_256_byte_payload(self):
        payload = b"\xBB" * 256
        frame = pack(payload)
        assert frame[1] == 0x00   # 256 & 0xFF
        assert frame[2] == 0x01   # 256 >> 8

    def test_round_trip(self):
        payload = b"\x02\xDE\xAD\xBE\xEF"
        frame = pack(payload)
        result = unpack_one(frame)
        assert result is not None
        is_resp, out, consumed = result
        assert not is_resp
        assert out == payload
        assert consumed == len(frame)

    def test_too_large_raises(self):
        with pytest.raises(ValueError, match="too large"):
            pack(b"\x00" * 70000)


class TestUnpackOne:
    def test_incomplete_returns_none(self):
        assert unpack_one(b"\x3C\x05") is None

    def test_partial_payload_returns_none(self):
        frame = pack(b"hello")
        assert unpack_one(frame[:5]) is None

    def test_invalid_marker_returns_none(self):
        assert unpack_one(b"\xFF\x01\x00\x42") is None

    def test_empty_returns_none(self):
        assert unpack_one(b"") is None

    def test_bytes_consumed_exact(self):
        payload = b"\x10\x20\x30"
        frame = pack(payload) + b"\xFF\xFF"   # trailing garbage
        is_resp, out, consumed = unpack_one(frame)
        assert consumed == 6   # 3 header + 3 payload
        assert out == payload

    def test_response_frame(self):
        frame = pack(b"\x00", response=True)
        is_resp, out, consumed = unpack_one(frame)
        assert is_resp
        assert out == b"\x00"


class TestFrameReader:
    def test_single_frame(self):
        reader = FrameReader()
        frame = pack(b"\x01\x02\x03")
        frames = reader.feed(frame)
        assert len(frames) == 1
        is_resp, payload = frames[0]
        assert not is_resp
        assert payload == b"\x01\x02\x03"

    def test_two_frames_concatenated(self):
        reader = FrameReader()
        data = pack(b"\x01") + pack(b"\x02", response=True)
        frames = reader.feed(data)
        assert len(frames) == 2
        assert frames[0] == (False, b"\x01")
        assert frames[1] == (True, b"\x02")

    def test_fragmented_delivery(self):
        reader = FrameReader()
        full = pack(b"\xAB\xCD\xEF")
        # Feed one byte at a time
        all_frames = []
        for byte in full:
            all_frames.extend(reader.feed(bytes([byte])))
        assert len(all_frames) == 1
        assert all_frames[0] == (False, b"\xAB\xCD\xEF")

    def test_junk_bytes_discarded(self):
        reader = FrameReader()
        junk = b"\x00\x01\xFF"
        frame = pack(b"\x07")
        frames = reader.feed(junk + frame)
        assert len(frames) == 1
        assert frames[0][1] == b"\x07"

    def test_buffered_property(self):
        reader = FrameReader()
        reader.feed(b"\x3C\x05\x00\x01")   # partial frame
        assert reader.buffered == 4

    def test_buffer_clears_after_complete_frame(self):
        reader = FrameReader()
        frame = pack(b"\x01")
        reader.feed(frame)
        assert reader.buffered == 0

    def test_multiple_feeds_accumulate(self):
        reader = FrameReader()
        frame = pack(b"\x01\x02")
        # Split at every possible byte boundary
        for i in range(1, len(frame)):
            r = FrameReader()
            r.feed(frame[:i])
            frames = r.feed(frame[i:])
            assert len(frames) == 1
            assert frames[0][1] == b"\x01\x02"
