"""Pair Home Assistant with Pulsar using a code shown in the Pulsar app."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.data_entry_flow import section
from homeassistant.helpers import instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import PulsarClient, PulsarConnectionError, PulsarError, PulsarInvalidCode
from .const import CONF_API_KEY, CONF_INSTALLATION_ID, CONF_PAIRING_CODE, CONF_URL, DEFAULT_URL, DOMAIN

# Collapsed by default; only needed to point at a test server.
ADVANCED = "advanced"


class PulsarConfigFlow(ConfigFlow, domain=DOMAIN):
    """One Pulsar connection per Home Assistant."""

    VERSION = 1

    async def _async_enroll(self, url: str, code: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
        client = PulsarClient(async_get_clientsession(self.hass), url)
        try:
            result = await client.enroll(
                pairing_code=code.strip(),
                instance_id=await instance_id.async_get(self.hass),
                integration_version=str((await async_get_integration(self.hass, DOMAIN)).version),
                ha_version=HA_VERSION,
                location_name=(self.hass.config.location_name or "")[:120],
            )
        except PulsarInvalidCode:
            return None, {"base": "invalid_code"}
        except PulsarConnectionError:
            return None, {"base": "cannot_connect"}
        except PulsarError:
            return None, {"base": "unknown"}
        if not result.get("api_key") or not result.get("installation_id"):
            return None, {"base": "unknown"}
        return result, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the pairing code."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = str((user_input.get(ADVANCED) or {}).get(CONF_URL) or DEFAULT_URL).rstrip("/")
            result, errors = await self._async_enroll(url, user_input[CONF_PAIRING_CODE])
            if result:
                return self.async_create_entry(
                    title=self.hass.config.location_name or "Pulsar",
                    data={
                        CONF_URL: url,
                        CONF_INSTALLATION_ID: result["installation_id"],
                        CONF_API_KEY: result["api_key"],
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_PAIRING_CODE): str,
                vol.Optional(ADVANCED): section(
                    vol.Schema({vol.Optional(CONF_URL, default=DEFAULT_URL): str}), {"collapsed": True}
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Pulsar rejected the key: the installation was disconnected or paired again."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for a new pairing code."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._async_enroll(entry.data[CONF_URL], user_input[CONF_PAIRING_CODE])
            if result:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_INSTALLATION_ID: result["installation_id"],
                        CONF_API_KEY: result["api_key"],
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PAIRING_CODE): str}),
            errors=errors,
        )
