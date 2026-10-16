"""Pulsar switches off only runs it switched on itself (0.3.1, pulsar-web#45).

The case it fixes, from a real home: an automation switched the bathroom heater on;
a Pulsar slot started while it was on and ended at 11:00, and Pulsar switched the
heater off in the middle of the automation's run.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

HEATER = "input_boolean.heater"


async def start(hass: HomeAssistant, entry: MockConfigEntry, initial: bool = False) -> Any:
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"heater": {"initial": initial}}})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def heartbeat(hass: HomeAssistant, agent: Any, pulsar: Any, target: str | None = None, command: str | None = None) -> None:
    pulsar.response = {
        "ok": True,
        "targets": [{"entity_id": HEATER, "state": target}] if target else [],
        "commands": [{"id": "c1", "entity_id": HEATER, "state": command, "valid_until": "2999-01-01T00:00:00+00:00"}] if command else [],
    }
    await agent.async_heartbeat()
    await hass.async_block_till_done()


async def someone(hass: HomeAssistant, service: str) -> None:
    """An automation or a person: a context that isn't Pulsar's."""
    await hass.services.async_call("input_boolean", service, {"entity_id": HEATER}, blocking=True, context=Context())
    await hass.async_block_till_done()


def state(hass: HomeAssistant) -> str:
    return hass.states.get(HEATER).state


async def test_pulsar_ends_its_own_run(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    await heartbeat(hass, agent, pulsar, "off")
    await heartbeat(hass, agent, pulsar, "on")
    assert state(hass) == "on"
    await heartbeat(hass, agent, pulsar, "off")
    assert state(hass) == "off"


async def test_a_run_already_on_when_the_slot_starts_is_left_on_when_it_ends(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    await heartbeat(hass, agent, pulsar, "off")
    await someone(hass, "turn_on")  # 10:44 the automation's comfort heat
    await heartbeat(hass, agent, pulsar, "on")  # a Pulsar slot starts: nothing to do
    await heartbeat(hass, agent, pulsar, "off")  # 11:00 the slot ends
    assert state(hass) == "on"
    # The run's owner ends it; Pulsar's next run is its own again.
    await someone(hass, "turn_off")
    await heartbeat(hass, agent, pulsar, "on")
    assert state(hass) == "on"
    await heartbeat(hass, agent, pulsar, "off")
    assert state(hass) == "off"


async def test_a_run_switched_by_someone_during_the_slot_is_theirs(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    await heartbeat(hass, agent, pulsar, "off")
    await heartbeat(hass, agent, pulsar, "on")
    # Off and on again by someone: their run now.
    await someone(hass, "turn_off")
    await someone(hass, "turn_on")
    await heartbeat(hass, agent, pulsar, "off")
    assert state(hass) == "on"


async def test_a_command_from_the_pulsar_app_always_applies(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    await heartbeat(hass, agent, pulsar, "off")
    await someone(hass, "turn_on")
    await heartbeat(hass, agent, pulsar, "off", command="off")
    assert state(hass) == "off"


async def test_ownership_survives_a_restart(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    await heartbeat(hass, agent, pulsar, "off")
    await heartbeat(hass, agent, pulsar, "on")
    assert await hass.config_entries.async_unload(entry.entry_id)
    # While Home Assistant starts, the device is briefly unavailable.
    hass.states.async_set(HEATER, "unavailable")
    hass.states.async_set(HEATER, "on")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await heartbeat(hass, entry.runtime_data, pulsar, "off")
    assert state(hass) == "off"


async def test_failsafe_still_switches_everything_on(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    agent = await start(hass, entry)
    await heartbeat(hass, agent, pulsar, "off")
    agent._last_success -= 3600  # Pulsar unreachable for an hour
    await agent._maybe_failsafe()
    await hass.async_block_till_done()
    assert state(hass) == "on"
    # Pulsar is back and its schedule says off: it switched the device on, so it switches it off.
    await heartbeat(hass, agent, pulsar, "off")
    assert state(hass) == "off"
