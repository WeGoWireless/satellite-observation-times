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
