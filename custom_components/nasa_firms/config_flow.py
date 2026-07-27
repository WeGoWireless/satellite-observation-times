"""Config flow for NASA FIRMS."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LOCATION, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
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

from .api import (
    REGIONS,
    SATELLITES,
    WINDOW_24H,
    WINDOW_7D,
    FirmsAuthError,
    FirmsClient,
    FirmsError,
    bbox_around,
)
from .const import (
    CONF_MAP_KEY,
    CONF_MIN_CONFIDENCE,
    CONF_MIN_FRP,
    CONF_REGION,
    CONF_SATELLITES,
    CONF_WINDOW,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_FRP,
    DEFAULT_RADIUS_M,
    DEFAULT_REGION,
    DEFAULT_SATELLITES,
    DOMAIN,
    MAP_KEY_URL,
)

_LOGGER = logging.getLogger(__name__)

SATELLITE_OPTIONS = [SelectOptionDict(value=k, label=v) for k, v in SATELLITES.items()]
WINDOW_OPTIONS = [
    SelectOptionDict(value=WINDOW_24H, label="Last 24 hours"),
    SelectOptionDict(value=WINDOW_7D, label="Last 7 days"),
]
CONFIDENCE_OPTIONS = [
    SelectOptionDict(value="any", label="Any (include low)"),
    SelectOptionDict(value="nominal", label="Nominal or higher"),
    SelectOptionDict(value="high", label="High only"),
]

# Shared between initial setup and the options flow.
FILTER_SCHEMA = {
    vol.Required(CONF_SATELLITES, default=DEFAULT_SATELLITES): SelectSelector(
        SelectSelectorConfig(
            options=SATELLITE_OPTIONS, multiple=True, mode=SelectSelectorMode.LIST
        )
    ),
    vol.Required(CONF_WINDOW, default=WINDOW_24H): SelectSelector(
        SelectSelectorConfig(options=WINDOW_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
    ),
    vol.Required(CONF_MIN_CONFIDENCE, default=DEFAULT_MIN_CONFIDENCE): SelectSelector(
        SelectSelectorConfig(
            options=CONFIDENCE_OPTIONS, mode=SelectSelectorMode.DROPDOWN
        )
    ),
    vol.Required(CONF_MIN_FRP, default=DEFAULT_MIN_FRP): NumberSelector(
        NumberSelectorConfig(
            min=0, max=10000, step=0.1, mode=NumberSelectorMode.BOX,
            unit_of_measurement="MW",
        )
    ),
}

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MAP_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_REGION, default=DEFAULT_REGION): SelectSelector(
            SelectSelectorConfig(options=REGIONS, mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_LOCATION): LocationSelector(
            LocationSelectorConfig(radius=True)
        ),
        **FILTER_SCHEMA,
    }
)


class NasaFirmsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input.pop(CONF_LOCATION)
            data = {
                **user_input,
                CONF_LATITUDE: location[CONF_LATITUDE],
                CONF_LONGITUDE: location[CONF_LONGITUDE],
                CONF_RADIUS: location.get(CONF_RADIUS, DEFAULT_RADIUS_M),
            }
            await self.async_set_unique_id(
                f"{data[CONF_REGION]}-{data[CONF_LATITUDE]:.3f}-{data[CONF_LONGITUDE]:.3f}"
            )
            self._abort_if_unique_id_configured()
            errors = await self._validate(data)
            if not errors:
                # The MAP_KEY goes into entry.data only — never into the
                # title, which is shown all over the UI.
                return self.async_create_entry(
                    title=f"FIRMS {data[CONF_LATITUDE]:.2f}/{data[CONF_LONGITUDE]:.2f}",
                    data=data,
                )
            user_input[CONF_LOCATION] = location
        schema = self.add_suggested_values_to_schema(
            USER_SCHEMA,
            user_input
            or {
                CONF_LOCATION: {
                    CONF_LATITUDE: self.hass.config.latitude,
                    CONF_LONGITUDE: self.hass.config.longitude,
                    CONF_RADIUS: DEFAULT_RADIUS_M,
                }
            },
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"map_key_url": MAP_KEY_URL},
        )

    async def _validate(self, data: dict[str, Any]) -> dict[str, str]:
        """Try a minimal fetch to validate key, region and reachability."""
        if not data.get(CONF_SATELLITES):
            return {"base": "no_satellites"}
        client = FirmsClient(
            async_get_clientsession(self.hass), data[CONF_MAP_KEY], data[CONF_REGION]
        )
        bbox = bbox_around(
            data[CONF_LATITUDE], data[CONF_LONGITUDE], data[CONF_RADIUS] / 1000
        )
        try:
            await client.fetch(
                data[CONF_SATELLITES][0], data[CONF_WINDOW], bbox, count=1
            )
        except FirmsAuthError:
            return {"base": "invalid_auth"}
        except FirmsError:
            _LOGGER.exception("Validation fetch failed")
            return {"base": "cannot_connect"}
        return {}

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauth when FIRMS rejects the stored MAP_KEY."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new MAP_KEY."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_MAP_KEY: user_input[CONF_MAP_KEY]}
            errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAP_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NasaFirmsOptionsFlow:
        """Create the options flow."""
        return NasaFirmsOptionsFlow()


class NasaFirmsOptionsFlow(OptionsFlow):
    """Adjust satellites, window and filters without re-adding the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        schema = self.add_suggested_values_to_schema(
            vol.Schema(FILTER_SCHEMA),
            {
                key: current[key]
                for key in (
                    CONF_SATELLITES,
                    CONF_WINDOW,
                    CONF_MIN_CONFIDENCE,
                    CONF_MIN_FRP,
                )
                if key in current
            },
        )
        return self.async_show_form(step_id="init", data_schema=schema)
