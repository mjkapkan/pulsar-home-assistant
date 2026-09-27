"""Pulsar: run appliances when electricity is cheapest.

The integration connects out to Pulsar every minute. Pulsar never connects to
Home Assistant, so nothing in the home is exposed to the internet.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .agent import PulsarAgent

type PulsarConfigEntry = ConfigEntry[PulsarAgent]


async def async_setup_entry(hass: HomeAssistant, entry: PulsarConfigEntry) -> bool:
    """Start the heartbeat for a paired installation."""
    agent = PulsarAgent(hass, entry)
    await agent.async_start()
    entry.runtime_data = agent
    entry.async_on_unload(agent.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PulsarConfigEntry) -> bool:
    """Stop the heartbeat (async_on_unload callbacks run after this)."""
    return True
