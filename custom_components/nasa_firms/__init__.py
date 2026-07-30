"""The NASA FIRMS Wildfire Monitor integration."""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_validation import config_entry_only_config_schema
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_loaded_integration

from .api import FirmsClient, MetNoClient
from .const import CONF_MAP_KEY, CONF_REGION, DOMAIN, USER_AGENT
from .coordinator import FirmsCoordinator, NasaFirmsConfigEntry
from .services import async_setup_services

PLATFORMS = [Platform.GEO_LOCATION, Platform.SENSOR]

CONFIG_SCHEMA = config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the domain's actions.

    Done here rather than in async_setup_entry so the action exists exactly
    once, whatever the number of entries — it resolves the entry from the
    fire entity it is called with.
    """
    async_setup_services(hass)
    return True


@callback
def _async_repair_region(hass: HomeAssistant, entry: NasaFirmsConfigEntry) -> None:
    """Rewrite the one stored region name that never worked.

    `Russia_and_Asia` was offered in the setup dropdown from the first release
    but is not a FIRMS region — the service is called `Russia_Asia`, and the
    wrong name is an HTTP 400 on every single fetch. Anyone who picked it
    cannot repair it themselves any more either, because the dropdown is gone
    and the region follows from the coordinates now.

    Only this one value is touched. A region that is merely an odd choice for
    a location still works, and rewriting those would undo a deliberate pick
    in one of the overlaps.
    """
    if entry.data.get(CONF_REGION) != "Russia_and_Asia":
        return
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REGION: "Russia_Asia"}
    )


async def async_setup_entry(hass: HomeAssistant, entry: NasaFirmsConfigEntry) -> bool:
    """Set up NASA FIRMS from a config entry."""
    _async_repair_region(hass, entry)
    session = async_get_clientsession(hass)
    client = FirmsClient(session, entry.data[CONF_MAP_KEY], entry.data[CONF_REGION])
    weather = MetNoClient(
        session,
        USER_AGENT.format(version=async_get_loaded_integration(hass, DOMAIN).version),
    )
    coordinator = FirmsCoordinator(hass, entry, client, weather)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: NasaFirmsConfigEntry
) -> None:
    """Reload on options change so the coordinator picks up new filters."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NasaFirmsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
