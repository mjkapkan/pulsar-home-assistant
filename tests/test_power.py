"""Power readings and meters in the heartbeat, and watched sensors (0.4.0)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.sun_driven_pulsar.power import device_power_sensor, power_w

POWER = {"device_class": "power", "unit_of_measurement": "W"}


def add_device(hass: HomeAssistant, host: MockConfigEntry, name: str) -> str:
    return dr.async_get(hass).async_get_or_create(config_entry_id=host.entry_id, identifiers={("test", name)}).id


def add_entity(hass: HomeAssistant, entity_id: str, state: str, attributes: dict[str, Any] | None = None,
               device_id: str | None = None, **registry: Any) -> None:
    domain, object_id = entity_id.split(".", 1)
    er.async_get(hass).async_get_or_create(domain, "test", entity_id, suggested_object_id=object_id,
                                           device_id=device_id, **registry)
    hass.states.async_set(entity_id, state, attributes or {})


async def setup_home(hass: HomeAssistant) -> None:
    host = MockConfigEntry(domain="test")
    host.add_to_hass(hass)
    plug = add_device(hass, host, "plug")
    relay = add_device(hass, host, "relay")
    bulb = add_device(hass, host, "bulb")
    # A plug: one switch, one power sensor.
    add_entity(hass, "switch.heater", "on", device_id=plug)
    add_entity(hass, "sensor.heater_energy_power", "1834.27", POWER, device_id=plug)
    # A two-channel relay: matched by name.
    add_entity(hass, "switch.relay_1", "on", device_id=relay)
    add_entity(hass, "switch.relay_2", "off", device_id=relay)
    add_entity(hass, "sensor.relay_1_power", "950", POWER, device_id=relay)
    add_entity(hass, "sensor.relay_2_power", "0", POWER, device_id=relay)
    # A bulb without a power sensor.
    add_entity(hass, "light.lamp", "on", device_id=bulb)
    # A main meter in kW, on no device; a temperature and a disabled power sensor are not meters.
    add_entity(hass, "sensor.main_power", "3.25", {"device_class": "power", "unit_of_measurement": "kW"})
    add_entity(hass, "sensor.outdoor", "12", {"device_class": "temperature", "unit_of_measurement": "°C"})
    add_entity(hass, "sensor.old_power", "5", POWER, disabled_by=er.RegistryEntryDisabler.USER)


async def start(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_heartbeat_reports_power_and_meters(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    await setup_home(hass)
    await start(hass, entry)
    payload = pulsar.payloads[-1]
    power = {e["entity_id"]: e["power_w"] for e in payload["entities"]}
    assert power == {"switch.heater": 1834.27, "switch.relay_1": 950.0, "switch.relay_2": 0.0, "light.lamp": None}
    assert [(m["entity_id"], m["power_w"]) for m in payload["meters"]] == [
        ("sensor.heater_energy_power", 1834.27),
        ("sensor.main_power", 3250.0),
        ("sensor.relay_1_power", 950.0),
        ("sensor.relay_2_power", 0.0),
    ]
    assert payload["integration_version"] == "0.4.0"


async def test_unavailable_sensor_reports_no_reading(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    await setup_home(hass)
    hass.states.async_set("sensor.heater_energy_power", "unavailable", POWER)
    await start(hass, entry)
    payload = pulsar.payloads[-1]
    assert next(e for e in payload["entities"] if e["entity_id"] == "switch.heater")["power_w"] is None
    meter = next(m for m in payload["meters"] if m["entity_id"] == "sensor.heater_energy_power")
    assert meter["power_w"] is None and meter["available"] is False


async def test_watched_sensor_triggers_a_heartbeat_at_most_once_a_second(
    hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any
) -> None:
    await setup_home(hass)
    pulsar.response = {"ok": True, "targets": [], "commands": [], "report_on_change": ["sensor.main_power"]}
    clock = [1000.0]
    with patch("custom_components.sun_driven_pulsar.agent.time.monotonic", lambda: clock[0]):
        await start(hass, entry)
        sent = len(pulsar.payloads)

        # An unwatched sensor changing does nothing.
        hass.states.async_set("sensor.relay_1_power", "900", POWER)
        await hass.async_block_till_done()
        assert len(pulsar.payloads) == sent

        # A second after the last heartbeat, a watched change is reported at once...
        clock[0] += 1.5
        hass.states.async_set("sensor.main_power", "5.1", {"device_class": "power", "unit_of_measurement": "kW"})
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert len(pulsar.payloads) == sent + 1
        assert next(m for m in pulsar.payloads[-1]["meters"] if m["entity_id"] == "sensor.main_power")["power_w"] == 5100.0

        # ...but changes within a second of it wait, and go together.
        clock[0] += 0.2
        for value in ("5.2", "5.3", "5.4"):
            hass.states.async_set("sensor.main_power", value, {"device_class": "power", "unit_of_measurement": "kW"})
            await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert len(pulsar.payloads) == sent + 1
        clock[0] += 0.8
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
        await hass.async_block_till_done()
        assert len(pulsar.payloads) == sent + 2
        assert next(m for m in pulsar.payloads[-1]["meters"] if m["entity_id"] == "sensor.main_power")["power_w"] == 5400.0


async def test_watching_stops_when_pulsar_stops_asking(hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any) -> None:
    await setup_home(hass)
    pulsar.response = {"ok": True, "targets": [], "commands": [], "report_on_change": ["sensor.main_power"]}
    await start(hass, entry)
    pulsar.response = {"ok": True, "targets": [], "commands": []}
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))  # the regular heartbeat
    await hass.async_block_till_done()
    sent = len(pulsar.payloads)
    hass.states.async_set("sensor.main_power", "9", {"device_class": "power", "unit_of_measurement": "kW"})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    assert len(pulsar.payloads) == sent


class _S:
    def __init__(self, entity_id: str, state: str, unit: str = "W") -> None:
        self.entity_id, self.object_id, self.state = entity_id, entity_id.split(".", 1)[1], state
        self.attributes = {"device_class": "power", "unit_of_measurement": unit}


def test_power_w_units_and_garbage() -> None:
    assert power_w(_S("sensor.a", "12.345")) == 12.35
    assert power_w(_S("sensor.a", "1.5", "kW")) == 1500.0
    assert power_w(_S("sensor.a", "1500", "mW")) == 1.5
    assert power_w(_S("sensor.a", "1", "BTU/h")) is None
    for bad in ("unknown", "unavailable", "nan", "inf", ""):
        assert power_w(_S("sensor.a", bad)) is None
    assert power_w(None) is None


def test_device_power_sensor_only_when_unambiguous() -> None:
    one = [_S("sensor.plug_power", "1")]
    assert device_power_sensor("switch.plug", one, 1) is one[0]
    # One sensor shared by two switches measures neither on its own.
    assert device_power_sensor("switch.relay_1", [_S("sensor.relay_total_power", "1")], 2) is None
    two = [_S("sensor.relay_1_power", "1"), _S("sensor.relay_10_power", "2")]
    assert device_power_sensor("switch.relay_1", two, 2) is two[0]
    assert device_power_sensor("switch.relay_3", two, 2) is None


async def test_switchables_still_leave_out_config_hidden_and_disabled(
    hass: HomeAssistant, entry: MockConfigEntry, pulsar: Any
) -> None:
    await setup_home(hass)
    add_entity(hass, "switch.child_lock", "off", entity_category=er.EntityCategory.CONFIG)
    add_entity(hass, "switch.hidden", "off", hidden_by=er.RegistryEntryHider.USER)
    add_entity(hass, "input_boolean.away", "off")
    await start(hass, entry)
    reported = {e["entity_id"] for e in pulsar.payloads[-1]["entities"]}
    assert reported == {"switch.heater", "switch.relay_1", "switch.relay_2", "light.lamp", "input_boolean.away"}
