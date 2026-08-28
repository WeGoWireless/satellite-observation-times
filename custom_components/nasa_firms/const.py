"""Constants for the NASA FIRMS integration."""
from datetime import timedelta

DOMAIN = "nasa_firms"

CONF_MAP_KEY = "map_key"
CONF_REGION = "region"
CONF_SATELLITES = "satellites"
CONF_WINDOW = "window"
CONF_MIN_CONFIDENCE = "min_confidence"
CONF_MIN_FRP = "min_frp"
CONF_IGNORE_ZONES = "ignore_zones"
CONF_WIND_FIRES = "wind_fires"
CONF_AUTO_IGNORE = "auto_ignore"
CONF_MONITORING_MODE = "monitoring_mode"
CONF_FIRE_SEASON_START_MONTH = "fire_season_start_month"
CONF_FIRE_SEASON_START_DAY = "fire_season_start_day"
CONF_FIRE_SEASON_END_MONTH = "fire_season_end_month"
CONF_FIRE_SEASON_END_DAY = "fire_season_end_day"
CONF_FIRMS_FULL_INTERVAL_MIN = "firms_full_interval_min"
CONF_NGFS_FULL_INTERVAL_MIN = "ngfs_full_interval_min"
CONF_FIRMS_REDUCED_INTERVAL_MIN = "firms_reduced_interval_min"
CONF_NGFS_REDUCED_INTERVAL_MIN = "ngfs_reduced_interval_min"
CONF_ALERT_RADIUS = "alert_radius"

# A zone is only ever meant to cover a known heat source and its immediate
# surroundings — a plant, a flare stack, a landfill. Wide enough and it starts
# hiding real fires next door, which is the one thing this feature must not do.
DEFAULT_ZONE_RADIUS_M = 1_000
MAX_ZONE_RADIUS_M = 20_000

DEFAULT_SATELLITES = ["noaa20", "noaa21", "snpp"]
DEFAULT_RADIUS_M = 100_000
DEFAULT_ALERT_RADIUS_M = 96_560  # 60 miles
# The location selector happily lets a user drag the circle across a continent,
# and past a certain size FETCH_COUNT silently clips the result. 500 km is five
# times the default and still answers "my area and well beyond it"; past that
# the question has stopped being "what is near me". Enforced on new entries
# only — an existing entry configured wider keeps working and reports the
# truncation instead.
MAX_RADIUS_M = 500_000
DEFAULT_MIN_CONFIDENCE = "any"
DEFAULT_MIN_FRP = 0.0

# Off by default, deliberately. The detection itself is safe — calibrated
# against 39,397 real detections across seven regions without suppressing a
# single one at or above 50 MW — but it needs 60 days of history before it
# does anything at all. A filter that stays dormant for two months and then
# starts hiding fire data on its own is the wrong thing to hand someone who
# never asked for it, and it matches the ignore zones, which also start empty.
DEFAULT_AUTO_IGNORE = False

# How long the per-cell history is kept in the store, and how the file is
# named. One store per entry: two entries watch different areas, and a shared
# file would make removing one of them clear the other's history.
SOURCES_STORAGE_VERSION = 1
SOURCES_STORAGE_KEY = f"{DOMAIN}.sources"

# How many of the nearest fires get a wind reading each cycle. Configurable
# because it changes the number of met.no requests, exactly like the satellite
# choice changes FIRMS calls — the project's own bar for what earns an option.
# The cap is budget arithmetic, not a technical limit: at 5 fires a cycle,
# a thousand installations stay comfortably inside met.no's stated request
# threshold under this integration's shared User-Agent. Fires ranked beyond
# the limit simply carry no reading.
DEFAULT_WIND_FIRES = 3
MAX_WIND_FIRES = 5

# Wildfire monitoring cadence. The full-rate FIRMS interval follows NASA's
# roughly 15-minute NRT refresh. Off-season mode keeps a low-rate safety net
# instead of going completely dark. NGFS uses its own cadence when that
# provider is enabled (5 minutes full-rate, 1 hour reduced-rate).
MONITORING_AUTO = "automatic"
MONITORING_FULL = "full"
MONITORING_REDUCED = "reduced"
MONITORING_DISABLED = "disabled"
DEFAULT_MONITORING_MODE = MONITORING_AUTO
DEFAULT_FIRE_SEASON_START_MONTH = 5
DEFAULT_FIRE_SEASON_START_DAY = 1
DEFAULT_FIRE_SEASON_END_MONTH = 10
DEFAULT_FIRE_SEASON_END_DAY = 31

DEFAULT_FIRMS_FULL_INTERVAL_MIN = 15
DEFAULT_NGFS_FULL_INTERVAL_MIN = 5
DEFAULT_FIRMS_REDUCED_INTERVAL_MIN = 120
DEFAULT_NGFS_REDUCED_INTERVAL_MIN = 60

UPDATE_INTERVAL = timedelta(minutes=DEFAULT_FIRMS_FULL_INTERVAL_MIN)
REDUCED_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_FIRMS_REDUCED_INTERVAL_MIN)
NGFS_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_NGFS_FULL_INTERVAL_MIN)
NGFS_REDUCED_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_NGFS_REDUCED_INTERVAL_MIN)
NGFS_LOOKBACK = timedelta(hours=2)
NGFS_FETCH_COUNT = 1000
NGFS_COLLECTION_WEST = "ngfs_schema.ngfs_detections_scene_west_conus"
NGFS_COLLECTION_EAST = "ngfs_schema.ngfs_detections_scene_east_conus"
NGFS_API_ROOT = "https://fire.data.nesdis.noaa.gov/api/ogc/detections"

# VIIRS pixel is 375 m; 1 km absorbs cross-satellite geolocation jitter.
CLUSTER_RADIUS_KM = 1.0
FETCH_COUNT = 1000

GEO_SOURCE = "nasa_firms"
ATTRIBUTION = "Data courtesy of NASA FIRMS"
# met.no publishes under CC BY 4.0, which requires the credit and the licence
# link. Only shown while wind data is actually present.
ATTRIBUTION_WEATHER = (
    "Wind data from MET Norway (CC BY 4.0, creativecommons.org/licenses/by/4.0/)"
)
# GeoNames ships under the same licence and the same rule applies: credit it
# only while a place name is actually on the entity.
ATTRIBUTION_PLACES = (
    "Place names from GeoNames (CC BY 4.0, creativecommons.org/licenses/by/4.0/)"
)

# Where the shared place index lives in hass.data. One per Home Assistant, not
# per entry: it is ~6 MB of place names (measured, 170,607 places) and two
# entries want the same table.
DATA_PLACES = "places"

# met.no hard-blocks generic agents: their ToS wants the application and a
# contact address. The version comes from the manifest so there is only ever
# one place to bump.
USER_AGENT = "ha-nasa-firms/{version} github.com/bangboomben/ha-nasa-firms"

MAP_KEY_URL = "https://firms.modaps.eosdis.nasa.gov/api/map_key/"

# Home Assistant event emitted when a new NGFS tracked fire first enters the alert radius.
EVENT_NEW_NGFS_FIRE = "wildfire_monitor_new_ngfs_fire"
