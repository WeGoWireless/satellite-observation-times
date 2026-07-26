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

from .const import ATTRIBUTION, DOMAIN
from .coordinator import FirmsCoordinator, FirmsData, NasaFirmsConfigEntry


@dataclass(frozen=True, kw_only=True)
class FirmsSensorDescription(SensorEntityDescription):
    """Sensor description with value/attribute extractors."""

    value_fn: Callable[[FirmsData], Any]
    attributes_fn: Callable[[FirmsData], dict[str, Any]] | None = None


SENSORS: tuple[FirmsSensorDescription, ...] = (
    FirmsSensorDescription(
        key="hotspot_count",
        translation_key="hotspot_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda d: len(d.clusters),
        attributes_fn=lambda d: {
            "raw_detections": d.raw_detections,
            "per_satellite": d.per_satellite,
            "satellite_errors": d.satellite_errors,
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
    _attr_attribution = ATTRIBUTION
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
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return diagnostic attributes where defined."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator.data)
        return None
