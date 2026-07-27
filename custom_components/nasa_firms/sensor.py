"""Aggregate sensors: hotspot count, nearest distance, max FRP."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, ATTRIBUTION_WEATHER, DOMAIN
from .coordinator import FirmsCoordinator, FirmsData, NasaFirmsConfigEntry


@dataclass(frozen=True, kw_only=True)
class FirmsSensorDescription(SensorEntityDescription):
    """Sensor description with value/attribute extractors.

    `attributes_fn` takes the coordinator rather than just its data, because the
    nearest-hotspot attributes need the cluster-id -> entity_id register that
    the geo_location entities maintain.
    """

    value_fn: Callable[[FirmsData], Any]
    attributes_fn: Callable[[FirmsCoordinator], dict[str, Any]] | None = None
    # Set where the sensor can carry met.no data, so their CC BY credit shows
    # up exactly while it does.
    uses_weather: bool = False


def _nearest_attributes(coordinator: FirmsCoordinator) -> dict[str, Any]:
    """Pointer to the closest fire, its bearing, and the wind at it.

    The entity id is the useful part: it unlocks every attribute of that fire
    instead of only the fields duplicated here.

    `wind_bearing` is the direction the wind blows *from* at the fire's own
    coordinates, in the same frame as `bearing`, which is what makes the two
    directly comparable. Both are plain observations — whether that is good or
    bad news depends on terrain, fuel and how the wind turns next, so the
    integration reports and the user judges.
    """
    clusters = coordinator.data.clusters
    wind = coordinator.data.nearest_wind
    if not clusters:
        return {
            "nearest_entity_id": None,
            "bearing": None,
            "direction": None,
            "wind_bearing": None,
            "wind_speed": None,
        }
    nearest = clusters[0]  # coordinator sorts by distance
    return {
        "nearest_entity_id": coordinator.entity_ids.get(nearest.id),
        "bearing": nearest.bearing,
        "direction": nearest.direction,
        "wind_bearing": round(wind.bearing) if wind else None,
        "wind_speed": round(wind.speed, 1) if wind else None,
    }


SENSORS: tuple[FirmsSensorDescription, ...] = (
    FirmsSensorDescription(
        key="hotspot_count",
        translation_key="hotspot_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda d: len(d.clusters),
        attributes_fn=lambda c: {
            "raw_detections": c.data.raw_detections,
            "per_satellite": c.data.per_satellite,
            "satellite_errors": c.data.satellite_errors,
        },
    ),
    FirmsSensorDescription(
        key="nearest_distance",
        translation_key="nearest_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.nearest_km,
        attributes_fn=_nearest_attributes,
        uses_weather=True,
    ),
    FirmsSensorDescription(
        key="max_frp",
        translation_key="max_frp",
        native_unit_of_measurement="MW",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:heat-wave",
        suggested_display_precision=1,
        value_fn=lambda d: d.max_frp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NasaFirmsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the aggregate sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        FirmsSensor(coordinator, entry, description) for description in SENSORS
    )


class FirmsSensor(CoordinatorEntity[FirmsCoordinator], SensorEntity):
    """One aggregate value derived from the current fire clusters."""

    _attr_has_entity_name = True
    entity_description: FirmsSensorDescription

    def __init__(
        self,
        coordinator: FirmsCoordinator,
        entry: NasaFirmsConfigEntry,
        description: FirmsSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="NASA FIRMS",
            model="Active fire data (VIIRS/MODIS)",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def attribution(self) -> str:
        """Credit met.no as well, but only while we are showing their data."""
        if self.entity_description.uses_weather and self.coordinator.data.nearest_wind:
            return f"{ATTRIBUTION}. {ATTRIBUTION_WEATHER}"
        return ATTRIBUTION

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return diagnostic attributes where defined."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator)
        return None
