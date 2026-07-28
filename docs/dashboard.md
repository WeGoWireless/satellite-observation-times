# Dashboard recipes

Everything here uses **built-in cards only**, except where a custom card is
named explicitly. Back to the [README](../README.md).

Entity ids in the examples follow an English instance — check
Developer tools → States for yours, they
[follow your Home Assistant language](../README.md#entities).

## The map

The fires show up on the standard map card — you add the card, it needs no
configuration beyond naming the source:

```yaml
type: map
geo_location_sources:
  - nasa_firms
entities:
  - zone.home
default_zoom: 8
theme_mode: auto
```

Only fires inside the radius you configured ever become entities, so the map
never shows detections from beyond it.

## Marker colours

Each fire is drawn as a flame marker, coloured by how hard it is burning.

| Colour | `intensity` | Fire radiative power |
|---|---|---|
| 🔴 red | `extreme` | 100 MW and up |
| 🟠 deep orange | `high` | 50–100 MW |
| 🟠 orange | `moderate` | 10–50 MW |
| 🟡 amber | `low` | under 10 MW |
| ⚪ grey | `null` | no FRP reading came through |

The bands are **absolute**, not relative to what is currently on screen: a
colour has to mean the same thing every time you look, or you never learn to
read it. The same value is on each fire as the `intensity` attribute, so cards
and templates can filter or style by band without hard-coding the thresholds.

**It says how hard the fire is radiating, not how dangerous it is to you.** A
small fire in the next valley outranks a large one a hundred kilometres away,
and FRP knows about neither distance nor terrain.

Two details behind the implementation, in case you wonder why it looks like it
does. The map card cannot use an entity's `icon` for markers it pulls in through
`geo_location_sources` — it would label them with the first letters of the
entity name instead — so the flame ships as the entity *picture*. And marker
**size** deliberately carries no meaning: the card sets one size for every
marker on it via `--ha-marker-size`, so it cannot vary per fire. Set that
variable in a theme if you want smaller pins.

## Two locations on one card

`nasa_firms` is a single source name shared by all config entries, so a card set
up as above plots the fires of all of them together. Worse than the zoomed-out
view: a fire's **state is its distance from its own entry's origin**, so a fire
belonging to your other location shows a perfectly believable, wrong number on
this card.

Every fire therefore carries an `origin` attribute — the coordinates of the
entry it belongs to, in the same `lat/lon` form as the entry title. The core map
card cannot filter on it, but a filtering card can:

```yaml
type: custom:auto-entities
card:
  type: map
filter:
  include:
    - domain: geo_location
      attributes:
        origin: "43.60/3.90"
```

Without such a card, give each location its own map listing its fire entities
explicitly, or accept that one card means one combined view.

## The map plus everything the integration knows

A map answers *where*. This pairs it with the rest — how far, how strong, seen
by which satellites, and the wind at the fire. It deliberately spells out what
each number means instead of printing bare values: `nominal` and `1.19 MW` tell
you nothing until someone says what they are. Replace the two entity ids on the
first two lines with yours and paste it in:

```yaml
type: vertical-stack
cards:
  - type: map
    geo_location_sources:
      - nasa_firms
    entities:
      - zone.home
    default_zoom: 8
    theme_mode: auto
    aspect_ratio: "1:1"
  - type: markdown
    content: |
      {% set s = 'sensor.firms_43_60_3_90_nearest_hotspot' %}
      {% set n = 'sensor.firms_43_60_3_90_hotspots' %}
      {% set km = states(s) %}
      {%- if km in ['unknown', 'unavailable'] -%}
      ### No active fires
      Nothing detected in the area you are monitoring.
      {%- else -%}
      ### Nearest fire: {{ km }} km away
      It lies to the **{{ state_attr(s, 'direction') }}** of you. {{ states(n) }} fires detected in the monitored area in the last 24 hours.
      {%- set e = state_attr(s, 'nearest_entity_id') %}
      {%- if e %}

      **How strong** — {{ state_attr(e, 'frp_mw') }} MW of radiated heat, i.e. how fiercely it was burning as the satellite passed over.
      **How certain** — {{ state_attr(e, 'confidence') }}. That is the satellite's own confidence that this is a real fire rather than a false alarm; it runs low, nominal, high.
      **When** — {{ state_attr(e, 'acquired') }}, seen by {{ state_attr(e, 'satellites') | join(' and ') }}.
      {%- endif %}
      {%- set fire = state_attr(s, 'bearing') %}
      {%- set wind = state_attr(s, 'wind_bearing') %}
      {%- set speed = state_attr(s, 'wind_speed') %}
      {% if wind is none or fire is none %}
      **Wind** — no reading for the fire's location at the moment.
      {%- else %}
      {%- set off = (((wind - fire) + 180) % 360 - 180) | abs %}
      **Wind at the fire** — from the {{ state_attr(s, 'wind_direction') }} at {{ (speed * 3.6) | round }} km/h, pushing the smoke {% if off <= 60 %}**towards you**{% elif off <= 120 %}**past you to one side**{% else %}**away from you**{% endif %} ({{ off | round }}° off the line to you).
      {%- if speed < 3 %}
      At this wind speed the direction says little — forecast models disagree by tens of degrees in light wind.
      {%- endif %}
      Wind shifts, and slope and fuel matter as much: this is the air at the fire right now, not a prediction of where the smoke ends up.
      {%- endif %}
      {%- endif %}
```

It renders roughly like this:

> ### Nearest fire: 9.2 km away
> It lies to the **SW** of you. 12 fires detected in the monitored area in the last 24 hours.
>
> **How strong** — 1.19 MW of radiated heat, i.e. how fiercely it was burning as the satellite passed over.
> **How certain** — nominal. That is the satellite's own confidence that this is a real fire rather than a false alarm; it runs low, nominal, high.
> **When** — 2026-07-26 01:32 UTC, seen by noaa21 and snpp.
>
> **Wind at the fire** — from the NW at 24 km/h, pushing the smoke **past you to one side** (90° off the line to you).
> Wind shifts, and slope and fuel matter as much: this is the air at the fire right now, not a prediction of where the smoke ends up.

Every branch is covered: no fires in range collapses it to two lines, a failed
weather lookup only replaces the wind sentence, and below roughly 3 m/s the card
adds a line warning that the wind direction is then close to meaningless.

### About the wind sentence

It puts the geometry into words — the same calculation as the
[upwind/downwind recipe](templates.md#upwind-or-downwind-work-it-out-yourself),
stated as *towards*, *past* or *away from* you, **with the angle itself in
brackets**.

The three words split the half-circle into equal thirds, at 60° and 120°. Those
are not arbitrary: at exactly 60° the part of the smoke's movement that runs
along the line to you is half its speed, and at 120° it is half its speed in the
opposite direction. So *towards you* means more than half the drift is coming
your way, *away from you* means more than half is leaving, and *past you to one
side* is the genuinely undecided middle. The angle is printed next to the words
because a bracket is still a bracket: 61° and 119° both read "past you" and
look nothing alike.

**Read it as the observation it is**, with the caveats from
[the wind section](templates.md#wind-at-the-fire) in mind. "Away from you"
describes where the air is moving at this moment; it is not an all-clear, and
the card says so on the next line. If you would rather have the raw angle and no
wording at all, swap that one line for the version in the recipe.

## Bubble Card

Using [Bubble Card](https://github.com/Clooos/Bubble-Card)? The same two cards
drop straight into a `pop-up` as its `cards:` list, so a tile on your dashboard
opens the full picture.
