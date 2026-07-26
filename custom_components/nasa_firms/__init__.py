"""The NASA FIRMS Wildfire Monitor integration."""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FirmsClient
from .const import CONF_MAP_KEY, CONF_REGION
from .coordinator import FirmsCoordinator, NasaFirmsConfigEntry

PLATFORMS = [Platform.GEO_LOCATION, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: NasaFirmsConfigEntry) -> bool:
    """Set up NASA FIRMS from a config entry."""
    client = FirmsClient(
        async_get_clientsession(hass), entry.data[CONF_MAP_KEY], entry.data[CONF_REGION]
    )
    coordinator = FirmsCoordinator(hass, entry, client)
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
