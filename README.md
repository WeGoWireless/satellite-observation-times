# Wildfire Monitor for Home Assistant

Wildfire Monitor combines **NASA FIRMS** satellite fire detections with **NOAA NESDIS Next Generation Fire System (NGFS)** detections to provide a more useful incident-level wildfire view in Home Assistant.

It keeps raw satellite evidence available, but also groups detections into probable wildfire incidents, associates FIRMS and NGFS observations when they represent the same fire, exposes NOAA incident names when available, and provides sensors designed for dashboards and alerts.

> This project is a fork and extension of `bangboomben/ha-nasa-firms`. The original MIT license and copyright notice are retained in `LICENSE`.

## Highlights

- NASA FIRMS VIIRS/MODIS wildfire detections
- NOAA NGFS / GOES detections
- FIRMS + NGFS incident association
- Named wildfire incidents when NOAA supplies an incident name
- Multiple NGFS tracking features can be combined into one named incident
- Nearest fire and nearest named wildfire sensors
- Configurable monitoring radius and separate alert radius
- Wind-at-fire and smoke-direction information
- Regional smoke-threat sensors
- Seasonal monitoring modes and configurable polling intervals
- Predicted VIIRS satellite observation times
- FIRMS truncation detection and Home Assistant Repair warning
- Ignore zones and persistent heat-source filtering inherited from the original integration

## Installation with HACS as a custom repository

1. In Home Assistant, open **HACS**.
2. Open the **three-dot menu** and choose **Custom repositories**.
3. Add:

   `https://github.com/WeGoWireless/ha-wildfire-monitor`

4. Select **Integration** as the repository type and add it.
5. Open **Wildfire Monitor** in HACS and choose **Download**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration** and search for **Wildfire Monitor**.

Requires Home Assistant **2025.6.0** or newer.

## Manual installation

Copy `custom_components/nasa_firms` into your Home Assistant `config/custom_components/` directory and restart Home Assistant.

The internal Home Assistant domain remains `nasa_firms` for compatibility with installations of the original integration.

## Configuration

You will need a free NASA FIRMS MAP_KEY. Obtain one from the NASA FIRMS API page, then add Wildfire Monitor from **Settings → Devices & services**.

The configuration flow lets you choose the monitored location, monitoring radius, satellites, detection filters, seasonal monitoring behavior, polling intervals, and ignore zones.

### Monitoring radius vs. alert radius

These are intentionally separate:

- **Monitoring radius** controls how large an area is analyzed for fires and regional smoke awareness.
- **Alert radius** identifies incidents close enough to be considered inside your local area of concern.

You can therefore monitor a broad region while keeping a smaller local alert boundary.

## Incident model

Satellite products report detections, not necessarily one row per wildfire. Wildfire Monitor therefore keeps several layers of information:

1. Raw FIRMS and NGFS detections.
2. Fine-grained FIRMS hotspot clusters and NGFS tracking features.
3. FIRMS incident groups.
4. Named NGFS incident groups when multiple nearby tracking features share an incident name.
5. Conservative FIRMS ↔ NGFS association to represent the same wildfire as one combined incident.

The current association model uses geography as the primary constraint. FIRMS incident grouping and cross-feed matching use a 5 km (about 3.1 mi) distance threshold, with a 24-hour cross-feed time window to account for the different observation cadences of geostationary GOES and polar-orbiting VIIRS satellites.

## Useful sensors

Entity IDs depend on the configured entry name. Important sensors include:

- **Nearby wildfires** — probable incident count with a compact incident list
- **Named wildfires** — named incidents sorted by distance
- **Nearest combined fire** — closest current FIRMS/NGFS fire representation; useful for proximity alerts
- **Nearest combined incident** — closest incident-level representation
- **Nearest named wildfire** — closest incident with a NOAA-supplied name
- **Nearest NGFS smoke threat** — closest wind-monitored NGFS fire whose smoke is directed toward the monitored location
- **Next satellite observation** — predicted next VIIRS observation window

Raw FIRMS/NGFS diagnostic sensors remain available for troubleshooting and detailed dashboards.

## Compact dashboard card

Replace `YOUR_PREFIX` with the common prefix Home Assistant assigned to your integration entities. Do not publish your own coordinate-bearing entity prefix if you consider the monitored location private.

```yaml
type: markdown
content: |
  {% set combined = 'sensor.YOUR_PREFIX_nearest_combined_fire' %}
  {% set named = 'sensor.YOUR_PREFIX_nearest_named_wildfire' %}
  {% set named_list = 'sensor.YOUR_PREFIX_named_wildfires' %}
  {% set smoke = 'sensor.YOUR_PREFIX_nearest_ngfs_smoke_threat' %}
  {% set next_sat = 'sensor.YOUR_PREFIX_next_satellite_observation' %}

  ## 🔥 Wildfire Monitor
  {% set d = states(combined) %}
  {% set src = state_attr(combined, 'source') %}
  {% set dir = state_attr(combined, 'direction') %}
  {% set inside = state_attr(combined, 'inside_alert_radius') %}
  {% set frp = state_attr(combined, 'max_frp') %}
  {% set wind = state_attr(combined, 'wind_speed_mph') %}
  {% set winddir = state_attr(combined, 'wind_direction') %}
  {% set rel = state_attr(combined, 'smoke_relationship') %}
  **Nearest:** 🔥 **{{ d }} mi {{ dir or '' }}** · {{ src }}{% if inside %} · **⚠️ INSIDE ALERT AREA**{% endif %}  
  {% if frp is number %}{{ frp | round(1) }} MW{% endif %}{% if wind is number %} · Wind {{ wind | round(1) }} mph {{ winddir or '' }}{% endif %}{% if rel %} · Smoke {{ rel | title }}{% endif %}

  {% set nn = state_attr(named, 'name') %}
  {% if nn %}
  **Named:** 📍 **{{ nn }}** · {{ states(named) }} mi {{ state_attr(named, 'direction') or '' }} · {{ state_attr(named, 'source') }} · {{ state_attr(named, 'max_frp') | round(1) }} MW
  {% else %}
  **Named:** None detected
  {% endif %}

  {% if states(smoke) not in ['unknown','unavailable','none'] %}
  **💨 Smoke toward us:** **{{ state_attr(smoke, 'name') or 'Fire' }}** · {{ states(smoke) }} mi
  {% else %}
  **💨 Smoke toward us:** None
  {% endif %}

  {% set fires = state_attr(named_list, 'fires') or [] %}
  ### Named Wildfires · {{ fires | length }}
  {% for f in fires[:5] %}
  🔥 **{{ f.name }}** · {{ f.distance_miles }} mi · {{ f.max_frp | round(1) }} MW · {{ f.source }}  
  {% endfor %}

  {% set sat = state_attr(next_sat, 'satellite_name') %}
  {% set sat_time = states(next_sat) | as_datetime | as_local %}
  {% set mins = ((as_timestamp(sat_time) - as_timestamp(now())) / 60) | round(0) | int %}
  🛰️ **{{ sat or 'Satellite' }}:** {% if mins > 1 %}in {{ mins }} min{% elif mins >= 0 %}very soon{% else %}observation underway/passed{% endif %}
```

## Map card

FIRMS detections are exposed as `geo_location` entities and can be shown on Home Assistant's standard map card:

```yaml
type: map
geo_location_sources:
  - nasa_firms
entities:
  - zone.home
default_zoom: 8
cluster: false
```

## Data sources and limitations

Wildfire Monitor is a situational-awareness tool, not an emergency warning service. Satellite detections can be delayed, obscured by clouds or smoke, duplicated, misclassified, or absent between satellite observations. NGFS is treated as an experimental data source in the integration. Incident association is heuristic and should not be interpreted as an official incident boundary or identity determination.

For emergencies, use official local emergency-management and fire-agency information in addition to this integration.

## Updating

When installed through HACS as a custom repository, HACS can download updates from this GitHub repository. GitHub releases are recommended so users can select and roll back versions cleanly.

## Development

The integration lives under:

`custom_components/nasa_firms/`

Validation workflows for **Hassfest** and **HACS** are included under `.github/workflows/validate.yml`.

## License and upstream credit

MIT licensed. See `LICENSE`.

Wildfire Monitor is based on the original NASA FIRMS Home Assistant integration by `bangboomben` and includes substantial additional work for NOAA NGFS ingestion, incident association, named wildfires, smoke analysis, seasonal monitoring, and dashboard-oriented sensors.
