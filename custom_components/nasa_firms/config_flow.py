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
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_RADIUS,
)
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
    CONF_IGNORE_ZONES,
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
    DEFAULT_ZONE_RADIUS_M,
    DOMAIN,
    MAP_KEY_URL,
    MAX_RADIUS_M,
    MAX_ZONE_RADIUS_M,
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
        if data.get(CONF_RADIUS, DEFAULT_RADIUS_M) > MAX_RADIUS_M:
            return {"base": "radius_too_large"}
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
    """Adjust filters and ignore zones without re-adding the entry."""

    def __init__(self) -> None:
        super().__init__()
        # Working copy. Options are written as a whole, so every step has to
        # carry the others along or they would be dropped on save.
        self._options: dict[str, Any] | None = None

    @property
    def options(self) -> dict[str, Any]:
        """The edit buffer, seeded from the entry on first use."""
        if self._options is None:
            self._options = dict(self.config_entry.options)
        return self._options

    @property
    def zones(self) -> list[dict[str, Any]]:
        """Ignore zones currently in the buffer."""
        return list(self.options.get(CONF_IGNORE_ZONES) or [])

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the two halves of the options: filters and ignore zones."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["filters", "zones"],
            description_placeholders={"zone_count": str(len(self.zones))},
        )

    async def async_step_filters(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Satellites, detection window, confidence and FRP thresholds."""
        if user_input is not None:
            return self.async_create_entry(data={**self.options, **user_input})
        current = {**self.config_entry.data, **self.options}
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
        return self.async_show_form(step_id="filters", data_schema=schema)

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the zones and offer to add, remove, or save."""
        menu = ["add_zone"]
        if self.zones:
            menu.append("remove_zone")
        menu.append("save_zones")
        return self.async_show_menu(
            step_id="zones",
            menu_options=menu,
            description_placeholders={"zones": self._zone_summary()},
        )

    @staticmethod
    def _zone_label(zone: dict[str, Any]) -> str:
        """Describe one zone, tolerating a hand-edited or partial entry.

        `in_ignored_zone` already skips zones it cannot read; the options flow
        has to survive them too, or a single bad entry would make the dialog
        unopenable — and therefore the bad entry unremovable.
        """
        name = str(zone.get(CONF_NAME) or "Unnamed zone")
        try:
            return (
                f"{name} — {float(zone[CONF_LATITUDE]):.4f}/"
                f"{float(zone[CONF_LONGITUDE]):.4f}, "
                f"{float(zone[CONF_RADIUS]) / 1000:.1f} km"
            )
        except (KeyError, TypeError, ValueError):
            return f"{name} — incomplete, has no effect"

    def _zone_summary(self) -> str:
        """Human-readable list for the menu description."""
        if not self.zones:
            return "None yet."
        return "\n".join(f"- {self._zone_label(z)}" for z in self.zones)

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Place one zone with the same map picker used for the main radius."""
        errors: dict[str, str] = {}
        if user_input is not None:
            location = user_input[CONF_LOCATION]
            radius = location.get(CONF_RADIUS, DEFAULT_ZONE_RADIUS_M)
            if radius > MAX_ZONE_RADIUS_M:
                errors["base"] = "zone_radius_too_large"
            else:
                zone = {
                    CONF_NAME: user_input[CONF_NAME].strip() or "Ignored area",
                    CONF_LATITUDE: location[CONF_LATITUDE],
                    CONF_LONGITUDE: location[CONF_LONGITUDE],
                    CONF_RADIUS: radius,
                }
                self.options[CONF_IGNORE_ZONES] = [*self.zones, zone]
                return await self.async_step_zones()
        schema = self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_NAME): TextSelector(),
                    vol.Required(CONF_LOCATION): LocationSelector(
                        LocationSelectorConfig(radius=True)
                    ),
                }
            ),
            user_input
            or {
                CONF_NAME: "Known heat source",
                CONF_LOCATION: {
                    CONF_LATITUDE: self.config_entry.data[CONF_LATITUDE],
                    CONF_LONGITUDE: self.config_entry.data[CONF_LONGITUDE],
                    CONF_RADIUS: DEFAULT_ZONE_RADIUS_M,
                },
            },
        )
        return self.async_show_form(
            step_id="add_zone",
            data_schema=schema,
            errors=errors,
            description_placeholders={"max_km": str(MAX_ZONE_RADIUS_M // 1000)},
        )

    async def async_step_remove_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Drop one or more zones, picked by their position in the list."""
        if user_input is not None:
            drop = {int(index) for index in user_input[CONF_IGNORE_ZONES]}
            self.options[CONF_IGNORE_ZONES] = [
                zone for i, zone in enumerate(self.zones) if i not in drop
            ]
            return await self.async_step_zones()
        options = [
            SelectOptionDict(value=str(i), label=self._zone_label(z))
            for i, z in enumerate(self.zones)
        ]
        return self.async_show_form(
            step_id="remove_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IGNORE_ZONES): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_save_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Commit the edited zone list."""
        return self.async_create_entry(data=dict(self.options))
