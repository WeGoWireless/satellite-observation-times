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
    MetNoClient,
    WeatherError,
    WindObservation,
    bbox_around,
    cluster_hotspots,
    haversine_km,
    in_ignored_zone,
)
from .const import (
    CLUSTER_RADIUS_KM,
    CONF_IGNORE_ZONES,
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
    # At least one satellite came back at the FETCH_COUNT ceiling, so the feed
    # was cut off and fires are missing. A log warning is not enough for this:
    # every number the integration shows is then too low, and nothing about a
    # too-low fire count looks wrong.
    truncated: bool = False
    # Detections dropped by the user's ignore zones. Surfaced so a zone can be
    # seen working — a silent filter on fire data would be worse than none.
    ignored_detections: int = 0
    # Wind at the nearest fire's own coordinates; None whenever the lookup was
    # skipped or failed, which is not an error worth surfacing.
    nearest_wind: WindObservation | None = None

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
        weather: MetNoClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.weather = weather
        # Latched so a weather outage is reported once, not every 15 minutes.
        self._weather_failing = False
        cfg = {**entry.data, **entry.options}
        self.latitude: float = cfg[CONF_LATITUDE]
        self.longitude: float = cfg[CONF_LONGITUDE]
        self.radius_km: float = cfg.get(CONF_RADIUS, DEFAULT_RADIUS_M) / 1000
        self.satellites: list[str] = cfg.get(CONF_SATELLITES, DEFAULT_SATELLITES)
        self.window: str = cfg.get(CONF_WINDOW, WINDOW_24H)
        self.min_confidence: str = cfg.get(CONF_MIN_CONFIDENCE, DEFAULT_MIN_CONFIDENCE)
        self.min_frp: float = cfg.get(CONF_MIN_FRP, DEFAULT_MIN_FRP)
        self._bbox = bbox_around(self.latitude, self.longitude, self.radius_km)
        # Identifies which entry a fire belongs to. Every entry publishes its
        # fires under the same `nasa_firms` geo_location source, so a map card
        # fed by `geo_location_sources` mixes them — and since each fire's state
        # is its distance from *its own* entry's origin, a foreign fire shows a
        # believable but wrong number. Same form as the entry title.
        self.origin = f"{self.latitude:.2f}/{self.longitude:.2f}"
        # cluster id -> entity_id, filled in by the geo_location entities once
        # Home Assistant has assigned them. Lets the aggregate sensors point at
        # the actual fire entity instead of guessing its slug.
        self.entity_ids: dict[str, str] = {}
        # Last cycle's clusters, so a fire keeps its id — and with it its
        # entity and its history — while its centroid drifts. Memory only:
        # after a restart the entities are rebuilt anyway, and every fire that
        # has not drifted since gets the same id from its coordinates.
        self._previous_clusters: list[FirmsCluster] = []

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
                data.truncated = True
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
        # ignore zones, minimum confidence, minimum fire radiative power.
        # Read per cycle rather than cached in __init__: an options edit does
        # reload the entry (see __init__.py), but reading them here means this
        # holds regardless of how the zones got there.
        zones = self.config_entry.options.get(CONF_IGNORE_ZONES) or []
        within: list = []
        ignored = 0
        for h in hotspots:
            dist = haversine_km(self.latitude, self.longitude, h.latitude, h.longitude)
            if dist > self.radius_km:
                continue
            if in_ignored_zone(h.latitude, h.longitude, zones):
                ignored += 1
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
        data.ignored_detections = ignored
        data.clusters = cluster_hotspots(
            within,
            CLUSTER_RADIUS_KM,
            (self.latitude, self.longitude),
            self._previous_clusters,
        )
        data.clusters_by_id = {c.id: c for c in data.clusters}
        # Only reached when the fetch succeeded — a failed cycle raises above
        # and leaves the previous set intact, so a single outage does not
        # renumber every fire.
        self._previous_clusters = data.clusters
        if data.clusters:
            data.nearest_wind = await self._async_wind(data.clusters[0])
        return data

    async def _async_wind(self, cluster: FirmsCluster) -> WindObservation | None:
        """Wind at the closest fire only — a busy box holds hundreds of them.

        Never raises: the fire data is the product, so a weather outage costs
        two attributes and nothing else.
        """
        try:
            wind = await self.weather.wind_at(cluster.latitude, cluster.longitude)
        except WeatherError as err:
            if not self._weather_failing:
                self._weather_failing = True
                _LOGGER.warning(
                    "Wind lookup failed, continuing without wind attributes: %s", err
                )
            else:
                _LOGGER.debug("Wind lookup still failing: %s", err)
            return None
        self._weather_failing = False
        return wind
