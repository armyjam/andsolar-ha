"""Config flow for AndSolar."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .api import AndSolarClient, AndSolarError, AuthError
from .const import (
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import AndSolarConfigEntry

_LOGGER = logging.getLogger(__name__)


class AndSolarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the OpenAPI username and password."""

    VERSION = 1

    async def _validate(self, username: str, password: str, base_url: str) -> str | None:
        """Try to log in. Returns an error key, or None on success."""
        client = AndSolarClient(username, password, base_url=base_url)
        try:
            await self.hass.async_add_executor_job(client.login)
        except AuthError:
            return "invalid_auth"
        except AndSolarError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while logging in")
            return "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url = user_input.get(CONF_BASE_URL) or DEFAULT_BASE_URL
            error = await self._validate(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD], base_url
            )
            if error is None:
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={**user_input, CONF_BASE_URL: base_url},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._validate(
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: AndSolarConfigEntry) -> OptionsFlow:
        return AndSolarOptionsFlow()


class AndSolarOptionsFlow(OptionsFlow):
    """Polling interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=60)
                    )
                }
            ),
        )
