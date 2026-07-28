"""Constants for the NASA FIRMS integration."""
from datetime import timedelta

DOMAIN = "nasa_firms"

CONF_MAP_KEY = "map_key"
CONF_REGION = "region"
CONF_SATELLITES = "satellites"
CONF_WINDOW = "window"
CONF_MIN_CONFIDENCE = "min_confidence"
CONF_MIN_FRP = "min_frp"

DEFAULT_REGION = "Europe"
DEFAULT_SATELLITES = ["noaa20", "noaa21", "snpp"]
DEFAULT_RADIUS_M = 100_000
# The location selector happily lets a user drag the circle across a continent,
# and past a certain size FETCH_COUNT silently clips the result. 500 km is five
# times the default and still answers "my area and well beyond it"; past that
# the question has stopped being "what is near me". Enforced on new entries
# only — an existing entry configured wider keeps working and reports the
# truncation instead.
MAX_RADIUS_M = 500_000
DEFAULT_MIN_CONFIDENCE = "any"
DEFAULT_MIN_FRP = 0.0

# NASA refreshes FIRMS NRT data roughly every 15 minutes — polling faster
# only burns request quota without new data.
UPDATE_INTERVAL = timedelta(minutes=15)

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

# met.no hard-blocks generic agents: their ToS wants the application and a
# contact address. The version comes from the manifest so there is only ever
# one place to bump.
USER_AGENT = "ha-nasa-firms/{version} github.com/bangboomben/ha-nasa-firms"

MAP_KEY_URL = "https://firms.modaps.eosdis.nasa.gov/api/map_key/"
