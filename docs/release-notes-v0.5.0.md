# v0.5.0

Text for the GitHub release. Delete this file once the release is published,
or keep it as the running draft for the next one.

## Release body

### ⚠️ Add one line to your map card

```yaml
cluster: false
```

By default the map card merges every marker within 40 screen pixels into one
disc with a count on it. At the `default_zoom: 8` the README prints, that is 15
to 20 km of ground — so as soon as more than one fire is in your area, several
of them collapse into a single bubble and the intensity colours go with them.

Turning it off costs the opposite: with many fires the markers overlap instead.
Both sides are in [`docs/dashboard.md`](docs/dashboard.md#why-cluster-false),
with two findings from the same check: the built-in Map panel always clusters
and has no setting for it, and when markers overlap the one in front is the
southernmost, not the strongest.

### A blueprint for the proximity alert

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fbangboomben%2Fha-nasa-firms%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fnasa_firms%2Ffire_within_distance.yaml)

Pick the *Nearest hotspot* sensor, set a distance, choose what should happen.
The message carries the distance, the direction and — when a reading exists —
where the wind at that fire is pushing the smoke.

It watches the *nearest* fire and triggers as that distance crosses your line
from outside to inside. A fire that is already closer than your distance when
you create the automation raises nothing, and neither does a second, closer fire
appearing later. Both need a "new fire" signal that lands in a later release.

### Wind speed as an entity

`sensor.<name>_wind_at_nearest_hotspot` carries its unit and converts to your
unit system — km/h on a metric instance, mph on a US one. The `wind_speed`
attribute is unchanged and stays the raw value in m/s.

### The FIRMS region picks itself

Setup no longer asks which of NASA's regional services to use; it follows from
the map pin. The extents were read from the services themselves. Where FIRMS
covers nothing at all, setup now says so instead of monitoring nothing.

**A bug turned up in that check:** the dropdown offered `Russia_and_Asia` and the
service is called `Russia_Asia`. The wrong name was an HTTP 400 on every request
since the first release. Existing entries are repaired automatically.

### Every fire carries its bearing

`bearing` and `direction` have been computed since v0.2.0 and published only for
the nearest fire. They are on every fire entity now, so the upwind/downwind
calculation works for any fire rather than only the closest one.

### When something goes wrong

- **Diagnostics download** — regional service, area size, per-satellite counts,
  what the filters dropped, whether the response was cut off, and every fire as
  a distance and a bearing. The MAP_KEY and every coordinate are removed.
- **A repairs notice** when FIRMS caps the response, because every count for that
  location is then too low and none of them looks wrong.
- **Issue forms** that ask for the diagnostics.

### Also

`daynight` is gone from the fire attributes — FIRMS never sends it and it was
`None` in every release. New recipes in [`docs/dashboard.md`](docs/dashboard.md).

### Upgrade notes

1. **Home Assistant 2025.6 is now the minimum**, because that is where the map
   card gained the `cluster` option.
2. **Copied the map card? Add `cluster: false`.** Nothing else to reconfigure.
3. `daynight` is gone from fire entities. It never had a value.
4. One new entity per location: the wind speed sensor. It reads `unknown`
   whenever there is no fire in range.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway, used under
CC BY 4.0.
