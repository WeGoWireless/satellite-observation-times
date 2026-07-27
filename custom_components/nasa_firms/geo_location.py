"""Geolocation events: one map entity per deduplicated fire."""
from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import datetime

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
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
    def _publish_entity_ids(_now: datetime) -> None:
        """Re-render the aggregate sensors once our entity ids exist.

        Must carry @callback: async_call_later hands a plain function to the
        executor, and the state writes downstream of async_update_listeners()
        then happen off the event loop, which Home Assistant rejects outright
        for custom integrations.
        """
        coordinator.async_update_listeners()

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
            # entity_ids only exist once Home Assistant has actually added the
            # entities, which happens after this callback returns. Nudge the
            # aggregate sensors shortly afterwards so `nearest_entity_id` is
            # populated right away instead of staying None until the next
            # 15-minute refresh.
            async_call_later(hass, 2, _publish_entity_ids)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


# The map card ignores `icon` for anything it pulls in through
# `geo_location_sources`: those entities arrive as bare entity ids, and only
# entities listed one by one can carry the `label_mode: icon` that would make
# it read the icon. Without a picture the marker falls back to the first
# letters of the name, so every fire showed up as "Wh4". What the card does
# honour for source-fed entities is `entity_picture`, which it renders as the
# marker's background image — so the flame has to travel as a picture.
#
# Sized 24x24 to match the 48px marker at 2x, drawn full-bleed because the
# card clips it to a circle anyway. One module-level constant: it is the same
# picture for every fire, and it ends up in the state attributes of each one.
_MARKER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="12" fill="#d84315"/>'
    '<path fill="#fff" d="M12 2.5c0 2.6 1.2 3.8 2.6 5.3C16.2 9.5 17.7 11.3 17.7 14'
    'a5.7 5.7 0 0 1-11.4 0c0-1.9.7-3.4 2-4.7 0 1.5.6 2.6 1.6 2.6 1.3 0 1.9-1.3 '
    '1.5-3-.3-1.9-.8-4-.4-6.4z"/>'
    "</svg>"
)
# base64 rather than percent-encoding: the card drops the value straight into
# an unquoted CSS url(), where raw angle brackets and spaces would break it.
MARKER_PICTURE = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(_MARKER_SVG.encode()).decode()
)


class FirmsFireEntity(CoordinatorEntity[FirmsCoordinator], GeolocationEvent):
    """A deduplicated fire hotspot on the map."""

    _attr_should_poll = False
    _attr_source = GEO_SOURCE
    # Kept as the fallback for anything that draws an icon rather than a
    # picture — a tile card, for one. Note it is *not* a second chance to see
    # mdi:fire next to the picture: wherever Home Assistant's state badge is
    # used (entity rows, the more-info header) the picture wins outright.
    _attr_icon = "mdi:fire"
    _attr_entity_picture = MARKER_PICTURE
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

    async def async_added_to_hass(self) -> None:
        """Publish our entity_id so the aggregate sensors can point at us."""
        await super().async_added_to_hass()
        self.coordinator.entity_ids[self.cluster_id] = self.entity_id

    async def async_will_remove_from_hass(self) -> None:
        """Drop our entry again when the fire is gone."""
        self.coordinator.entity_ids.pop(self.cluster_id, None)
        await super().async_will_remove_from_hass()

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
