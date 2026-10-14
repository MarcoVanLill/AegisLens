# Item catalog data attribution

`src/dota_advisor/data/item_catalog.json` is a transformed snapshot of the structured item records used by the [Dota 2 Wiki Items page on Fandom](https://dota2.fandom.com/wiki/Items).

- Retrieved: 2026-10-14
- Source API: `https://dota2.fandom.com/api.php?action=cargoquery`
- Source table: `items`
- Source filter: records whose `game` field is null or `Dota 2 Hidden`
- Fields retained: item name, listed cost, category, source page
- Transformations: records are sorted and deduplicated by name; purchasability is derived from the source category; no article prose or images are included

Fandom states that community text is generally available under the [Creative Commons Attribution-ShareAlike 3.0 Unported license](https://creativecommons.org/licenses/by-sa/3.0/) unless otherwise noted. The transformed catalog snapshot is redistributed under those terms. Source authorship is attributed through the source-page link above and each record's `page` field.

The snapshot is provided for inventory-name recognition. It does not assert that every record is enabled in the latest Dota 2 patch, and it does not make unreviewed records eligible for advisor recommendations.

Dota 2 and its item names are property of Valve Corporation. This project is not affiliated with or endorsed by Valve. No Fandom or Valve images are included in the snapshot.

