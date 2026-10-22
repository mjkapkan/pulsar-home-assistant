"""A refused heartbeat is not an unlink until it lasts (0.3.2, pulsar-web#57).

From a real home: on 2026-10-19 Google's front end, in front of Pulsar, answered
one heartbeat with 401 although the key was valid. The integration took it for
an unlink, stopped heartbeating and waited three days for a re-pair.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.sun_driven_pulsar.api import PulsarAuthError, PulsarClient, PulsarError

URL = "https://pulsar.example"
FRONT_END_401 = "<html><head><title>401 Unauthorized</title></head><body>Your client does not have permission.</body></html>"


async def test_only_pulsars_own_401_is_a_refusal(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    client = PulsarClient(async_get_clientsession(hass), URL, "pul_test")
    aioclient_mock.post(f"{URL}/api/agent/v1/heartbeat", status=401, text=FRONT_END_401)
    with pytest.raises(PulsarError) as raised:
        await client.heartbeat({})
    assert not isinstance(raised.value, PulsarAuthError)

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{URL}/api/agent/v1/heartbeat", status=401, json={"error": "unauthorized"})
    with pytest.raises(PulsarAuthError):
        await client.heartbeat({})


async def start(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_a_refusal_is_retried_for_ten_minutes_then_asks_to_re_pair(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    pulsar.error = PulsarAuthError("unauthorized")
    await agent.async_heartbeat()
    await hass.async_block_till_done()
    assert agent._unsub is not None  # still heartbeating
    assert not hass.config_entries.flow.async_progress_by_handler(entry.domain)

    # Accepted again: the count starts over.
    pulsar.error = None
    await agent.async_heartbeat()
    assert agent._refused_since is None

    # Refused for more than ten minutes: an unlink. Stop, and ask to re-pair.
    pulsar.error = PulsarAuthError("unauthorized")
    await agent.async_heartbeat()
    agent._refused_since -= 601
    await agent.async_heartbeat()
    await hass.async_block_till_done()
    assert agent._unsub is None
    assert hass.config_entries.flow.async_progress_by_handler(entry.domain)
