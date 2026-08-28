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
from homeassistant.const import UnitOfLength, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import bearing_deg, cardinal, smoke_offset
from .const import ATTRIBUTION, ATTRIBUTION_WEATHER, DOMAIN
from .coordinator import FirmsCoordinator, FirmsData, NasaFirmsConfigEntry
from .ngfs_coordinator import NgfsCoordinator


KM_TO_MILES = 0.621371192237334

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
    directly comparable — the degrees are what any upwind/downwind template
    needs. `wind_direction` is the same value as a compass point, mirroring
    `bearing`/`direction`, because that is what reads well on a dashboard.

    All of them are plain observations — whether that is good or bad news
    depends on terrain, fuel and how the wind turns next, so the integration
    reports and the user judges.
    """
    clusters = coordinator.data.clusters
    wind = coordinator.data.nearest_wind
    if not clusters:
        return {
            "nearest_entity_id": None,
            "bearing": None,
            "direction": None,
            "wind_bearing": None,
            "wind_direction": None,
            "wind_speed": None,
            "smoke_offset": None,
        }
    nearest = clusters[0]  # coordinator sorts by distance
    has_offset = wind is not None and nearest.bearing is not None
    return {
        "nearest_entity_id": coordinator.entity_ids.get(nearest.id),
        "bearing": nearest.bearing,
        "direction": nearest.direction,
        "wind_bearing": round(wind.bearing) if wind else None,
        "wind_direction": cardinal(wind.bearing) if wind else None,
        "wind_speed": round(wind.speed, 1) if wind else None,
        # The angle between where that wind pushes the smoke and the line
        # from the fire to you — the finished number behind the card's
        # towards/past/away wording, so no template has to carry the
        # arithmetic. 0 = straight at you, 180 = straight away. Geometry,
        # not danger. This sensor keeps its None convention; on the fire
        # entities the same attributes are absent instead.
        "smoke_offset": (
            round(smoke_offset(wind.bearing, nearest.bearing)) if has_offset else None
        ),
    }


def _max_frp_attributes(coordinator: FirmsCoordinator) -> dict[str, Any]:
    """Pointer to the fire behind the maximum — the nearest_entity_id move.

    Asked for in the community thread by the one user running this as
    infrastructure: the sensor said how strong the strongest fire is, but not
    which one it is, so anyone wanting its bearing or confidence had to
    iterate the fires and re-find the maximum themselves. Ties go to the
    nearest of the tied fires, because the clusters arrive sorted by distance
    and max() keeps the first — the same fire the max_frp value comes from.
    """
    strongest = max(
        (c for c in coordinator.data.clusters if c.frp is not None),
        key=lambda c: c.frp,
        default=None,
    )
    if strongest is None:
        return {"strongest_entity_id": None}
    return {"strongest_entity_id": coordinator.entity_ids.get(strongest.id)}


def _satellite_observation_attributes(
    coordinator: FirmsCoordinator,
) -> dict[str, Any]:
    """Orbital facts for the next look and the previous look's identity."""
    observation = coordinator.data.next_observation
    previous = coordinator.data.previous_observation
    if observation is None:
        return {
            "satellite": None,
            "satellite_name": None,
            "norad_id": None,
            "window_start": None,
            "window_end": None,
            "closest_ground_track_miles": None,
            "closest_subpoint_latitude": None,
            "closest_subpoint_longitude": None,
            "swath_miles": None,
            "previous_observation": previous.closest.isoformat() if previous else None,
            "previous_satellite": previous.satellite if previous else None,
        }
    return {
        "satellite": observation.satellite,
        "satellite_name": observation.satellite_name,
        "norad_id": observation.norad_id,
        "window_start": observation.start.isoformat(),
        "window_end": observation.end.isoformat(),
        "closest_ground_track_miles": round(observation.closest_ground_track_km * KM_TO_MILES, 1),
        "closest_subpoint_latitude": observation.closest_subpoint_latitude,
        "closest_subpoint_longitude": observation.closest_subpoint_longitude,
        "swath_miles": round(observation.swath_km * KM_TO_MILES, 1),
        "previous_observation": previous.closest.isoformat() if previous else None,
        "previous_satellite": previous.satellite if previous else None,
    }


SENSORS: tuple[FirmsSensorDescription, ...] = (
    FirmsSensorDescription(
        key="hotspot_count",
        translation_key="hotspot_count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda d: len(d.clusters) if d.monitoring_active else None,
        attributes_fn=lambda c: {
            "monitoring_mode": c.data.monitoring_mode,
            "monitoring_active": c.data.monitoring_active,
            "raw_detections": c.data.raw_detections,
            "per_satellite": c.data.per_satellite,
            "satellite_errors": c.data.satellite_errors,
            "truncated": c.data.truncated,
            "ignored_detections": c.data.ignored_detections,
            # Next to the manual zones' count on purpose: this filter picks its
            # own targets, so the number it drops belongs where someone will
            # trip over it, not only in a diagnostics download.
            "auto_ignored_detections": c.data.auto_ignored_detections,
        },
    ),
    FirmsSensorDescription(
        key="alert_fire_count",
        name="FIRMS fires inside alert radius",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alarm-light-outline",
        value_fn=lambda d: None,  # coordinator-aware value supplied below
        attributes_fn=lambda c: {
            "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
            "monitoring_radius_miles": round(c.radius_km * KM_TO_MILES, 1),
        },
    ),
    FirmsSensorDescription(
        key="nearest_distance",
        translation_key="nearest_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.MILES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.nearest_km * KM_TO_MILES if d.nearest_km is not None else None,
        attributes_fn=_nearest_attributes,
        uses_weather=True,
    ),
    # The same reading as the `wind_speed` attribute above, as an entity.
    # A bare number in the states view has no unit, and on this integration the
    # `km` of the distance sensor sits directly under it — a user in the
    # community thread read 4.4 m/s as 4.4 km/h and filed it as a bug against
    # a card showing 16 km/h for the same wind. As an entity Home Assistant
    # prints the unit itself and converts it to whatever the instance or the
    # user prefers, so the ambiguity cannot recur. The attribute stays: every
    # template this project has published reads it, and it is the raw value
    # that any calculation wants.
    FirmsSensorDescription(
        key="nearest_wind_speed",
        translation_key="nearest_wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.nearest_wind.speed if d.nearest_wind else None,
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
        attributes_fn=_max_frp_attributes,
    ),
    FirmsSensorDescription(
        key="satellite_observation",
        translation_key="satellite_observation",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:satellite-variant",
        value_fn=lambda d: d.next_observation.closest if d.next_observation else None,
        attributes_fn=_satellite_observation_attributes,
    ),
)



MS_TO_MPH = 2.2369362920544

def _smoke_relationship(offset: float | None) -> str | None:
    """Simple geometric relationship of smoke path to the observer."""
    if offset is None:
        return None
    if offset <= 60:
        return "toward"
    if offset <= 120:
        return "crosswind"
    return "away"

def _wind_confidence(speed_mps: float | None) -> str | None:
    """Glanceable confidence based only on wind strength, not fire danger."""
    if speed_mps is None:
        return None
    mph = speed_mps * MS_TO_MPH
    if mph < 3:
        return "light"
    if mph < 8:
        return "medium"
    return "strong"

def _ngfs_fire_smoke(c, fire):
    """Return wind, smoke offset and relationship for one tracked NGFS fire."""
    wind = c.data.tracked_wind.get(fire.tracking_id)
    if wind is None:
        return None, None, None
    offset = smoke_offset(wind.bearing, fire.bearing)
    return wind, offset, _smoke_relationship(offset)

def _ngfs_smoke_values(c):
    if not c.data.tracked_fires:
        return None, None
    _, offset, relationship = _ngfs_fire_smoke(c, c.data.tracked_fires[0])
    return offset, relationship

def _ngfs_toward_fires(c):
    """Wind-monitored NGFS tracked fires whose smoke path points toward us."""
    result = []
    for fire in c.data.tracked_fires:
        wind, offset, relationship = _ngfs_fire_smoke(c, fire)
        if wind is not None and relationship == "toward":
            result.append((fire, wind, offset))
    return result

def _ngfs_nearest_smoke_threat_value(c):
    toward = _ngfs_toward_fires(c)
    return round(toward[0][0].distance_km * KM_TO_MILES, 1) if toward else None

def _ngfs_nearest_smoke_threat_attrs(c):
    toward = _ngfs_toward_fires(c)
    attrs = {
        "tracked_fires": len(c.data.tracked_fires),
        "wind_monitored_fires": len(c.data.tracked_wind),
        "toward_fires": len(toward),
        "wind_lookup_budget": c.firms.wind_fires,
    }
    if not toward:
        return attrs
    fire, wind, offset = toward[0]
    attrs.update({
        "name": fire.name,
        "tracking_id": fire.tracking_id,
        "direction": fire.direction,
        "bearing": round(fire.bearing),
        "latest": fire.latest.isoformat(),
        "max_frp": fire.max_frp,
        "detection_count": fire.detection_count,
        "satellite": fire.satellite,
        "wind_bearing": round(wind.bearing),
        "wind_direction": cardinal(wind.bearing),
        "wind_speed_mph": round(wind.speed * MS_TO_MPH, 1),
        "smoke_offset": round(offset),
        "smoke_relationship": "toward",
        "smoke_confidence": _wind_confidence(wind.speed),
        "inside_alert_radius": fire.distance_km <= c.alert_radius_km,
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
    })
    return attrs

def _ngfs_toward_attrs(c):
    toward = _ngfs_toward_fires(c)
    return {
        "tracked_fires": len(c.data.tracked_fires),
        "wind_monitored_fires": len(c.data.tracked_wind),
        "wind_lookup_budget": c.firms.wind_fires,
        "nearest_toward_name": toward[0][0].name if toward else None,
        "nearest_toward_distance_miles": round(toward[0][0].distance_km * KM_TO_MILES, 1) if toward else None,
        "nearest_toward_direction": toward[0][0].direction if toward else None,
        "fires": [
            {
                "name": fire.name,
                "tracking_id": fire.tracking_id,
                "distance_miles": round(fire.distance_km * KM_TO_MILES, 1),
                "direction": fire.direction,
                "smoke_offset": round(offset),
                "wind_speed_mph": round(wind.speed * MS_TO_MPH, 1),
            }
            for fire, wind, offset in toward
        ],
    }

def _combined_nearest(c):
    """Closest current fire representation across FIRMS and NGFS.

    This intentionally does not claim cross-feed deduplication yet. It is the
    closest observation from either feed and serves as stable groundwork for
    cards/alerts while event association is developed separately.
    """
    firms = c.firms.data.clusters[0] if c.firms.data.clusters else None
    ngfs = c.data.tracked_fires[0] if c.data.tracked_fires else None
    if firms is None:
        return ("NGFS", ngfs) if ngfs else (None, None)
    if ngfs is None:
        return "FIRMS", firms
    return ("FIRMS", firms) if firms.distance_km <= ngfs.distance_km else ("NGFS", ngfs)

def _combined_nearest_value(c):
    _, fire = _combined_nearest(c)
    return round(fire.distance_km * KM_TO_MILES, 1) if fire else None

def _combined_nearest_attrs(c):
    source, fire = _combined_nearest(c)
    firms = c.firms.data.clusters[0] if c.firms.data.clusters else None
    ngfs = c.data.tracked_fires[0] if c.data.tracked_fires else None
    attrs = {
        "source": source,
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
        "inside_alert_radius": bool(fire and fire.distance_km <= c.alert_radius_km),
        "firms_distance_miles": round(firms.distance_km * KM_TO_MILES, 1) if firms else None,
        "ngfs_distance_miles": round(ngfs.distance_km * KM_TO_MILES, 1) if ngfs else None,
    }
    if fire is None:
        return attrs

    attrs["direction"] = getattr(fire, "direction", None)
    attrs["bearing"] = round(fire.bearing) if getattr(fire, "bearing", None) is not None else None

    if source == "NGFS":
        wind = c.data.nearest_tracked_wind
        offset = smoke_offset(wind.bearing, fire.bearing) if wind and fire.bearing is not None else None
        attrs.update({
            "name": fire.name,
            "tracking_id": fire.tracking_id,
            "latest": fire.latest.isoformat(),
            "max_frp": fire.max_frp,
            "wind_bearing": round(wind.bearing) if wind else None,
            "wind_direction": cardinal(wind.bearing) if wind else None,
            "wind_speed_mph": round(wind.speed * MS_TO_MPH, 1) if wind else None,
            "smoke_offset": round(offset) if offset is not None else None,
            "smoke_relationship": _smoke_relationship(offset),
            "smoke_confidence": _wind_confidence(wind.speed if wind else None),
        })
    else:
        wind = c.firms.data.nearest_wind
        offset = smoke_offset(wind.bearing, fire.bearing) if wind and fire.bearing is not None else None
        attrs.update({
            "name": None,
            "tracking_id": None,
            "latest": fire.acq_datetime,
            "max_frp": fire.frp,
            "wind_bearing": round(wind.bearing) if wind else None,
            "wind_direction": cardinal(wind.bearing) if wind else None,
            "wind_speed_mph": round(wind.speed * MS_TO_MPH, 1) if wind else None,
            "smoke_offset": round(offset) if offset is not None else None,
            "smoke_relationship": _smoke_relationship(offset),
            "smoke_confidence": _wind_confidence(wind.speed if wind else None),
        })
    return attrs


def _nearby_wildfires_attrs(c):
    incidents = c.data.combined_incidents
    return {
        "matched_firms_ngfs": c.data.matched_incidents,
        "firms_only": sum(1 for i in incidents if i.source == "FIRMS"),
        "ngfs_only": sum(1 for i in incidents if i.source == "NGFS"),
        "both_sources": sum(1 for i in incidents if i.source == "FIRMS + NGFS"),
        "match_distance_miles": round(5.0 * KM_TO_MILES, 1),
        "match_time_hours": 24,
        "firms_incident_group_distance_miles": round(5.0 * KM_TO_MILES, 1),
        "fires": [
            {
                "name": i.name,
                "source": i.source,
                "distance_miles": round(i.distance_km * KM_TO_MILES, 1),
                "latest": i.latest.isoformat() if i.latest else None,
                "max_frp": i.max_frp,
                "firms_detections": i.firms_detections,
                "ngfs_detections": i.ngfs_detections,
                "tracking_id": i.ngfs_tracking_id,
                "tracking_ids": list(i.ngfs_tracking_ids),
                "ngfs_tracking_features": i.ngfs_tracking_features,
                "match_distance_miles": round(i.match_distance_km * KM_TO_MILES, 1) if i.match_distance_km is not None else None,
            }
            for i in incidents[:20]
        ],
        "fires_list_truncated": len(incidents) > 20,
    }

def _nearest_incident_attrs(c):
    if not c.data.combined_incidents:
        return {"source": None, "name": None}
    i = c.data.combined_incidents[0]
    bearing = None
    direction = None
    bearing = bearing_deg(c.latitude, c.longitude, i.latitude, i.longitude)
    direction = cardinal(bearing)
    return {
        "source": i.source, "name": i.name, "direction": direction,
        "bearing": round(bearing) if bearing is not None else None,
        "latest": i.latest.isoformat() if i.latest else None, "max_frp": i.max_frp,
        "firms_detections": i.firms_detections, "ngfs_detections": i.ngfs_detections,
        "tracking_id": i.ngfs_tracking_id, "tracking_ids": list(i.ngfs_tracking_ids),
        "ngfs_tracking_features": i.ngfs_tracking_features, "firms_cluster_id": i.firms_cluster_id,
        "match_distance_miles": round(i.match_distance_km * KM_TO_MILES, 1) if i.match_distance_km is not None else None,
        "inside_alert_radius": i.distance_km <= c.alert_radius_km,
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
    }


def _named_incidents(c):
    return [i for i in c.data.combined_incidents if i.name]

def _named_wildfires_attrs(c):
    incidents = _named_incidents(c)
    return {
        "named_wildfires": len(incidents),
        "fires": [
            {
                "name": i.name,
                "source": i.source,
                "distance_miles": round(i.distance_km * KM_TO_MILES, 1),
                "latest": i.latest.isoformat() if i.latest else None,
                "max_frp": i.max_frp,
                "firms_detections": i.firms_detections,
                "ngfs_detections": i.ngfs_detections,
                "ngfs_tracking_features": i.ngfs_tracking_features,
                "tracking_ids": list(i.ngfs_tracking_ids),
            }
            for i in incidents[:10]
        ],
        "fires_list_truncated": len(incidents) > 10,
    }

def _nearest_named_incident_attrs(c):
    incidents = _named_incidents(c)
    if not incidents:
        return {"name": None, "source": None}
    i = incidents[0]
    bearing = bearing_deg(c.latitude, c.longitude, i.latitude, i.longitude)
    return {
        "name": i.name, "source": i.source,
        "direction": cardinal(bearing),
        "bearing": round(bearing) if bearing is not None else None,
        "latest": i.latest.isoformat() if i.latest else None,
        "max_frp": i.max_frp,
        "firms_detections": i.firms_detections,
        "ngfs_detections": i.ngfs_detections,
        "tracking_id": i.ngfs_tracking_id,
        "tracking_ids": list(i.ngfs_tracking_ids),
        "ngfs_tracking_features": i.ngfs_tracking_features,
        "inside_alert_radius": i.distance_km <= c.alert_radius_km,
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
    }

def _ngfs_tracked_attrs(c):
    fires = c.data.tracked_fires
    return {
        "named_fires": sum(1 for f in fires if f.name),
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
        "fires_inside_alert_radius": sum(1 for f in fires if f.distance_km <= c.alert_radius_km),
        "nearest_fire_name": fires[0].name if fires else None,
        "nearest_tracking_id": fires[0].tracking_id if fires else None,
    }

def _ngfs_nearest_tracked_attrs(c):
    if not c.data.tracked_fires:
        return {"name": None, "tracking_id": None, "latest": None, "max_frp": None, "detection_count": 0}
    f = c.data.tracked_fires[0]
    wind = c.data.tracked_wind.get(f.tracking_id)
    offset = smoke_offset(wind.bearing, f.bearing) if wind else None
    return {
        "name": f.name, "tracking_id": f.tracking_id, "latest": f.latest.isoformat(),
        "max_frp": f.max_frp, "detection_count": f.detection_count,
        "satellite": f.satellite, "latitude": f.latitude, "longitude": f.longitude,
        "bearing": round(f.bearing), "direction": f.direction,
        "wind_bearing": round(wind.bearing) if wind else None,
        "wind_direction": cardinal(wind.bearing) if wind else None,
        "wind_speed_mph": round(wind.speed * MS_TO_MPH, 1) if wind else None,
        "smoke_offset": round(offset) if offset is not None else None,
        "smoke_relationship": _smoke_relationship(offset),
        "smoke_confidence": _wind_confidence(wind.speed if wind else None),
        "inside_alert_radius": f.distance_km <= c.alert_radius_km,
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
    }


def _new_ngfs_fire_value(c):
    """Distance to the nearest NGFS fire newly entering the alert radius."""
    if not c.data.new_alert_fires:
        return None
    return round(c.data.new_alert_fires[0].distance_km * KM_TO_MILES, 1)

def _new_ngfs_fire_attrs(c):
    fires = c.data.new_alert_fires
    if not fires:
        return {
            "new_fire": False,
            "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
        }
    f = fires[0]
    return {
        "new_fire": True,
        "new_fires_this_update": len(fires),
        "name": f.name,
        "tracking_id": f.tracking_id,
        "direction": f.direction,
        "bearing": round(f.bearing),
        "latest": f.latest.isoformat(),
        "max_frp": f.max_frp,
        "detection_count": f.detection_count,
        "satellite": f.satellite,
        "alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1),
    }

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
    ngfs = getattr(coordinator, "ngfs", None)
    if ngfs is not None:
        async_add_entities([
            NgfsSensor(ngfs, entry, "detections", "NGFS detections", "mdi:fire-alert", lambda c: len(c.data.detections) if c.data.monitoring_active else None, lambda c: {"latest_detection": c.data.latest.isoformat() if c.data.latest else None, "max_frp": c.data.max_frp, "records_received": c.data.records_received, "records_with_valid_coordinates": c.data.records_with_valid_coordinates, "records_in_radius": c.data.records_in_radius, "monitoring_radius_miles": round(c.radius_km * KM_TO_MILES, 1), "nearest_raw_distance_miles": round(c.data.nearest_raw_distance_km * KM_TO_MILES, 1) if c.data.nearest_raw_distance_km is not None else None, "nearest_raw_latitude": c.data.nearest_raw_latitude, "nearest_raw_longitude": c.data.nearest_raw_longitude, "collection": c.data.collection, "query_lookback_minutes": c.data.query_lookback_minutes, "last_successful_update": c.data.last_successful_update.isoformat() if c.data.last_successful_update else None, "error": c.data.error}),
            NgfsSensor(ngfs, entry, "nearest", "Nearest NGFS detection", "mdi:map-marker-alert", lambda c: round(c.distance_km(c.data.nearest) * KM_TO_MILES, 1) if c.distance_km(c.data.nearest) is not None else None, _ngfs_nearest_attrs, "mi"),
            NgfsSensor(ngfs, entry, "latest", "Latest NGFS detection", "mdi:clock-alert-outline", lambda c: c.data.latest),
            NgfsSensor(ngfs, entry, "max_frp", "NGFS max fire radiative power", "mdi:heat-wave", lambda c: c.data.max_frp, unit="MW"),
            NgfsSensor(ngfs, entry, "tracked_fires", "NGFS tracked fires", "mdi:fire-circle", lambda c: len(c.data.tracked_fires), _ngfs_tracked_attrs),
            NgfsSensor(ngfs, entry, "nearest_tracked_fire", "Nearest NGFS tracked fire", "mdi:map-marker-radius", lambda c: round(c.data.tracked_fires[0].distance_km * KM_TO_MILES, 1) if c.data.tracked_fires else None, _ngfs_nearest_tracked_attrs, "mi"),
            NgfsSensor(ngfs, entry, "nearest_smoke_relationship", "Nearest NGFS smoke relationship", "mdi:weather-windy", lambda c: _ngfs_smoke_values(c)[1], lambda c: {
                "smoke_offset": round(_ngfs_smoke_values(c)[0]) if _ngfs_smoke_values(c)[0] is not None else None,
                "confidence": _wind_confidence(c.data.nearest_tracked_wind.speed if c.data.nearest_tracked_wind else None),
                "fire_name": c.data.tracked_fires[0].name if c.data.tracked_fires else None,
                "fire_direction": c.data.tracked_fires[0].direction if c.data.tracked_fires else None,
                "wind_speed_mph": round(c.data.nearest_tracked_wind.speed * MS_TO_MPH, 1) if c.data.nearest_tracked_wind else None,
            }),
            NgfsSensor(ngfs, entry, "combined_nearest_fire", "Nearest combined fire", "mdi:fire-alert", _combined_nearest_value, _combined_nearest_attrs, "mi"),
            NgfsSensor(ngfs, entry, "nearby_wildfires", "Nearby wildfires", "mdi:fire-circle", lambda c: len(c.data.combined_incidents), _nearby_wildfires_attrs),
            NgfsSensor(ngfs, entry, "nearest_combined_incident", "Nearest combined incident", "mdi:map-marker-alert", lambda c: round(c.data.combined_incidents[0].distance_km * KM_TO_MILES, 1) if c.data.combined_incidents else None, _nearest_incident_attrs, "mi"),
            NgfsSensor(ngfs, entry, "named_wildfires", "Named wildfires", "mdi:fire", lambda c: len(_named_incidents(c)), _named_wildfires_attrs),
            NgfsSensor(ngfs, entry, "nearest_named_wildfire", "Nearest named wildfire", "mdi:map-marker-fire", lambda c: round(_named_incidents(c)[0].distance_km * KM_TO_MILES, 1) if _named_incidents(c) else None, _nearest_named_incident_attrs, "mi"),
            NgfsSensor(ngfs, entry, "tracked_fires_toward", "NGFS tracked fires toward us", "mdi:weather-windy", lambda c: len(_ngfs_toward_fires(c)), _ngfs_toward_attrs),
            NgfsSensor(ngfs, entry, "nearest_smoke_threat", "Nearest NGFS smoke threat", "mdi:weather-windy-alert", _ngfs_nearest_smoke_threat_value, _ngfs_nearest_smoke_threat_attrs, "mi"),
            NgfsSensor(ngfs, entry, "alert_fires", "NGFS fires inside alert radius", "mdi:alarm-light-outline", lambda c: sum(1 for f in c.data.tracked_fires if f.distance_km <= c.alert_radius_km), lambda c: {"alert_radius_miles": round(c.alert_radius_km * KM_TO_MILES, 1), "monitoring_radius_miles": round(c.radius_km * KM_TO_MILES, 1)}),
            NgfsSensor(ngfs, entry, "new_alert_fire", "New NGFS fire", "mdi:fire-alert", _new_ngfs_fire_value, _new_ngfs_fire_attrs, "mi"),
        ])


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
        if self.entity_description.key == "alert_fire_count":
            if not self.coordinator.data.monitoring_active:
                return None
            return sum(1 for fire in self.coordinator.data.clusters if fire.distance_km <= self.coordinator.alert_radius_km)
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return diagnostic attributes where defined."""
        if self.entity_description.attributes_fn:
            return self.entity_description.attributes_fn(self.coordinator)
        return None


class NgfsSensor(CoordinatorEntity[NgfsCoordinator], SensorEntity):
    """One aggregate NOAA NGFS value."""
    _attr_has_entity_name = True
    _attr_attribution = "Data courtesy of NOAA NESDIS Next Generation Fire System (experimental)"
    def __init__(self, coordinator, entry, key, name, icon, value_fn, attrs_fn=None, unit=None):
        super().__init__(coordinator); self._attr_unique_id=f"{entry.entry_id}_ngfs_{key}"; self._attr_name=name; self._attr_icon=icon
        self._value_fn=value_fn; self._attrs_fn=attrs_fn; self._attr_native_unit_of_measurement=unit
        self._attr_device_info=DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer="NOAA / NASA", model="Wildfire satellite monitoring", entry_type=DeviceEntryType.SERVICE)
    @property
    def attribution(self) -> str:
        if self._attr_unique_id.endswith("_ngfs_combined_nearest_fire"):
            source, _ = _combined_nearest(self.coordinator)
            if source == "FIRMS":
                return ATTRIBUTION
            if source == "NGFS":
                return "Data courtesy of NOAA NESDIS Next Generation Fire System (experimental)"
            return f"{ATTRIBUTION}; NOAA NESDIS Next Generation Fire System (experimental)"
        return "Data courtesy of NOAA NESDIS Next Generation Fire System (experimental)"
    @property
    def native_value(self): return self._value_fn(self.coordinator)
    @property
    def extra_state_attributes(self): return self._attrs_fn(self.coordinator) if self._attrs_fn else {}

def _ngfs_nearest_attrs(c):
    d=c.data.nearest
    if d is None: return {"satellite":None,"confidence":None,"frp":None,"acquired":None,"known_incident_name":None,"feature_tracking_id":None}
    return {"satellite":d.satellite,"confidence":d.confidence,"frp":d.frp,"acquired":d.acquired.isoformat(),"known_incident_name":d.known_incident_name,"feature_tracking_id":d.feature_tracking_id,"latitude":d.latitude,"longitude":d.longitude,"error":c.data.error}
