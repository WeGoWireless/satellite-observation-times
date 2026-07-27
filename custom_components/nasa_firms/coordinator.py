"""Update coordinator: fetch all satellites, filter, deduplicate."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CONFIDENCE_RANK,
    WINDOW_24H,
    FirmsAuthError,
    FirmsClient,
    FirmsCluster,
    bbox_around,
    cluster_hotspots,
    haversine_km,
)
from .const import (
    CLUSTER_RADIUS_KM,
    CONF_MIN_CONFIDENCE,
    CONF_MIN_FRP,
    CONF_SATELLITES,
    CONF_WINDOW,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_FRP,
    DEFAULT_RADIUS_M,
    DEFAULT_SATELLITES,
    DOMAIN,
    FETCH_COUNT,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type NasaFirmsConfigEntry = ConfigEntry[FirmsCoordinator]


@dataclass
class FirmsData:
    """Result of one update cycle."""

    clusters: list[FirmsCluster] = field(default_factory=list)
    clusters_by_id: dict[str, FirmsCluster] = field(default_factory=dict)
    raw_detections: int = 0
    per_satellite: dict[str, int] = field(default_factory=dict)
    satellite_errors: dict[str, str] = field(default_factory=dict)

    @property
    def nearest_km(self) -> float | None:
        """Distance to the closest fire, or None when there is none."""
        return self.clusters[0].distance_km if self.clusters else None

    @property
    def max_frp(self) -> float | None:
        """Strongest fire radiative power across all clusters."""
        frps = [c.frp for c in self.clusters if c.frp is not None]
        return max(frps) if frps else None


class FirmsCoordinator(DataUpdateCoordinator[FirmsData]):
    """Poll FIRMS for all configured satellites and merge the result."""

    config_entry: NasaFirmsConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NasaFirmsConfigEntry,
        client: FirmsClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        cfg = {**entry.data, **entry.options}
        self.latitude: float = cfg[CONF_LATITUDE]
        self.longitude: float = cfg[CONF_LONGITUDE]
        self.radius_km: float = cfg.get(CONF_RADIUS, DEFAULT_RADIUS_M) / 1000
        self.satellites: list[str] = cfg.get(CONF_SATELLITES, DEFAULT_SATELLITES)
        self.window: str = cfg.get(CONF_WINDOW, WINDOW_24H)
        self.min_confidence: str = cfg.get(CONF_MIN_CONFIDENCE, DEFAULT_MIN_CONFIDENCE)
        self.min_frp: float = cfg.get(CONF_MIN_FRP, DEFAULT_MIN_FRP)
        self._bbox = bbox_around(self.latitude, self.longitude, self.radius_km)
        # cluster id -> entity_id, filled in by the geo_location entities once
        # Home Assistant has assigned them. Lets the aggregate sensors point at
        # the actual fire entity instead of guessing its slug.
        self.entity_ids: dict[str, str] = {}

    async def _async_update_data(self) -> FirmsData:
        results = await asyncio.gather(
            *(
                self.client.fetch(sat, self.window, self._bbox, FETCH_COUNT)
                for sat in self.satellites
            ),
            return_exceptions=True,
        )
        data = FirmsData()
        hotspots = []
        for sat, result in zip(self.satellites, results):
            if isinstance(result, FirmsAuthError):
                raise ConfigEntryAuthFailed from result
            if isinstance(result, BaseException):
                data.satellite_errors[sat] = str(result)
                _LOGGER.warning("FIRMS fetch failed for %s: %s", sat, result)
                continue
            if len(result) >= FETCH_COUNT:
                _LOGGER.warning(
                    "FIRMS returned the maximum of %s features for %s — "
                    "results may be truncated",
                    FETCH_COUNT,
                    sat,
                )
            data.per_satellite[sat] = len(result)
            hotspots.extend(result)
        if not data.per_satellite and data.satellite_errors:
            raise UpdateFailed(f"All FIRMS fetches failed: {data.satellite_errors}")

        # Client-side filtering: exact radius (the bbox is a superset),
        # minimum confidence, minimum fire radiative power.
        within: list = []
        for h in hotspots:
            dist = haversine_km(self.latitude, self.longitude, h.latitude, h.longitude)
            if dist > self.radius_km:
                continue
            if (
                self.min_confidence != "any"
                and CONFIDENCE_RANK.get(h.confidence or "nominal", 1)
                < CONFIDENCE_RANK[self.min_confidence]
            ):
                continue
            if self.min_frp and (h.frp or 0.0) < self.min_frp:
                continue
            within.append((h, dist))

        data.raw_detections = len(within)
        data.clusters = cluster_hotspots(
            within, CLUSTER_RADIUS_KM, (self.latitude, self.longitude)
        )
        data.clusters_by_id = {c.id: c for c in data.clusters}
        return data
