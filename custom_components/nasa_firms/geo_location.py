"""Geolocation events: one map entity per deduplicated fire."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, GEO_SOURCE
from .coordinator import FirmsCoordinator, NasaFirmsConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NasaFirmsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Track coordinator updates and manage the dynamic set of fire entities."""
    coordinator = entry.runtime_data
    tracked: set[str] = set()

    @callback
    def _sync() -> None:
        new = [
            FirmsFireEntity(coordinator, cluster_id, tracked.discard)
            for cluster_id in coordinator.data.clusters_by_id
            if cluster_id not in tracked
        ]
        tracked.update(entity.cluster_id for entity in new)
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class FirmsFireEntity(CoordinatorEntity[FirmsCoordinator], GeolocationEvent):
    """A deduplicated fire hotspot on the map."""

    _attr_should_poll = False
    _attr_source = GEO_SOURCE
    _attr_icon = "mdi:fire"
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: FirmsCoordinator,
        cluster_id: str,
        untrack: Callable[[str], None],
    ) -> None:
        super().__init__(coordinator)
        self.cluster_id = cluster_id
        # Deliberately NOT named _on_remove — that attribute exists on the
        # Entity base class (list of remove callbacks) and must not be shadowed.
        self._untrack = untrack
        self._attr_name = f"Wildfire hotspot {cluster_id}"
        self._update_from_cluster()

    def _update_from_cluster(self) -> None:
        cluster = self.coordinator.data.clusters_by_id[self.cluster_id]
        self._attr_latitude = cluster.latitude
        self._attr_longitude = cluster.longitude
        self._attr_distance = cluster.distance_km
        self._attr_extra_state_attributes = {
            "frp_mw": cluster.frp,
            "confidence": cluster.confidence,
            "satellites": cluster.satellites,
            "detections": cluster.detections,
            "brightness_k": cluster.brightness,
            "acquired": cluster.acq_datetime,
            "daynight": cluster.daynight,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update in place, or remove ourselves when the fire is gone."""
        if self.cluster_id not in self.coordinator.data.clusters_by_id:
            self._untrack(self.cluster_id)
            self.hass.async_create_task(self.async_remove(force_remove=True))
            return
        self._update_from_cluster()
        self.async_write_ha_state()
