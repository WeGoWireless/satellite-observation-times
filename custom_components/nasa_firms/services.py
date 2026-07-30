"""The get_wind action: the wind at one named fire, on demand.

The per-cycle lookups cover the N nearest fires and no more — that is a
budget, and budgets do not bend for interesting fires. This action is the
other half of the deal: any single fire can be asked about at any time, it
costs nothing until called, and one call is one met.no request at most —
usually zero, because it goes through the same keyed cache as the cycle.
The client's global backoff applies here too, so the action cannot be used
to hammer met.no when it is already refusing us.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import FirmsCluster, WeatherError, cardinal, smoke_offset
from .const import DOMAIN
from .coordinator import FirmsCoordinator

SERVICE_GET_WIND = "get_wind"
ATTR_ENTITY_ID = "entity_id"

GET_WIND_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})


def _find_fire(
    hass: HomeAssistant, entity_id: str
) -> tuple[FirmsCoordinator, FirmsCluster] | None:
    """The coordinator and cluster behind a fire entity id, if it is live.

    Goes through the cluster-id -> entity-id register the geo_location
    entities maintain, which is also what the nearest-hotspot sensor uses —
    so whatever entity id a user copied from there resolves here.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: FirmsCoordinator = entry.runtime_data
        for cluster_id, known_id in coordinator.entity_ids.items():
            if known_id != entity_id:
                continue
            cluster = coordinator.data.clusters_by_id.get(cluster_id)
            if cluster is not None:
                return coordinator, cluster
    return None


async def _async_get_wind(call: ServiceCall) -> ServiceResponse:
    """Look up the wind at one fire's own coordinates and describe it."""
    entity_id = call.data[ATTR_ENTITY_ID]
    found = _find_fire(call.hass, entity_id)
    if found is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_fire",
            translation_placeholders={"entity_id": entity_id},
        )
    coordinator, cluster = found
    try:
        wind = await coordinator.weather.wind_at(cluster.latitude, cluster.longitude)
    except WeatherError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="wind_unavailable"
        ) from err
    if wind is None:
        # Backed off, or the forecast holds no usable step. The caller asked a
        # direct question; "I don't know" must be an error, not a dict of
        # nulls that templates its way into an automation unnoticed.
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="wind_unavailable"
        )
    return {
        # Same values, same rounding as the attributes on the fire itself.
        "wind_bearing": round(wind.bearing),
        "wind_direction": cardinal(wind.bearing),
        "wind_speed": round(wind.speed, 1),
        "smoke_offset": (
            round(smoke_offset(wind.bearing, cluster.bearing))
            if cluster.bearing is not None
            else None
        ),
        # Which forecast step answered — the honest "how fresh is this".
        "forecast_time": wind.time,
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the domain's actions. Called once, from async_setup."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_WIND,
        _async_get_wind,
        schema=GET_WIND_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
