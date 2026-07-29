# Dashboard recipes

Everything here uses **built-in cards only**, except where a custom card is
named explicitly. Back to the [README](../README.md).

Entity ids in the examples follow an English instance — check
Developer tools → States for yours, they
[follow your Home Assistant language](../README.md#entities).

## The map

The fires show up on the standard map card. Naming the source is all it takes —
plus one line that is not the default:

```yaml
type: map
geo_location_sources:
  - nasa_firms
entities:
  - zone.home
default_zoom: 8
cluster: false
theme_mode: auto
```

Only fires inside the radius you configured ever become entities, so the map
never shows detections from beyond it.

### Why `cluster: false`

Left at its default, the card merges every marker within 40 screen pixels into
one disc carrying a count. At `default_zoom: 8` those 40 pixels are on the order
of 15 to 20 km of ground, depending on how far north you are — so the moment
there is more than one fire in the area, several of them collapse into a single
blue bubble, and the colours collapse with them. The feature is worth having on
a map of five phones. On a map of fires it hides the thing you came to look at.

Turning it off has a real price: with many fires the markers overlap instead.
That is the trade, and it is yours to make — a count you can zoom into, or
colours you can read at a glance. The option needs Home Assistant 2025.6 or
newer; before that the card clusters with no way to stop it.

**When markers do overlap, the one in front is the southernmost, not the
strongest.** The card draws them in screen order and sets nothing per entity, so
a weak fire can cover a fierce one. Zooming in separates them.

### The built-in Map panel

The *Map* entry in the sidebar shows the fires as well, with no card to set up —
which makes it the fastest way to see whether this thing works at all. It always
clusters and offers no setting for it, so treat it as an answer to *where*, not
to *how strong*.

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
marker on it via `--ha-marker-size`, so it cannot vary per fire.

### Smaller markers

You can change that one size — for every marker on the card at once — with
`card-mod` from HACS:

```yaml
type: map
geo_location_sources:
  - nasa_firms
entities:
  - zone.home
default_zoom: 8
cluster: false
theme_mode: auto
card_mod:
  style: |
    ha-card {
      --ha-marker-size: 28px;
    }
```

The default is 48 px. The variable cascades from the card down into the markers;
checked on a live dashboard rather than inferred from the frontend source.

**It is not the answer to a crowded map, though.** The size applies to every
marker equally, so it cannot carry intensity, and shrinking everything makes a
dense area harder to read, including the one fire that matters. For crowding,
`cluster: false` plus the band colours is the lever that works — see
[Why `cluster: false`](#why-cluster-false).

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
  cluster: false
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
you nothing until someone says what they are. Replace the three entity ids on
the first three lines with yours and paste it in:

```yaml
type: vertical-stack
cards:
  - type: map
    geo_location_sources:
      - nasa_firms
    entities:
      - zone.home
    default_zoom: 8
    cluster: false
    theme_mode: auto
    aspect_ratio: "1:1"
  - type: markdown
    content: |
      {% set s = 'sensor.firms_43_60_3_90_nearest_hotspot' %}
      {% set n = 'sensor.firms_43_60_3_90_hotspots' %}
      {% set w = 'sensor.firms_43_60_3_90_wind_at_nearest_hotspot' %}
      {% set dist = states(s) %}
      {%- if dist in ['unknown', 'unavailable'] -%}
      ### No active fires
      Nothing detected in the area you are monitoring.
      {%- else -%}
      ### Nearest fire: {{ dist }} {{ state_attr(s, 'unit_of_measurement') }} away
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
      **Wind at the fire** — from the {{ state_attr(s, 'wind_direction') }} at {{ states(w) | float | round(1) }} {{ state_attr(w, 'unit_of_measurement') }}, pushing the smoke {% if off <= 60 %}**towards you**{% elif off <= 120 %}**past you to one side**{% else %}**away from you**{% endif %} ({{ off | round }}° off the line to you).
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
> **Wind at the fire** — from the NW at 23.8 km/h, pushing the smoke **past you to one side** (90° off the line to you).
> Wind shifts, and slope and fuel matter as much: this is the air at the fire right now, not a prediction of where the smoke ends up.

Every branch is covered: no fires in range collapses it to two lines, a failed
weather lookup only replaces the wind sentence, and below roughly 3 m/s the card
adds a line warning that the wind direction is then close to meaningless.

**Why the card reads the wind twice.** The speed it prints comes from the wind
*entity*, so it arrives with a unit attached and in whatever your instance
displays — km/h here, mph on a US instance. The 3 m/s check underneath reads the
raw `wind_speed` *attribute* instead, because a threshold has to compare against
a fixed unit, and the attribute is always m/s no matter what the entity shows.

**And why the distance names its unit.** Same reason, one line up: the
nearest-hotspot sensor follows your unit system too, so the heading takes the
unit off the entity rather than printing `km`. On a US instance that number is
in miles — while the markers on the map above it stay in kilometres, because
`geo_location` entities have no unit conversion at all.

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

## A custom map with your own tiles and layering

Everything above uses the built-in card. If you want your own basemap, control
over which marker draws on top, or a free choice of icon, `auto-entities` plus a
third-party map card gets you there. Both come from HACS.

This is @pyspilf's setup from the community thread, with his API key removed:

```yaml
type: custom:auto-entities
card:
  type: custom:map-card        # map-card by nathan.gs
  cluster_markers: false
  theme_mode: light
  focus_entity: zone.home
  zoom: 8
  tile_layers:
    - url: https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png?api_key=YOUR_KEY
      attribution: © Stadia Maps © OpenMapTiles © OpenStreetMap
filter:
  include:
    - entity_id: geo_location.wildfire_hotspot_*
      attributes:
        intensity: extreme
      options:
        z_index_offset: 900
        display: icon
        icon: mdi:fire
        color: "#FF0000"
    - entity_id: geo_location.wildfire_hotspot_*
      attributes:
        intensity: high
      options:
        z_index_offset: 800
        display: icon
        icon: mdi:fire
        color: "#FF4D00"
    - entity_id: geo_location.wildfire_hotspot_*
      attributes:
        intensity: moderate
      options:
        z_index_offset: 700
        display: icon
        icon: mdi:fire
        color: "#FF7400"
    - entity_id: geo_location.wildfire_hotspot_*
      attributes:
        intensity: low
      options:
        z_index_offset: 600
        display: icon
        icon: mdi:fire
        color: "#FFC100"
sort:
  method: friendly_name
```

**What it buys you** is the `z_index_offset` ladder: the fiercest fire is drawn
on top of the weaker ones. The built-in card cannot do that — it orders markers
by screen position, so the southernmost wins regardless of intensity.

Three details worth keeping when you adapt it:

- **`theme_mode: light` is not a typo.** That card inverts its own colours under
  Home Assistant's dark theme, so it needs the light setting to come out dark.
  This is the card's behaviour, not ours: on the built-in card our band colours
  render as authored in both themes.
- **`display: icon` replaces our marker picture entirely**, which is why the
  four colours are repeated in the card config. They are the same bands, so the
  map keeps meaning the same thing.
- **With more than one config entry**, add `origin: "43.60/3.90"` next to each
  `intensity` to keep the locations apart — see
  [Two locations on one card](#two-locations-on-one-card).

Worth repeating pyspilf's own verdict on it: for most people the built-in card
is enough. This is for when you have a reason.

## Bubble Card

Using [Bubble Card](https://github.com/Clooos/Bubble-Card)? The same two cards
drop straight into a `pop-up` as its `cards:` list, so a tile on your dashboard
opens the full picture.
