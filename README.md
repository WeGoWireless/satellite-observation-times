# NASA FIRMS Wildfire Monitor for Home Assistant

[![Support this project on Ko-fi](https://img.shields.io/badge/Ko--fi-support_this_project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/mrbenedict)

Near-real-time satellite wildfire detection from [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/)
(VIIRS + MODIS) as native Home Assistant entities: fires on the map card,
aggregate sensors, and everything you need for proximity alerts.

This grew out of a [zero-custom-code setup using `geo_json_events`](https://community.home-assistant.io/t/wildfire-monitoring-with-nasa-firms-live-fire-map-proximity-alerts-zero-custom-components/1016485)
and fixes what that approach structurally can't:

| | `geo_json_events` | this integration |
|---|---|---|
| FIRMS attributes (confidence, FRP, brightness, time, satellite) | dropped | preserved per fire |
| Multiple satellites | duplicate markers | deduplicated into one fire per ~1 km cluster |
| Filtering (min confidence / min FRP) | impossible | config option |
| Area definition | hand-computed BBOX (`cos(radians(lat))` footgun) | pick location + radius on a map |
| MAP_KEY | visible in the entry title | stored in config data, never displayed |
| Polling | every 5 min | every 15 min, matching NASA's refresh cadence |
| Count / nearest-distance sensors | template DIY | built in, plus max FRP |

![Deduplicated FIRMS fire detections on the standard Home Assistant map card](assets/map-live-fires.png)

*Live screenshot (dark theme, standard map card): deduplicated VIIRS detections
during the July 2026 fires in southern France — each marker is one logical fire,
merged from up to three satellites.*

## Installation

**HACS** (recommended): HACS → Integrations → ⋮ → *Custom repositories* →
add `https://github.com/bangboomben/ha-nasa-firms` as *Integration* → install → restart.

**Manual**: copy `custom_components/nasa_firms` into your `config/custom_components/` and restart.

## Setup

1. Get a free MAP_KEY at <https://firms.modaps.eosdis.nasa.gov/api/map_key/>
   (rate limit 5 000 requests / 10 min — this integration uses a handful per 15 minutes).
2. Settings → Devices & Services → Add Integration → **NASA FIRMS Wildfire Monitor**.
3. Enter the key, pick your FIRMS region, drag the location pin onto the spot
   you want to watch, set the radius, choose satellites and filters.

Satellites, detection window (24 h / 7 days), minimum confidence and minimum
fire radiative power can be changed later via the entry's *Configure* dialog.

## Entities

Per config entry:

| Entity | Meaning |
|---|---|
| `sensor.<name>_hotspots` | Number of deduplicated fires in the radius (attributes: raw detections, per-satellite counts, fetch errors) |
| `sensor.<name>_nearest_hotspot` | Distance to the closest fire in km (`unknown` when there is none). Attributes: `nearest_entity_id`, `bearing`, `direction` |
| `sensor.<name>_max_fire_radiative_power` | Strongest fire in MW |
| `geo_location.*` (source `nasa_firms`) | One entity per fire, with `frp_mw`, `confidence`, `satellites`, `detections`, `brightness_k`, `acquired`, `daynight` |

### Pointing at the nearest fire

The nearest-hotspot sensor carries the id of the fire entity it is reporting, so
you can read any of that fire's attributes without searching for it yourself:

```jinja
{% set e = state_attr('sensor.firms_40_54_23_01_nearest_hotspot', 'nearest_entity_id') %}
{{ state_attr(e, 'frp_mw') }} MW, {{ state_attr(e, 'confidence') }} confidence,
seen by {{ state_attr(e, 'satellites') | join(' + ') }}
```

`bearing` (degrees) and `direction` (16-point compass) are on the same sensor —
great-circle values, so they stay correct at high latitudes:

```jinja
Fire {{ states('sensor.firms_40_54_23_01_nearest_hotspot') }} km
{{ state_attr('sensor.firms_40_54_23_01_nearest_hotspot', 'direction') }}
```

## Map card

```yaml
type: map
geo_location_sources:
  - nasa_firms
entities:
  - zone.home
default_zoom: 8
theme_mode: auto
```

## Proximity alert example

```yaml
alias: "Wildfire proximity warning"
triggers:
  - trigger: numeric_state
    entity_id: sensor.firms_40_54_23_01_nearest_hotspot
    below: 15
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "🔥 Wildfire warning"
      message: >-
        Fire {{ trigger.to_state.state }} km away
        (NASA FIRMS satellite detection).
mode: single
```

## Honest limitations

- **Not a real-time alarm.** VIIRS satellites pass ~2× per day each (three
  satellites shrink the gap to a few hours), plus up to ~3 h processing
  latency. This reliably answers *"where is it burning and how far from me"* —
  a freshly ignited fire can be invisible for hours. Pair it with your
  country's official warning channel (in Europe: the `meteoalarm` integration).
- FIRMS detects **thermal anomalies**, not wildfires. Factories, flares and
  landfills show up too — that's what the confidence/FRP filters are for.
  Automatic suppression of persistent heat sources is on the roadmap.
- A hotspot is the center of a 375 m satellite pixel; expect a few hundred
  meters of positional tolerance.

## Roadmap

- Auto-ignore persistent heat sources (same spot detected across many days)
- Protocol layer (`api.py`, intentionally free of HA imports) extracted to a
  PyPI package, then a Home Assistant Core submission alongside the existing
  geo-feed family (`nsw_rural_fire_service_feed`, `qld_bushfire_feed`, …)

## Support

This integration is free and always will be. If it earns a place on your
dashboard, you can [buy me a coffee](https://ko-fi.com/mrbenedict) ☕ — much
appreciated, never required.

**If you want to help those affected by wildfires:** the best place for your
money is not my coffee fund — it's the people fighting and recovering from
these fires. Consider the [IFRC](https://www.ifrc.org/) or your country's
Red Cross / civil protection. This project stays free either way.

## Credits & disclaimer

This integration was developed with the supporting help of AI tooling
(Claude Code). All changes are reviewed, tested against a live Home Assistant
instance, and maintained by a human.

Fire data courtesy of NASA FIRMS. This project is not affiliated with or
endorsed by NASA. We acknowledge the use of data and imagery from NASA's Fire
Information for Resource Management System (FIRMS), part of NASA's Earth
Science Data and Information System (ESDIS).

License: [MIT](LICENSE)
