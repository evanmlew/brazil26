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
- `data/photo-catalog.json` — generated technical metadata for the private Lightroom export, including each photo's real capture `date` (ISO 8601 with UTC offset, e.g. `2026-07-13T07:44:49-03:00`) and `utcOffset` (e.g. `-03:00`), pulled from the EXIF `DateTimeOriginal`/`OffsetTimeOriginal` tags — not the Lightroom export timestamp.
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

The review page loads every photo automatically — no folder picker needed, since `photos\` is already right here. Each card shows the photo's real capture date, time, and timezone (e.g. "Jul 13, 2026 · 7:44 AM · UTC-03:00"), read from the catalog's `date`/`utcOffset` fields — this is read-only context, not an editable field. Photos are grouped into sections for each destination (São Paulo, Amazon, Pantanal, Rio). For each photo, fill in:
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

## Editorial checklist (read this before writing/reviewing captions)

- **Always put the animal/plant/insect's exact common name in the visible text itself** — in `kicker`, `title`, or `body`. The `species` field is captured and stored, but `build_trip_content.py` currently never reads it when building a real photo's slide, so it is **not** rendered anywhere on the live site. Setting `species` alone is not enough — the name must appear in the prose a reader actually sees.
- When given specific IDs/notes for individual photos (e.g. "1907 is a neotropical otter", "2014 is a yellow-spotted river turtle"), use the **exact** name given, not a generic stand-in ("the otter" / "a turtle"). Re-check every caption after a batch of notes — it's easy to update `species` but forget the prose still just says "the otter."
- After a request like "review all the captions and use these notes," re-read the *entire* `photo-edits.json` file first to see the current order/excluded state (order and exclusions may have changed since the captions were originally written), so the narrative sequence still reads correctly (e.g. don't call a photo "the finale" if an earlier excluded photo means it's now the leg's opening shot).

## After excluding a photo: check `data/legs.json` for orphaned sequence slots

Each leg in `data/legs.json` has a `sequence` array of `narrative.json` `subjectId`s that `build_trip_content.py` **guarantees** gets a slide. If you `Exclude` the only real, non-excluded photo bound to one of those `subjectId`s (via that photo's `subjectId` field), the build script doesn't just skip the slot — it falls back to the raw narrative entry instead:
- If that narrative subject has no `stockPhoto` (typical for `kind: "placeholder"` subjects like an arrival/city-hero shot), the live site shows a broken, literal empty "DROP IN — ..." placeholder box.
- If it does have a `stockPhoto` (typical for `kind: "species"` subjects), a generic, non-personal stock image is silently substituted in place of the excluded personal photo — which can also look duplicated if another unlinked real photo of the same animal still exists.

**Whenever you exclude (or re-include) a photo that has a `subjectId`**, check whether any other non-excluded photo is still bound to that same `subjectId`. If not, remove that `subjectId` from the relevant leg's `sequence` array in `legs.json` before rebuilding, so the slot is simply omitted instead of falling back to a placeholder/stock image.

## Publishing to GitHub Pages

Editing captions and rebuilding `data/trip.json` locally does **not** publish anything — GitHub Pages serves whatever is on `origin/main` of this repo (`evanmlew/brazil26`, the source for `https://evanmlew.github.io/brazil26/`). After any edit session:

```powershell
cd "C:\Users\evlew\OneDrive\Personal\1-Projects\Brazil 2026\Websites\Brazil 2026 Journal"
git add data/legs.json data/photo-edits.json data/trip.json
git commit -m "Update captions/ordering"
git push origin main
```

**If `git push` fails with a 403 "Permission denied"**, the environment's default GitHub CLI/credential-manager identity may be a different account (e.g. a corporate `evlew_microsoft` account) that lacks write access to the personal `evanmlew/brazil26` repo, even though `gh auth status` may show `evanmlew` already logged in via keyring. Fix by explicitly switching and pushing with that account's token for one command:

```powershell
$env:GH_TOKEN=""; $env:GITHUB_TOKEN=""
gh auth switch --user evanmlew
$token = gh auth token
git -c http.extraheader="AUTHORIZATION: basic $([Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token")))" push origin main
```

New shells default back to the corporate account automatically (it's set via a `GH_TOKEN` env var), so there's nothing to restore afterward.

After pushing, GitHub Pages typically takes 1-2 minutes to rebuild before the live site reflects the change.
