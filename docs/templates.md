# Templates and automations

What each attribute is good for, and how to calculate with it. Back to the
[README](../README.md), or on to the [dashboard recipes](dashboard.md).

Entity ids in the examples follow an English instance — check
Developer tools → States for yours, they
[follow your Home Assistant language](../README.md#entities).

## Pointing at the nearest fire

The nearest-hotspot sensor carries the id of the fire entity it is reporting, so
you can read any of that fire's attributes without searching for it yourself:

```jinja
{% set e = state_attr('sensor.firms_43_60_3_90_nearest_hotspot', 'nearest_entity_id') %}
{{ state_attr(e, 'frp_mw') }} MW, {{ state_attr(e, 'confidence') }} confidence,
seen by {{ state_attr(e, 'satellites') | join(' + ') }}
```

`bearing` (degrees) and `direction` (16-point compass) are on the same sensor —
great-circle values, so they stay correct at high latitudes:

```jinja
Fire {{ states('sensor.firms_43_60_3_90_nearest_hotspot') }} km
{{ state_attr('sensor.firms_43_60_3_90_nearest_hotspot', 'direction') }}
```

## Wind at the fire

The same sensor carries the wind **at the nearest fire's own coordinates**, not
at your house — which is the whole point, since the two can differ completely
across a valley:

| Attribute | Meaning |
|---|---|
| `wind_bearing` | Direction the wind is blowing **from**, in degrees (0 = from the north) |
| `wind_direction` | The same, as a 16-point compass abbreviation (`SW`, `NNE`, …) |
| `wind_speed` | Wind speed at 10 m above ground, always in **m/s** — the raw value, for calculating with |

`wind_direction` is the one to put on a dashboard; `wind_bearing` is the one to
calculate with, exactly like `direction` and `bearing` for the fire itself.

**For the speed, use the entity, not the attribute.**
`sensor.<name>_wind_at_nearest_hotspot` carries the same reading with its unit
attached, converted to whatever your instance displays — km/h on a metric
instance, mph on a US one. The attribute stays **m/s whatever the entity shows**,
which is what makes it the right one for a threshold and the wrong one to print
without saying so. Reading `4.4` next to a sensor whose unit is `km` is how this
distinction got added in the first place.

Source: [met.no Locationforecast](https://api.met.no/weatherapi/locationforecast/2.0/documentation).
One request per 15-minute cycle, for the nearest fire only, cached according to
met.no's own `Expires` header. All three attributes are `None` when there is no
fire in range or the lookup did not succeed — the fire data is unaffected
either way.

### Upwind or downwind: work it out yourself

`bearing` is measured **from you to the fire**, `wind_bearing` is the direction
the wind comes **from** at the fire. The wind pushes smoke towards
`wind_bearing + 180°`, and the line from the fire to you is `bearing + 180°` —
the same 180° on both sides, so the smoke travels along your line of sight
exactly when the two raw numbers are close:

```jinja
{% set s = 'sensor.firms_43_60_3_90_nearest_hotspot' %}
{% set fire = state_attr(s, 'bearing') %}
{% set wind = state_attr(s, 'wind_bearing') %}
{% if fire is not none and wind is not none %}
  {# 0 deg = wind pushing along the fire-to-you line, 180 deg = the other way #}
  {% set delta = (((wind - fire) + 180) % 360 - 180) | abs | round %}
  Fire {{ states(s) }} km {{ state_attr(s, 'direction') }},
  wind from {{ state_attr(s, 'wind_direction') }} at
  {{ (state_attr(s, 'wind_speed') * 3.6) | round(1) }} km/h,
  {{ delta }}° off the line towards you.
{% endif %}
```

**Read that number for what it is.** It is a geometry calculation on two
observations, not a safety assessment:

- `wind_speed` and `wind_bearing` are a **forecast** for the fire's grid cell,
  not a measurement at the flame front, and they come from the forecast step
  nearest the current time — hourly resolution, roughly 1 km of ground.
- **Wind turns.** A comfortable 170° now says nothing about the next hour, and a
  wind shift is the classic way a fire surprises people.
- **In light wind the direction barely means anything.** Below roughly 3 m/s,
  forecast models disagree wildly: on a spot checked while writing this, two
  independent models agreed on the speed to within 0.2 m/s and were 65° apart
  on the direction. Weight the direction by the speed next to it.
- **Terrain beats wind direction.** Fires run uphill far faster than downhill,
  large fires generate their own wind, and slope, fuel and humidity matter as
  much as the direction the smoke is drifting today.
- The wind **at the fire** is not the wind along the whole path to you, and this
  says nothing about plume height or how far smoke will actually carry.

So: a useful extra input, never an all-clear. Your country's official warning
channel stays the authority on whether to act.

### The same maths for a fire that is not the closest

Every fire carries its own `bearing` and `direction`, so the calculation works
for any of them — take the bearing off the fire entity instead of off the
sensor:

```jinja
{% set f = 'geo_location.wildfire_hotspot_43_45_4_90' %}
{% set s = 'sensor.firms_43_60_3_90_nearest_hotspot' %}
{% set fire = state_attr(f, 'bearing') %}
{% set wind = state_attr(s, 'wind_bearing') %}
{% if fire is not none and wind is not none %}
  {% set delta = (((wind - fire) + 180) % 360 - 180) | abs | round %}
  Fire {{ states(f) }} km {{ state_attr(f, 'direction') }},
  {{ delta }}° off the line towards you.
{% endif %}
```

**The wind in it is still the nearest fire's**, because that is the only point
looked up. Using it for a different fire is a judgement about how far one
reading carries, and it is yours to make:

- **A few kilometres is fine.** The lookup is rounded to about 1 km before it
  is sent, and the forecast grid behind it is coarser than that — a fire two
  kilometres from the one we asked about is genuinely covered by the same
  reading.
- **Tens of kilometres is not.** That is several grid cells, i.e. different
  weather, and the number you would get is arithmetic rather than an
  observation.
- **In mountains it can be wrong at any distance.** Valley winds do not care
  how close two points look on a map.

If the fire you care about is far from the nearest one, treat the angle as
undefined instead of as a number you happen to be able to compute.

### What leaves your instance

When there is a fire in range, its coordinates — rounded to about 1 km — are
sent to met.no once per update cycle to look up the wind. Nothing about your own
location, your MAP_KEY or your instance is included.

## Proximity alert

### The blueprint

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbangboomben%2Fha-nasa-firms%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnasa_firms%2Ffire_within_distance.yaml)

Pick the *Nearest hotspot* sensor of the location you want to watch, set a
distance, choose what should happen. The message is built for you and carries
the distance, the direction, and — only when a reading exists — where the wind
at that fire is currently pushing the smoke:

> Fire detected 8.2 km ENE. Wind at the fire is pushing the smoke towards you
> (30° off the line to you).

Inside the action you configure, two variables are ready to use: `{{ message }}`
and `{{ title }}`. The action is a free choice, so it does not have to be a
notification — a script, a light, a siren and a TTS announcement all work.

**The one real gap.** It watches the *nearest* fire and triggers on the moment
that distance crosses your line from outside to inside. So:

- **A fire already inside the line when you create the automation raises
  nothing.** The crossing happened before the automation existed. Set a distance
  of 100 km while the nearest fire sits at 2.8 km and it will simply never fire
  — correct behaviour, and the first thing to check when it stays quiet.
- **A second, closer fire raises nothing either.** The distance drops further,
  which is not a crossing.

Both are the same missing piece. Closing it needs a "new fire" signal the
integration does not have yet; it is planned, and the blueprint will be rebuilt
on it.

The wind sentence is the same geometry as
[the section above](#upwind-or-downwind-work-it-out-yourself), with the same
limits: it describes where the air is moving at this moment, it is not a
forecast of where the smoke ends up, and "away from you" is not an all-clear.

### Or build your own

```yaml
alias: "Wildfire proximity warning"
triggers:
  - trigger: numeric_state
    entity_id: sensor.firms_43_60_3_90_nearest_hotspot
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

## Checking your data is complete

Two attributes on the hotspot sensor say when the picture is not the whole
picture:

```jinja
{% set n = 'sensor.firms_43_60_3_90_hotspots' %}
{% if state_attr(n, 'truncated') %}
  FIRMS capped the response — there are more fires than are being shown.
{% endif %}
{{ state_attr(n, 'ignored_detections') }} detections dropped by ignore zones.
```

`truncated` means the area is too large for a single FIRMS response and counts
are too low; shrink the radius or raise the confidence/FRP filter.
`ignored_detections` is how many detections your
[ignore zones](../README.md#ignore-zones) removed — useful to confirm a zone is
doing what you meant it to.
