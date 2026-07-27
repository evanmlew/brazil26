# Brazil 2026 Journal — Photo diary site

A scroll-driven static diary for the Brazil trip, built from the design-handoff prototype in `index.html` + `support.js`.
Serve it over HTTP so the JSON data and map load correctly:

```text
python -m http.server 8000
```

## Files

- `index.html` — the journal experience. The design/runtime stays inline here; it now fetches `data/trip.json` first and falls back to the embedded mockup data if the JSON is missing.
- `support.js` — the dc-runtime bundle from the handoff. Do not edit.
- `photo-review.html` / `.css` / `.js` — local-only browser review tool for tagging real exports (auto-loads previews, drag-and-drop reorder/section-assignment, Save button).
- `review_server.py` — local dev server (serves this folder + a `POST /api/save-edits` route the review tool's Save button calls, which also rebuilds `data/trip.json`). Local-only, never published.
- `data/legs.json` — trip legs, palettes, stop-thumb defaults, and sequence order.
- `data/narrative.json` — species + placeholder narrative entries keyed by `subjectId`.
- `data/photo-catalog.json` — generated technical metadata for the private Lightroom export.
- `data/photo-edits.json` — durable editorial overlay (the source of truth for captions/species/ordering/exclusions).
- `data/trip.json` — generated merged payload consumed by the site.
- `scripts/build_photo_catalog.py` — rebuilds `data/photo-catalog.json` from `photos\`.
- `scripts/build_photo_assets.py` — creates public `assets\photos\*-card.jpg` and `*-thumb.jpg` derivatives.
- `scripts/build_trip_content.py` — merges legs, narrative, catalog, and edits into `data/trip.json` (skips any photo with `excluded: true`).
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

Start the review server from this folder (not the plain `http.server` — this one also exposes the Save button's endpoint), then open `http://localhost:8000/photo-review.html`:

```powershell
python review_server.py
```

The review page loads every photo automatically — no folder picker needed, since `photos\` is already right here. Photos are grouped into sections for each destination (São Paulo, Amazon, Pantanal, Rio). For each photo, fill in:
- **Location** (`kicker`) — the place name, e.g. "Clearwater river"
- **Subject** (`title`) — a short headline, e.g. "The otter on the boulder"
- **Caption** (`body`) — a sentence or two of story/context
- **Species** — the animal's common name where known, e.g. "Neotropical Otter"
- **Narrative link** (`subjectId`, optional) — bind a frame to an entry in `data/narrative.json` (`jaguar`, `sp_01`, `closing`, etc.) to inherit its kicker/title/body
- **Latitude / Longitude** — pre-filled from EXIF GPS; edit if the GPS was wrong or missing

Drag a photo to reorder it within a section, or drag it into a different section to reassign its destination — a placeholder shows exactly where it will land. Use **Exclude from site** on any photo you don't want published; it stays in the catalog but `build_trip_content.py` leaves it out of `trip.json`. Click **Save** to write straight to `data\photo-edits.json` (a `.bak` backup of the previous version is kept automatically) **and immediately rebuild `data\trip.json`**, so reloading the journal at `http://localhost:8000/index.html` shows the change right away — no separate build step needed. **Download backup** / **Import edits** are the manual fallback if you're not running the server.

Rebuild the merged trip payload after catalog or edit changes:

```powershell
python scripts\build_trip_content.py `
  data\legs.json `
  data\narrative.json `
  data\photo-catalog.json `
  data\photo-edits.json `
  data\trip.json
```

Then preview the site locally at `http://localhost:8000/index.html` (the review server above already serves it, or use plain `python -m http.server 8000`).

## Schema notes

- `subjectId` binds a real photo to an existing narrative slot from `data/narrative.json`, so a tagged frame can inherit the already-written kicker/title/body.
- `body` is the canonical long-caption field in Journal. The review tool and merge script also accept legacy `caption` values if they ever appear in imported edits.
- `featured` controls which real photo becomes a stop thumbnail when a leg has tagged real images.
- `star` maps to the `★ TRIP STANDOUT` chip.
- `excluded` (set via the review tool's Exclude toggle) removes a photo from `trip.json` without deleting it from the catalog or overlay.
- `species` is a free-text common name (e.g. "Jaguar"); not yet surfaced on the public site, but carried through the merge pipeline for future use.
