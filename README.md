# Brazil 2026 Journal — Photo diary site

A scroll-driven static diary for the Brazil trip, built from the design-handoff prototype in `index.html` + `support.js`.
Serve it over HTTP so the JSON data and map load correctly:

```text
python -m http.server 8000
```

## Files

- `index.html` — the journal experience. The design/runtime stays inline here; it now fetches `data/trip.json` first and falls back to the embedded mockup data if the JSON is missing.
- `support.js` — the dc-runtime bundle from the handoff. Do not edit.
- `photo-review.html` — local-only browser review tool for tagging real exports.
- `data/legs.json` — trip legs, palettes, stop-thumb defaults, and sequence order.
- `data/narrative.json` — species + placeholder narrative entries keyed by `subjectId`.
- `data/photo-catalog.json` — generated technical metadata for the private Lightroom export.
- `data/photo-edits.json` — durable editorial overlay (kept sparse; empty by default).
- `data/trip.json` — generated merged payload consumed by the site.
- `scripts/build_photo_catalog.py` — rebuilds `data/photo-catalog.json` from `photos\`.
- `scripts/build_photo_assets.py` — creates public `assets\photos\*-card.jpg` and `*-thumb.jpg` derivatives.
- `scripts/build_trip_content.py` — merges legs, narrative, catalog, and edits into `data/trip.json`.
- `photos\` — private raw export folder. Ignored by git; do not publish.

## Photo workflow

Rebuild the technical catalog after a fresh Lightroom export:

```powershell
python scripts\build_photo_catalog.py photos data\photo-catalog.json
```

Generate the public card/thumb derivatives for the current export:

```powershell
python scripts\build_photo_assets.py photos data\photo-catalog.json assets\photos
```

Start the local server from this folder, then open `http://localhost:8000/photo-review.html`:

```powershell
python -m http.server 8000
```

In the review page:
- choose the `photos\` folder,
- set `legId` from the dropdown,
- optionally bind a frame to a narrative entry with `subjectId` (`jaguar`, `sp_01`, `closing`, etc.),
- add any per-photo overrides (`kicker`, `title`, `body`, `chips`, `featured`, `star`, etc.),
- use the up/down buttons to write per-leg `order`,
- download `photo-edits.json`, then replace `data\photo-edits.json` with it.

Rebuild the merged trip payload after catalog or edit changes:

```powershell
python scripts\build_trip_content.py `
  data\legs.json `
  data\narrative.json `
  data\photo-catalog.json `
  data\photo-edits.json `
  data\trip.json
```

Then preview the site locally:

```powershell
python -m http.server 8000
```

Open `http://localhost:8000/index.html`.

## Schema notes

- `subjectId` binds a real photo to an existing narrative slot from `data/narrative.json`, so a tagged frame can inherit the already-written kicker/title/body.
- `body` is the canonical long-caption field in Journal. The review tool and merge script also accept legacy `caption` values if they ever appear in imported edits.
- `featured` controls which real photo becomes a stop thumbnail when a leg has tagged real images.
- `star` maps to the `★ TRIP STANDOUT` chip.
