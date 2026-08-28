# Wildfire Monitor wm14

## NGFS early warning

wm14 adds a Home Assistant event and sensor for newly observed NOAA NGFS tracked fires entering the configured alert radius.

- Event: `wildfire_monitor_new_ngfs_fire`
- Sensor: **New NGFS fire** (distance in miles while a new fire is present in that update)
- Event data includes tracking ID, incident name when available, distance, direction, bearing, latest detection time, FRP, detection count, satellite, and configured alert radius.
- The first successful NGFS refresh after Home Assistant starts establishes a baseline and does **not** generate new-fire events.
- Tracking IDs already seen inside the alert radius remain remembered for the current Home Assistant runtime, avoiding duplicate alerts after temporary feed gaps.
- FIRMS polling and existing 25/10/5-mile alert behavior are unchanged.
