"""Config flow for SwitcheOn."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SwitcheOnApi, SwitcheOnApiError
from .const import DOMAIN


async def _validate(hass: HomeAssistant, data: dict) -> None:
    """Validate credentials by reading the account endpoint."""
    api = SwitcheOnApi(async_get_clientsession(hass), data[CONF_EMAIL], data[CONF_PASSWORD])
    await api.async_get_boxes()


class SwitcheOnConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await _validate(self.hass, user_input)
            except SwitcheOnApiError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(user_input[CONF_EMAIL].casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="SwitcheOn", data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )
