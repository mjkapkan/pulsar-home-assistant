"""Power readings for Pulsar's power limits.

- What a switchable entity's device draws, from a power sensor on the same
  device, so Pulsar can count measured power instead of an estimate.
- Power sensors, which a Pulsar living area can use as its meters.
"""

from __future__ import annotations

import math
from typing import Any

# Units Home Assistant power sensors report in, as factors to watts.
POWER_UNITS = {"mW": 0.001, "W": 1.0, "kW": 1000.0, "MW": 1_000_000.0}


def is_power_sensor(state: Any) -> bool:
    """Whether a sensor state is a power reading Pulsar can use."""
    return (
        state.attributes.get("device_class") == "power"
        and state.attributes.get("unit_of_measurement") in POWER_UNITS
    )


def power_w(state: Any | None) -> float | None:
    """A power sensor's reading in watts, or None when it has no number."""
    if state is None:
        return None
    factor = POWER_UNITS.get(state.attributes.get("unit_of_measurement"))
    if factor is None:
        return None
    try:
        value = float(state.state) * factor
    except (TypeError, ValueError):
        return None  # unavailable, unknown
    return round(value, 2) if math.isfinite(value) else None


def device_power_sensor(switch_entity_id: str, sensors: list[Any], switches_on_device: int) -> Any | None:
    """The power sensor that measures a switch, or None when that is unclear.

    That is the device's only power sensor when the switch is the device's only
    switch; otherwise the one named after the switch (switch.plug_1 and
    sensor.plug_1_power), as on multi-channel relays.
    """
    if len(sensors) == 1 and switches_on_device == 1:
        return sensors[0]
    prefix = switch_entity_id.split(".", 1)[1] + "_"
    named = [s for s in sensors if s.object_id.startswith(prefix)]
    return named[0] if len(named) == 1 else None
