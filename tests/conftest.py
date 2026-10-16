"""Fixtures: a real Home Assistant core with a fake Pulsar on the other end."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sun_driven_pulsar.const import CONF_API_KEY, CONF_URL, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


class FakePulsar:
    """Records heartbeats and answers with whatever the test sets."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.response: dict[str, Any] = {"ok": True, "targets": [], "commands": []}

    def client(self, *_args: Any) -> FakePulsar:
        return self

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(payload)
        return dict(self.response)


@pytest.fixture
def pulsar() -> FakePulsar:
    """Pulsar's side of the heartbeat."""
    fake = FakePulsar()
    with patch("custom_components.sun_driven_pulsar.agent.PulsarClient", fake.client):
        yield fake


@pytest.fixture
def entry(enable_custom_integrations: Any) -> MockConfigEntry:
    """A paired installation, loaded from custom_components."""
    return MockConfigEntry(domain=DOMAIN, data={CONF_URL: "https://pulsar.example", CONF_API_KEY: "pul_test"})
