# Templates and automations

What each attribute is good for, and how to calculate with it. Back to the
[README](../README.md), or on to the [dashboard recipes](dashboard.md).

Entity ids in the examples follow an English instance — check
Developer tools → States for yours, they
[follow your Home Assistant language](../README.md#entities).

**Distances: take the unit from the entity.** The nearest-hotspot sensor is a
distance sensor, so Home Assistant shows it in your instance's unit system —
kilometres on a metric instance, miles on a US one — and it can be overridden
per entity. The examples below therefore read
`state_attr(s, 'unit_of_measurement')` rather than printing `km`. The **fire
entities are the exception**: `geo_location` has no unit conversion, so their
state is in kilometres everywhere, whatever the sensor next to them says.

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
{% set s = 'sensor.firms_43_60_3_90_nearest_hotspot' %}
Fire {{ states(s) }} {{ state_attr(s, 'unit_of_measurement') }}
{{ state_attr(s, 'direction') }}
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
| `smoke_offset` | Angle between where that wind pushes the smoke and the line from the fire to you: `0` = straight at you, `180` = straight away. The finished number behind the card's *towards / past / away* wording |

`wind_direction` is the one to put on a dashboard; `wind_bearing` is the one to
calculate with, exactly like `direction` and `bearing` for the fire itself.
`smoke_offset` is the one to automate on: "closer than 20 km **and**
`smoke_offset` below 60" is the rule this integration exists to enable, and no
template has to carry the arithmetic.

**For the speed, use the entity, not the attribute.**
`sensor.<name>_wind_at_nearest_hotspot` carries the same reading with its unit
attached, converted to whatever your instance displays — km/h on a metric
instance, mph on a US one. The attribute stays **m/s whatever the entity shows**,
which is what makes it the right one for a threshold and the wrong one to print
without saying so. Reading `4.4` next to a sensor whose unit is `km` is how this
distinction got added in the first place.

Source: [met.no Locationforecast](https://api.met.no/weatherapi/locationforecast/2.0/documentation).
One request per fire per 15-minute cycle, cached according to met.no's own
`Expires` header. All four attributes are `None` when there is no fire in range
or the lookup did not succeed — the fire data is unaffected either way.

### The nearest fires carry their own wind

Not only the sensor: the **three nearest fires** — configurable up to five
under *Configure* → *Satellites and filters* — each carry `wind_bearing`,
`wind_direction`, `wind_speed` and `smoke_offset` on the fire entity itself,
each computed from that fire's own coordinates and bearing. Per-fire on
purpose: a forecast is a grid cell, and applying the near fire's wind to one
forty kilometres further out would be a plausible-looking wrong number.

On fires beyond that count the attributes are **absent entirely**, not `None`
— so "does this fire have a reading" is a presence check, which is exactly
what a filtering template wants. All fires currently drifting your way:

```jinja
{% for f in states.geo_location
   | selectattr('attributes.source', 'eq', 'nasa_firms')
   | selectattr('attributes.smoke_offset', 'defined')
   | selectattr('attributes.smoke_offset', 'le', 60) %}
{{ f.name }}: {{ f.state }} km {{ f.attributes.direction }}, {{ f.attributes.smoke_offset }}° off the line to you
{% endfor %}
```

The count is a budget. Every reading is one met.no request per refresh, and
every installation of this integration shares one identity with their service
— five per cycle is where a thousand installations still sit comfortably
inside met.no's stated limits. That is also why it is an option at all: like
the satellite choice, it changes what the integration asks external services
for.

### Any other fire: the `get_wind` action

For a fire outside the budget, ask for it directly — same cache, same
rate-limit respect, one request at most:

```yaml
action: nasa_firms.get_wind
data:
  entity_id: geo_location.wildfire_hotspot_43_45_4_90
response_variable: wind
# wind.wind_bearing, wind.wind_direction, wind.wind_speed,
# wind.smoke_offset, wind.forecast_time
```

Try it in Developer tools → Actions first — the entity picker only offers
this integration's fires. When no reading is available (met.no unreachable or
rate limited), the action **raises an error rather than returning empty
values**; in an automation that should carry on regardless, set
`continue_on_error: true` on the step.

### Upwind or downwind: work it out yourself

You do not have to any more: this exact calculation ships as `smoke_offset`,
on the sensor and on every fire with a reading. The recipe stays because a
number you can re-derive is a number you can trust — and because the pieces
are what any variant of your own starts from.

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
  Fire {{ states(s) }} {{ state_attr(s, 'unit_of_measurement') }}
  {{ state_attr(s, 'direction') }},
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

Nothing to borrow any more: a fire inside the wind budget carries its own
reading, computed at its own coordinates against its own bearing —

```jinja
{% set f = 'geo_location.wildfire_hotspot_43_45_4_90' %}
{% if state_attr(f, 'smoke_offset') is not none %}
  Fire {{ states(f) }} km {{ state_attr(f, 'direction') }},
  smoke {{ state_attr(f, 'smoke_offset') }}° off the line towards you.
{% endif %}
```

— and a fire outside it is what [the `get_wind`
action](#any-other-fire-the-get_wind-action) is for. Earlier versions of this
page showed how to apply the nearest fire's wind to a different fire; that
recipe is gone on purpose. A forecast covers a grid cell, and beyond a few
kilometres — in mountains, at any distance — the borrowed number is
arithmetic, not an observation. Per-fire readings exist precisely so nobody
has to make that judgement call.

### What leaves your instance

When there are fires in range, the coordinates of the nearest ones — as many
as the wind budget covers, rounded to about 1 km — are sent to met.no once per
update cycle to look up the wind, and one more per `get_wind` call. Nothing
about your own location, your MAP_KEY or your instance is included.

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
    # In whatever unit the sensor displays — 15 km on a metric instance,
    # 15 miles on a US one. See the note at the top of this page.
    below: 15
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "🔥 Wildfire warning"
      message: >-
        Fire {{ trigger.to_state.state }}
        {{ trigger.to_state.attributes.unit_of_measurement }} away
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

**`satellite_errors`** names each satellite whose fetch failed this cycle and
why — a timeout ("FIRMS request timed out after 60 s"), a connection error, an
HTTP status. The other satellites' data is unaffected, so the counts are
merely *lower*, not gone. Two things it never holds: a **rejected MAP_KEY**
starts the re-authentication flow instead of filling an attribute, and a cycle
where **every** satellite fails does not fill it either — the whole update then
counts as failed and the entities go `unavailable`. Partial trouble shows in
the attribute, total failure in the state.

## Is the data still arriving?

A cycle that found the same fires as the last one changes no state, so on a
dashboard "nothing changed" and "nothing arrived" look identical. Home
Assistant keeps the two apart: every entity has a `last_reported` timestamp
that is refreshed on **every** update, including one that changed nothing —
and unlike a "last updated" attribute, it costs the recorder nothing.

```yaml
template:
  - binary_sensor:
      - name: "FIRMS feed stale"
        state: >
          {{ (now() - states['sensor.firms_43_60_3_90_hotspots'].last_reported)
             .total_seconds() > 3600 }}
```

An hour is four missed cycles — one flaky poll should not page you. For a hard
outage — Home Assistant failed to set up the entry, or every satellite fetch
failed — the entities go `unavailable` instead, so that is a second trigger:

```yaml
automation:
  triggers:
    - trigger: state
      entity_id: sensor.firms_43_60_3_90_hotspots
      to: "unavailable"
      for: "00:10:00"
```

**The `for:` is not optional.** Every reload passes through a brief
`unavailable` — a restart, saving options — and checked against a live
instance's history, every `unavailable` phase this integration had ever
produced there was exactly that. Without the delay this alert fires on every
configuration change.
