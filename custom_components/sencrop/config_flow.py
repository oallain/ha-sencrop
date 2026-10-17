"""Config flow for the Sencrop integration."""

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import (
    SencropAuthError,
    SencropClient,
    SencropConnectionError,
    SencropDevice,
    SencropError,
)
from .const import (
    CONF_DEVICES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import SencropConfigEntry

_LOGGER = logging.getLogger(__name__)

PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)
SCAN_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=1,
        unit_of_measurement="min",
        mode=NumberSelectorMode.BOX,
    )
)


def device_selector(devices: Mapping[int, SencropDevice]) -> SelectSelector:
    """Build the multi-select listing the account's devices."""
    options = []
    for device in devices.values():
        label = f"{device.name} ({device.model or 'Sencrop'})"
        if device.last_status_update:
            seen = dt_util.as_local(device.last_status_update)
            label += f" — {seen:%d/%m/%Y}"
        options.append(SelectOptionDict(value=str(device.id), label=label))
    return SelectSelector(
        SelectSelectorConfig(
            options=options, multiple=True, mode=SelectSelectorMode.LIST
        )
    )


class SencropConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sencrop."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._credentials: dict[str, str] = {}
        self._devices: dict[int, SencropDevice] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: SencropConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SencropOptionsFlow()

    async def _async_login(
        self, email: str, password: str
    ) -> tuple[SencropClient | None, int | None, dict[str, str]]:
        client = SencropClient(async_get_clientsession(self.hass), email, password)
        try:
            user_id = await client.async_login()
        except SencropAuthError:
            return None, None, {"base": "invalid_auth"}
        except SencropConnectionError:
            return None, None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error while logging in to Sencrop")
            return None, None, {"base": "unknown"}
        return client, user_id, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Sencrop app credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client, user_id, errors = await self._async_login(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if client is not None:
                await self.async_set_unique_id(str(user_id))
                self._abort_if_unique_id_configured()
                try:
                    self._devices = await client.async_get_devices()
                except SencropAuthError:
                    errors = {"base": "invalid_auth"}
                except SencropError:
                    errors = {"base": "cannot_connect"}
                else:
                    self._credentials = user_input
                    return await self.async_step_devices()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the devices to add."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_DEVICES]:
                return self.async_create_entry(
                    title=self._credentials[CONF_EMAIL],
                    data=self._credentials,
                    options={
                        CONF_DEVICES: user_input[CONF_DEVICES],
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    },
                )
            errors["base"] = "no_devices"
        named = [str(d.id) for d in self._devices.values() if d.named]
        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICES, default=named): device_selector(
                        self._devices
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client, user_id, errors = await self._async_login(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if client is not None:
                await self.async_set_unique_id(str(user_id))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class SencropOptionsFlow(OptionsFlow):
    """Change the selected devices and the polling interval."""

    config_entry: SencropConfigEntry

    def _client(self) -> SencropClient:
        """Client of the loaded entry, or a new one when setup failed."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is not None:
            return coordinator.client
        return SencropClient(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_EMAIL],
            self.config_entry.data[CONF_PASSWORD],
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_DEVICES]:
                return self.async_create_entry(
                    data={
                        CONF_DEVICES: user_input[CONF_DEVICES],
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    }
                )
            errors["base"] = "no_devices"
        try:
            devices = await self._client().async_get_devices()
        except SencropAuthError:
            return self.async_abort(reason="invalid_auth")
        except SencropError:
            return self.async_abort(reason="cannot_connect")
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICES, default=options.get(CONF_DEVICES, [])
                ): device_selector(devices),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): SCAN_INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
