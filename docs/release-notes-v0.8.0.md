# v0.8.0 — putting a name to the place

Text for the GitHub release.

## Release body

A fire used to arrive as `43.61/3.93`. Now it arrives near Montpellier.

Every fire entity gains two attributes:

| Attribute | Meaning |
|---|---|
| `place_name` | The nearest populated place, in its own language |
| `place_distance_km` | How far that place is **from the fire** — always kilometres |

So a notification can read *"fire 18 km away, near Saint-Martin-de-Londres"*
instead of a pair of coordinates.
[The recipes](docs/templates.md#name-the-place-a-fire-is-near) cover the
plain version, the miles version, and how to say "in open country" when the
nearest town is genuinely far off.

### No geocoding service is involved

The obvious way to do this is to call a reverse-geocoding API, and every
candidate ruled itself out on its own terms. The public Nominatim service
counts the traffic of *all* users of an application against a single limit and
discourages periodic requests outright — one block, matched on the identity
every installation shares, would take the feature away from everyone at once.
BigDataCloud's key-less endpoint is licensed for browsers, not servers.
GeoNames' web service wants an account per user.

So the data ships with the integration instead: the GeoNames `cities1000`
extract, 170,607 populated places across 246 countries, trimmed to about 2 MB.
Lookups happen locally against that file.

- No API key, no account, no rate limit, nothing to configure.
- It still works when a fire has taken your internet connection down — which
  is the moment it matters most.
- About 6 MB of memory, once, shared by all your config entries.

### What it will and will not tell you

The nearest **listed town**, never a street address. Where people live that is
usually a few kilometres. In the Australian outback the honest answer is
"Yulara, 12 km"; in boreal Canada it can be 85. `place_distance_km` is what
tells the two apart, and a large number there means remote, not wrong.

### Upgrade notes

1. Nothing to configure and nothing to turn on — the attributes are simply
   there after the update.
2. The download is ~2 MB larger, and Home Assistant uses ~6 MB more memory
   once the dataset is first read (shared across entries, not per entry).
3. `place_distance_km` stays kilometres on every instance. Home Assistant
   converts sensor *states* to your unit system but never attributes, so the
   unit is fixed in the name rather than silently changing meaning — the
   miles one-liner is in the recipes.
4. Nothing is removed or renamed; existing cards, templates, automations and
   the blueprint keep working.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway and place names
from GeoNames, both used under CC BY 4.0.
