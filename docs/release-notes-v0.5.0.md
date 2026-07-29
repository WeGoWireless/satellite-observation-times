# v0.5.0 — arriving without a guide

Text for the GitHub release. Delete this file once the release is published,
or keep it as the running draft for the next one.

## Release body

Everything here comes from watching people install this without having read
anything first — and from checking a few things against the real service
instead of against our own code. Two of those checks turned up bugs that had
been shipping since the beginning.

### ⚠️ The recommended map card was hiding your fires

**If you copied the map card out of the README, add one line to it:**

```yaml
cluster: false
```

Left at its default, the map card merges every marker within 40 screen pixels
into a single disc with a count on it. At the `default_zoom: 8` the README
prints, that is 15 to 20 km of ground. So the moment there was more than one
fire in your area — the situation this integration exists for — several of them
collapsed into one blue bubble, and the intensity colours from v0.4.0 went with
them.

Turning it off costs the opposite: with many fires the markers overlap instead.
Both halves are now in [`docs/dashboard.md`](docs/dashboard.md#why-cluster-false),
along with two things that came out of the same check — the built-in Map panel
in the sidebar always clusters and has no setting for it, and when markers do
overlap the one in front is the southernmost, not the strongest.

### An alert you can click together

The point of this integration was always the alert, and until now it was a
template in the docs to copy, adapt and debug. There is a blueprint now: pick
the *Nearest hotspot* sensor, set a distance, choose what should happen.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbangboomben%2Fha-nasa-firms%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnasa_firms%2Ffire_within_distance.yaml)

The message writes itself:

> Fire detected 8.2 km ENE. Wind at the fire is pushing the smoke towards you
> (30° off the line to you).

The wind half only appears when there is a reading. The action is a free choice,
so a script, a siren or a spoken announcement work as well as a notification.

**What it does not catch** is written into the blueprint's own description
rather than left to be discovered: it watches the *nearest* fire and triggers as
that distance crosses your line from outside to inside. A fire that is already
closer than your distance when you create the automation raises nothing, and
neither does a second, closer fire appearing later. Both need a "new fire"
signal that does not exist yet — it is the headline of a later release, and the
blueprint will be rebuilt on it.

Asked for by @magicbeing within an hour of installing.

### Wind speed now carries its unit

@pyspilf read `wind_speed: 4.4` in the states view as 4.4 km/h and reported the
dashboard card, which showed 16 km/h, as a bug. Both were the same reading —
met.no gives m/s — and the reason he misread it is that the `km` of the distance
sensor sits directly under the wind attributes.

An attribute cannot carry a unit; an entity can. So the reading also exists as
`sensor.<name>_wind_at_nearest_hotspot` now, where Home Assistant prints the
unit and converts it to your unit system: km/h on a metric instance, mph on a
US one. **The `wind_speed` attribute stays exactly as it was** — every published
template reads it, and it is the raw value any calculation wants.

### The FIRMS region picks itself — and one of them was broken

Setup used to ask which of NASA's dozen regional services to use, right above a
map pin that already answers the question. Picking wrong returned an empty feed
and no explanation. **That field is gone**: the region follows from the pin.

The extents come from the services themselves — every FIRMS server publishes its
own bounding box, so the twelve boxes were read off the live endpoints rather
than guessed. They overlap on purpose, and the one a point sits deepest inside
wins. They also leave gaps: pick a spot FIRMS does not cover and setup now says
so instead of quietly monitoring nothing.

Checking those names against the live endpoints turned up a bug that had been
shipping since the first release: the dropdown offered **`Russia_and_Asia`** and
the service is called **`Russia_Asia`**. The wrong name is an HTTP 400 on every
single request, so anyone in Russia or most of Asia who picked it has never seen
a fire. **Existing entries are repaired automatically on upgrade.**

### Every fire knows which way it lies

`bearing` and `direction` were computed for every fire since v0.2.0 and
published only for the nearest one. They are on every fire entity now. No new
data and no new requests — the numbers were already there and were being thrown
away.

It matters because the upwind/downwind calculation needs the bearing of *the
fire it is about*. Until now it could only be done for the closest one, whether
or not that was the one worth asking about. The docs show it applied to another
fire, with the limit that comes with it: the wind is still the nearest fire's,
which covers a fire two kilometres away and does not cover one eighty kilometres
away.

### When something does go wrong

- **Diagnostics.** *Configure* → ⋮ → *Download diagnostics* now produces
  everything a bug report needs: which regional service, how large an area, what
  each satellite returned, what the filters dropped, whether the response was cut
  off, and every fire as a distance and a bearing. The MAP_KEY is removed, and so
  is every coordinate — your location, and the ignore zones around it, are not in
  the file.
- **A repairs notice for truncated results.** When FIRMS caps the response, every
  number for that location is too low and none of them looks wrong. That has been
  an attribute and a log line since v0.4.0; it is now a notice in
  Settings → System → **Repairs**, with what to change. It clears itself.
- **Issue forms** that ask for the diagnostics by name — and make "I checked this
  for my MAP_KEY" a required checkbox.

### Also in this release

- **`daynight` is gone from the fire attributes.** It was `None` in every
  release. The layer schema declares the field and the GeoJSON never carries it —
  checked across three satellites, both windows and three regions. Nothing to
  fix, only something to stop promising.
- **New recipes** in [`docs/dashboard.md`](docs/dashboard.md): @pyspilf's
  `auto-entities` map with per-intensity layering, and a tested `card-mod`
  snippet for smaller markers.
- The README notes that **GDACS has no fire category** — it covers drought,
  earthquake, flood, tropical cyclone, tsunami and volcano. Raised by
  @Mariusthvdb, who had been relying on it for exactly this.

**Upgrade notes.**

1. **Home Assistant 2025.6 is now the minimum**, because that is where the map
   card gained the `cluster` option the recommended card depends on.
2. **Copied the map card? Add `cluster: false`.** Nothing else to reconfigure.
3. The `daynight` attribute is gone from fire entities. It never had a value, so
   nothing can be depending on it.
4. One new entity per configured location: the wind speed sensor. It reads
   `unknown` whenever there is no fire in range.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway, used under
CC BY 4.0.
