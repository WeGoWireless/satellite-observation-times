# v0.4.0 — telling fires apart

Text for the GitHub release. Delete this file once the release is published,
or keep it as the running draft for the next one.

## Release body

Three ways this release helps you tell one fire from another: the ones you
already know about can be silenced, the ones that matter stand out on the map,
and a fire now stays the same entity from one refresh to the next.

### Ignore zones for known heat sources

FIRMS reports heat, not wildfires. A steel works, a flare stack or a smouldering
landfill is detected every single day, and nothing in the data separates it from
a real fire — same pixel, same brightness, often the same confidence.

*Configure* → **Ignore zones** → **Add a zone**, drag the pin onto the source,
size the circle, save. Detections inside a zone are dropped before anything else
touches them, and the count appears as `ignored_detections` on the hotspot
sensor so you can see a zone doing its job.

Raised in the community thread by @finity, whose factory had been setting the
alarm off since the very first version of this setup, back when it was still a
`geo_json_events` template.

**A zone is a blind spot and does not know what it is hiding** — a real fire
next to your factory is invisible while it burns inside that circle. Zones are
capped at 20 km for exactly that reason. There is deliberately **no automatic
version**: "ignore anything detected here for many days running" is precisely
what a fire front burning for a week looks like, and suppressing fires on that
guess is not a trade this integration makes.

### Map markers coloured by how hard a fire is burning

Every fire used to look identical, so the one worth a second look was
indistinguishable from background noise until you clicked it. Markers now carry
four bands of fire radiative power:

| Colour | `intensity` | FRP |
|---|---|---|
| 🔴 red | `extreme` | 100 MW and up |
| 🟠 deep orange | `high` | 50–100 MW |
| 🟠 orange | `moderate` | 10–50 MW |
| 🟡 amber | `low` | under 10 MW |

The thresholds and colours are @pyspilf's, who had already run exactly these
against live data in his own Node-RED setup before this integration existed,
and made the case for an **absolute** scale rather than one relative to what is
currently on screen: a colour has to mean the same thing every time you look, or
you never learn to read it.

The same value ships as an `intensity` attribute on each fire, so cards and
templates can filter or style by band without repeating the thresholds. It
describes **radiated power, not danger to you** — a small fire in the next
valley outranks a large one a hundred kilometres away, and FRP knows about
neither distance nor terrain.

### A fire keeps its entity while it drifts

A fire's id comes from the centroid of its merged detections, and that centroid
moves every refresh as satellites add and drop pixels. Cross one of the
invisible grid lines and the entity was destroyed and rebuilt under a new id:
history gone, and any automation or card pointing at the old entity id quietly
pointing at nothing. Nothing about it looked like a fault.

Each cycle is now matched against the previous one and a surviving fire hands
its id down. Fires close together keep their own ids — candidates are paired
nearest-first and no id is ever handed out twice.

Measured on live data before and after: a 220 m shift, which a single new
satellite pixel is enough to cause, would have renamed **2 of 9** fires in one
monitored area and **9 of 32** in a busier one.

### Two numbers that were wrong without looking wrong

- **The radius now stops at 500 km.** FIRMS returns at most 1000 detections per
  satellite, so a large enough area silently lost fires and every count dropped
  with it — the worst direction to be wrong in here, and the one a newcomer
  walks into, since "bigger radius" reads as "see more". Existing entries are
  untouched; if the ceiling is ever hit anyway, the hotspot sensor now says so
  through a `truncated` attribute instead of only mentioning it in the log.
- **Every fire now carries an `origin` attribute** naming the config entry it
  came from. All entries publish under the one `nasa_firms` map source, so a map
  card fed by `geo_location_sources` mixes them — and because a fire's state is
  its distance from *its own* origin, a fire from your other location showed a
  perfectly believable wrong number. The core map card still cannot filter, but
  a filtering card can, and the docs show how.

### The wind sentence in the example card

@pyspilf spotted that the card's wording did not match the geometry, and drew a
sketch to prove it: a fire ENE of him with the wind from the SSW was described
as pushing the smoke "sideways to your position" when 71% of the drift was
leaving. He was right. The wording is fixed, the raw angle is now printed
alongside it, and the brackets sit at the thirds of the half-circle — 60° and
120°, where the movement along the line to you is exactly half the wind speed.
"Towards you" therefore covers **more** cases than before, not fewer.

### Also in this release

- The README is down from 412 lines to 164. The recipes moved to
  [`docs/dashboard.md`](docs/dashboard.md) and
  [`docs/templates.md`](docs/templates.md), where they ship with the tag that
  produced them.
- `tests/smoke_test.py` grew coverage for the intensity bands, ignore zones and
  the id carry-over, including neighbour separation and collisions.

**Upgrade note.** Nothing to reconfigure, and no entity ids change. Two things
worth knowing:

1. **If you copied the dashboard card out of the README**, its wind line still
   carries the old wording and the old thresholds. Replace that one line with
   the version in [`docs/dashboard.md`](docs/dashboard.md).
2. Markers change appearance: coloured discs by intensity, with a dark flame
   instead of a white one, because white was unreadable on the amber band.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway, used under
CC BY 4.0.
