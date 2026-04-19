"""MeshCore companion protocol frame codec.

Wire format: [MARKER: 1B][LEN_LOW: 1B][LEN_HIGH: 1B][PAYLOAD: N bytes]
The first byte of every payload is the command or packet-type code.

Commands (app → radio) use FRAME_START (0x3C).
Responses (radio → app) use FRAME_RESP (0x3E).
"""
from __future__ import annotations

FRAME_START = 0x3C  # '<'  app → radio
FRAME_RESP  = 0x3E  # '>'  radio → app

_VALID_MARKERS = frozenset((FRAME_START, FRAME_RESP))


def pack(payload: bytes, *, response: bool = False) -> bytes:
    """Wrap payload in a frame for transmission."""
    marker = FRAME_RESP if response else FRAME_START
    n = len(payload)
    if n > 0xFFFF:
        raise ValueError(f"Payload too large: {n} bytes (max 65535)")
    return bytes([marker, n & 0xFF, (n >> 8) & 0xFF]) + payload


def unpack_one(data: bytes | bytearray) -> tuple[bool, bytes, int] | None:
    """Try to parse one frame from the start of data.

    Returns (is_response, payload, bytes_consumed) or None if the buffer holds
    fewer bytes than a complete frame requires.  Does not advance the buffer;
    the caller is responsible for slicing off bytes_consumed.
    """
    if len(data) < 3:
        return None
    marker = data[0]
    if marker not in _VALID_MARKERS:
        return None
    n = data[1] | (data[2] << 8)
    total = 3 + n
    if len(data) < total:
        return None
    return marker == FRAME_RESP, bytes(data[3:total]), total


class FrameReader:
    """Stateful incremental parser for a streaming byte source.

    Feed arbitrary chunks; complete frames are returned as they arrive.
    Invalid leading bytes (neither 0x3C nor 0x3E) are silently discarded,
    matching the behaviour of meshcore-rs read_task.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[bool, bytes]]:
        """Append chunk and return all newly complete (is_response, payload) frames."""
        self._buf.extend(chunk)
        frames: list[tuple[bool, bytes]] = []
        while True:
            # Discard bytes that cannot start a valid frame
            while self._buf and self._buf[0] not in _VALID_MARKERS:
                del self._buf[0]
            result = unpack_one(self._buf)
            if result is None:
                break
            is_resp, payload, consumed = result
            del self._buf[:consumed]
            frames.append((is_resp, payload))
        return frames

    @property
    def buffered(self) -> int:
        """Number of bytes currently held in the internal buffer."""
        return len(self._buf)
