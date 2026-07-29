# v0.5.1

Text for the GitHub release.

## Release body

### The alert said km even when it meant miles

The *Nearest hotspot* sensor is a distance sensor, so Home Assistant shows it in
your unit system — kilometres on a metric instance, **miles on a US one** — and
Settings → Entities can override that per entity. The blueprint and the recipes
printed `km` regardless, so on a US instance the notification put the wrong
label on a right number, and the alert distance you typed was read as miles
while the field said km.

Everything that prints the distance now takes the unit from the entity. Nothing
about the integration itself changed: same entities, same attributes, same
values.

**If you already imported the blueprint, re-import it.** A blueprint is copied
into your configuration when you import it, so an existing copy keeps the old
text. In Settings → Automations → Blueprints, the blueprint's overflow menu has
*Re-import blueprint*. Your automations keep working either way — the fix is in
what the message says, not in when it fires.

**One thing that cannot follow your unit system:** the fires on the map. Their
state is in kilometres on every instance, because `geo_location` entities have
no unit conversion in Home Assistant. The README says so now, next to the entity
table.

### Also

Thanks to RedKing in the community thread for the question that turned this up.

Fire data courtesy of NASA FIRMS. Wind data from MET Norway, used under
CC BY 4.0.
