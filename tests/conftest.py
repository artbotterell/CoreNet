"""Shared pytest fixtures for the CoreNet bridge test suite."""
from __future__ import annotations

import pytest

from bridge.router import ContactEntry, ContactRegistry, Router
from tests.doubles.mock_app import MockApp
from tests.doubles.mock_lxmf import MockLxmfTransport
from tests.doubles.mock_radio import MockRadio

LOCAL_HASH = "aabbccdd"
REMOTE_HASH = "11223344"

REMOTE_PREFIX = bytes.fromhex("aabbccddeeff")   # 6 bytes
LOCAL_PREFIX  = bytes.fromhex("112233445566")


@pytest.fixture
def radio() -> MockRadio:
    return MockRadio()


@pytest.fixture
def lxmf() -> MockLxmfTransport:
    return MockLxmfTransport()


@pytest.fixture
def app() -> MockApp:
    return MockApp()


@pytest.fixture
def contacts() -> ContactRegistry:
    reg = ContactRegistry()
    # A local contact (no LXMF hash)
    reg.add(ContactEntry(
        pubkey=LOCAL_PREFIX + b"\x00" * 26,
        prefix=LOCAL_PREFIX,
        display_name="LocalNode",
        lxmf_hash="",
        is_remote=False,
    ))
    # A remote contact reachable via LXMF
    reg.add(ContactEntry(
        pubkey=REMOTE_PREFIX + b"\x00" * 26,
        prefix=REMOTE_PREFIX,
        display_name="RemoteNode",
        lxmf_hash=REMOTE_HASH,
        is_remote=True,
    ))
    return reg


@pytest.fixture
def router(contacts, lxmf, radio, app) -> Router:
    r = Router(contacts, lxmf, LOCAL_HASH)
    r.attach(radio, app)
    return r
