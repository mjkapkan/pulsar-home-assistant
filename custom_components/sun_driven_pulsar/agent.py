"""The heartbeat loop: report entities to Pulsar and apply what it wants.

Behaviour (see README):
- A target is applied only when it differs from the last target applied to
  that entity, so manual changes in Home Assistant are kept until Pulsar's
  desired state next changes.
- Pulsar switches off only runs it switched on itself. A device already on
  when Pulsar wants it on (an automation's run, or by hand) is not Pulsar's;
  neither is one someone switched since. Such runs are left on when Pulsar's
  slot ends, for whoever started them to end.
- One-off commands from the Pulsar UI are applied unless valid_until passed.
- If Pulsar is unreachable for failsafe_after_s, every entity Pulsar controls
  is switched to the failsafe state (on) once. A device is never held off
  indefinitely because Pulsar went away.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    __version__ as HA_VERSION,
)
from homeassistant.core import CALLBACK_TYPE, Context, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .api import PulsarAuthError, PulsarClient, PulsarError
from .const import (
    CONF_API_KEY,
    CONF_URL,
    DEFAULT_FAILSAFE_AFTER_S,
    DEFAULT_FAILSAFE_STATE,
    DEFAULT_HEARTBEAT_INTERVAL_S,
    DOMAIN,
    MAX_PENDING_RESULTS,
    MIN_HEARTBEAT_INTERVAL_S,
    REPORT_AFTER_SWITCH_S,
    STORAGE_VERSION,
    SWITCHABLE_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)


class PulsarAgent:
    """Runs the heartbeat for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._client = PulsarClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY])
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        self._unsub: CALLBACK_TYPE | None = None
        self._unsub_report: CALLBACK_TYPE | None = None
        # Entities whose on/off changes are followed, to know who switched them.
        self._tracked: tuple[str, ...] = ()
        self._unsub_tracked: CALLBACK_TYPE | None = None
        # Contexts of Pulsar's own service calls: a state change with one of them is Pulsar's.
        self._contexts: deque[str] = deque(maxlen=50)
        self._integration_version = "unknown"
        self._interval_s = DEFAULT_HEARTBEAT_INTERVAL_S
        self._failsafe_after_s = DEFAULT_FAILSAFE_AFTER_S
        self._failsafe_state = DEFAULT_FAILSAFE_STATE
        # Persisted across restarts.
        self._applied: dict[str, str] = {}
        # Entities on because Pulsar switched them on, untouched since: the only runs it ends.
        self._owned: set[str] = set()
        self._pending_results: list[dict[str, Any]] = []
        self._last_success: float | None = None
        self._failsafe_active = False

    async def async_start(self) -> None:
        """Load saved state and start heartbeating."""
        saved = await self._store.async_load() or {}
        self._applied = dict(saved.get("applied", {}))
        self._owned = set(saved.get("owned", []))
        self._pending_results = list(saved.get("pending_results", []))
        self._last_success = saved.get("last_success")
        self._failsafe_active = bool(saved.get("failsafe_active", False))
        self._failsafe_after_s = int(saved.get("failsafe_after_s", DEFAULT_FAILSAFE_AFTER_S))
        self._failsafe_state = saved.get("failsafe_state", DEFAULT_FAILSAFE_STATE)
        self._integration_version = str((await async_get_integration(self.hass, DOMAIN)).version)
        self._track()
        self._schedule(self._interval_s)
        self.entry.async_create_background_task(self.hass, self.async_heartbeat(), "pulsar first heartbeat")

    async def async_stop(self) -> None:
        """Stop heartbeating and save state."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._unsub_report:
            self._unsub_report()
            self._unsub_report = None
        if self._unsub_tracked:
            self._unsub_tracked()
            self._unsub_tracked = None
        self._tracked = ()
        await self._save()

    def _schedule(self, seconds: int) -> None:
        if self._unsub:
            self._unsub()
        self._unsub = async_track_time_interval(
            self.hass, self._handle_interval, timedelta(seconds=seconds), name="pulsar heartbeat"
        )

    async def _handle_interval(self, _now: Any) -> None:
        await self.async_heartbeat()

    async def async_heartbeat(self) -> None:
        """One exchange with Pulsar. Never raises."""
        if self._lock.locked():
            return  # The previous heartbeat is still running.
        switched = 0
        async with self._lock:
            results = self._pending_results[:MAX_PENDING_RESULTS]
            payload = {
                "integration_version": self._integration_version,
                "ha_version": HA_VERSION,
                "location_name": (self.hass.config.location_name or "")[:120],
                "entities": self._collect_entities(),
                "results": results,
            }
            try:
                response = await self._client.heartbeat(payload)
            except PulsarAuthError:
                _LOGGER.warning("Pulsar no longer accepts this Home Assistant; re-pair it to continue")
                if self._unsub:
                    self._unsub()
                    self._unsub = None
                self.entry.async_start_reauth(self.hass)
                return
            except PulsarError as err:
                _LOGGER.debug("Pulsar heartbeat failed: %s", err)
                await self._maybe_failsafe()
                return

            # Delivered: drop the results we sent.
            self._pending_results = self._pending_results[len(results):]
            self._last_success = dt_util.utcnow().timestamp()
            if self._failsafe_active:
                _LOGGER.info("Pulsar is reachable again; resuming its schedule")
            self._failsafe_active = False
            self._failsafe_after_s = int(response.get("failsafe_after_s", self._failsafe_after_s))
            if response.get("failsafe_state") in ("on", "off"):
                self._failsafe_state = response["failsafe_state"]
            interval = max(MIN_HEARTBEAT_INTERVAL_S, int(response.get("heartbeat_interval_s", self._interval_s)))
            if interval != self._interval_s:
                self._interval_s = interval
                self._schedule(interval)

            switched = await self._apply_targets(response.get("targets") or [])
            switched += await self._apply_commands(response.get("commands") or [])
            await self._save()

        if switched and self._unsub is not None:
            # Report the new states and results now rather than at the next heartbeat.
            if self._unsub_report:
                self._unsub_report()
            self._unsub_report = async_call_later(self.hass, REPORT_AFTER_SWITCH_S, self._handle_report)

    async def _handle_report(self, _now: Any) -> None:
        self._unsub_report = None
        await self.async_heartbeat()

    def _collect_entities(self) -> list[dict[str, Any]]:
        """Switchable entities, without configuration/diagnostic, hidden or disabled ones."""
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        entities: list[dict[str, Any]] = []
        for state in self.hass.states.async_all(SWITCHABLE_DOMAINS):
            entry = ent_reg.async_get(state.entity_id)
            if entry is not None and (
                entry.entity_category is not None or entry.hidden_by is not None or entry.disabled_by is not None
            ):
                continue
            area_id = entry.area_id if entry else None
            if area_id is None and entry is not None and entry.device_id:
                device = dev_reg.async_get(entry.device_id)
                area_id = device.area_id if device else None
            area = area_reg.async_get_area(area_id) if area_id else None
            entities.append(
                {
                    "entity_id": state.entity_id,
                    "name": state.name[:200],
                    "domain": state.domain,
                    "state": state.state[:64],
                    "available": state.state != STATE_UNAVAILABLE,
                    "area": area.name[:120] if area else None,
                }
            )
        return entities[:1000]

    async def _apply_targets(self, targets: list[dict[str, Any]]) -> int:
        """Apply targets that changed. Returns how many entities it tried to switch."""
        switched = 0
        targeted: set[str] = set()
        for target in targets:
            entity_id, want = target.get("entity_id"), target.get("state")
            if not isinstance(entity_id, str) or want not in ("on", "off"):
                continue
            targeted.add(entity_id)
            if self._applied.get(entity_id) == want:
                continue  # Unchanged: leave manual changes alone.
            current = self.hass.states.get(entity_id)
            if current is not None and current.state == "on" and (want == "on" or entity_id not in self._owned):
                # Already on: nothing to switch. Not Pulsar's run unless it switched it on
                # itself (owned), so at the end of the slot it is left to whoever did.
                if want == "off":
                    _LOGGER.info("Leaving %s on: it was switched on by something other than Pulsar", entity_id)
                self._applied[entity_id] = want
                continue
            error = await self._switch(entity_id, want)
            switched += 1
            self._record(entity_id, want, "schedule", None, error)
            if error is None:
                self._applied[entity_id] = want
        # Forget entities Pulsar no longer controls, so linking one again applies its target.
        for entity_id in list(self._applied):
            if entity_id not in targeted:
                del self._applied[entity_id]
                self._owned.discard(entity_id)
        self._track()
        return switched

    async def _apply_commands(self, commands: list[dict[str, Any]]) -> int:
        """Apply one-off commands. Returns how many entities it tried to switch."""
        switched = 0
        now = dt_util.utcnow()
        for command in commands:
            entity_id, want, command_id = command.get("entity_id"), command.get("state"), command.get("id")
            if not isinstance(entity_id, str) or want not in ("on", "off"):
                continue
            valid_until = dt_util.parse_datetime(str(command.get("valid_until") or ""))
            if valid_until is None or valid_until <= now:
                self._record(entity_id, want, "command", command_id, "expired before it arrived")
                continue
            self._record(entity_id, want, "command", command_id, await self._switch(entity_id, want))
            switched += 1
        return switched

    async def _maybe_failsafe(self) -> None:
        if self._failsafe_active or self._last_success is None or not self._applied:
            return
        offline_s = dt_util.utcnow().timestamp() - self._last_success
        if offline_s < self._failsafe_after_s:
            return
        _LOGGER.warning(
            "Pulsar unreachable for %d s; switching %d entities %s (failsafe)",
            offline_s, len(self._applied), self._failsafe_state,
        )
        for entity_id in list(self._applied):
            error = await self._switch(entity_id, self._failsafe_state)
            self._record(entity_id, self._failsafe_state, "failsafe", None, error)
            if error is None:
                self._applied[entity_id] = self._failsafe_state
        self._failsafe_active = True
        await self._save()

    def _track(self, *extra: str) -> None:
        """Follow on/off changes of the entities Pulsar controls (and `extra`)."""
        wanted = tuple(sorted(set(self._applied) | self._owned | set(extra)))
        if wanted == self._tracked:
            return
        if self._unsub_tracked:
            self._unsub_tracked()
            self._unsub_tracked = None
        self._tracked = wanted
        if wanted:
            self._unsub_tracked = async_track_state_change_event(self.hass, list(wanted), self._handle_state_change)

    @callback
    def _handle_state_change(self, event: Event) -> None:
        """Who switched it: Pulsar (one of its contexts) owns the run it switched on."""
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if new is None or new.state not in ("on", "off"):
            return
        entity_id = event.data["entity_id"]
        if new.context.id in self._contexts:
            if new.state == "on":
                self._owned.add(entity_id)
            else:
                self._owned.discard(entity_id)
        elif old is not None and old.state in ("on", "off") and old.state != new.state:
            # Switched by someone else (an automation, by hand): no longer Pulsar's.
            # Unavailable/unknown flaps, e.g. while Home Assistant starts, don't count.
            self._owned.discard(entity_id)

    async def _switch(self, entity_id: str, state: str) -> str | None:
        """Turn an entity on or off. Returns an error message, or None on success."""
        domain = entity_id.split(".", 1)[0]
        if domain not in SWITCHABLE_DOMAINS:
            return f"Pulsar cannot switch {domain} entities"
        if self.hass.states.get(entity_id) is None:
            return "entity not found in Home Assistant"
        # The state change carries this context, so the run is known to be Pulsar's.
        context = Context()
        self._contexts.append(context.id)
        self._track(entity_id)
        try:
            await self.hass.services.async_call(
                domain,
                SERVICE_TURN_ON if state == "on" else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
                context=context,
            )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Could not switch %s %s: %s", entity_id, state, err)
            return str(err)[:500] or type(err).__name__
        _LOGGER.debug("Switched %s %s", entity_id, state)
        return None

    def _record(self, entity_id: str, state: str, source: str, command_id: str | None, error: str | None) -> None:
        self._pending_results.append(
            {
                "entity_id": entity_id,
                "state": state,
                "source": source,
                "command_id": command_id,
                "success": error is None,
                "error": error,
                "at": dt_util.utcnow().isoformat(),
            }
        )
        # Keep the newest if Pulsar has been away for a long time.
        self._pending_results = self._pending_results[-MAX_PENDING_RESULTS:]

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "applied": self._applied,
                "owned": sorted(self._owned),
                "pending_results": self._pending_results,
                "last_success": self._last_success,
                "failsafe_active": self._failsafe_active,
                "failsafe_after_s": self._failsafe_after_s,
                "failsafe_state": self._failsafe_state,
            }
        )
