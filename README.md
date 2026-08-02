# Brazil 2026 Journal — Photo diary site

A scroll-driven static diary for the Brazil trip, built from the design-handoff prototype in `index.html` + `support.js`.
Serve it over HTTP so the JSON data and map load correctly:

```text
python -m http.server 8000
```

## Files

- `index.html` — the journal experience. The design/runtime stays inline here; it reads the trip payload from `data/trip.js` (a blocking `<script>` in `<head>`) so the very first paint already has data.
- `support.js` — the dc-runtime bundle from the handoff. Do not edit.
- `photo-review.html` / `.css` / `.js` — local-only browser review tool for tagging real exports (auto-loads previews, drag-and-drop reorder/section-assignment, Save button). The CSS/JS are loaded with a `?v=N` cache-busting query string in `photo-review.html` — **bump that number whenever you edit `.css`/`.js`**, or a browser tab left open from an earlier session can load a stale script against the new HTML and throw errors like "Cannot set properties of null".
- `review_server.py` — local dev server (serves this folder + a `POST /api/save-edits` route the review tool's Save button calls, which also rebuilds `data/trip.json`). Local-only, never published.
- `data/legs.json` — trip legs, palettes, stop-thumb defaults, and sequence order.
- `data/narrative.json` — species + placeholder narrative entries keyed by `subjectId`.
- `data/photo-catalog.json` — generated technical metadata for the private Lightroom export, including each photo's real capture `date` (ISO 8601 with UTC offset, e.g. `2026-07-13T07:44:49-03:00`) and `utcOffset` (e.g. `-03:00`), pulled from the EXIF `DateTimeOriginal`/`OffsetTimeOriginal` tags — not the Lightroom export timestamp.
- `data/photo-edits.json` — durable editorial overlay (the source of truth for captions/species/ordering/exclusions).
- `data/trip.json` — generated merged payload. The readable, diffable copy of what the site shows.
- `data/trip.js` — the same payload as `window.__TRIP__`, and the copy the site actually loads. Written by the same function in the same pass as `trip.json`, so the two can't drift; commit both.
- `scripts/build_photo_catalog.py` — rebuilds `data/photo-catalog.json` from `photos\`, and prints what changed against the catalog already at the output path (added / removed / re-keyed).
- `scripts/build_photo_assets.py` — creates public `assets\photos\*-card.avif`, `*-card.jpg` and `*-thumb.jpg` derivatives. Keeps existing files rather than re-encoding them. See "Photo quality" below.
- `scripts/build_trip_content.py` — merges legs, narrative, catalog, and edits into `data/trip.json` (skips any photo with `excluded: true`).
- `scripts/link_photos.py` — points a git worktree or fresh clone at the real `photos\` folder (see "Working from a worktree").
- `scripts/make_previews.py` — throwaway ~900px previews into `previews\`, for reading a batch of photos while writing captions (see "Writing captions for a new batch").
- `assets/photos/build-settings.json` — the encode settings the published derivatives were made with. Generated; commit it. Do not delete it — it is what stops the next build from re-encoding all of them.
- `photos\` — private raw export folder. Ignored by git; do not publish.
- `previews\` — scratch previews. Ignored by git; safe to delete any time.

## Working from a worktree

`photos\` is gitignored, so it exists only in the checkout it was put in (the OneDrive one).
Every build script needs it, so from a `git worktree` or a fresh clone, link it first:

```powershell
python scripts\link_photos.py
```

That finds the main working tree via `git worktree list` and creates a directory junction —
no disk cost, no administrator rights. `--source <path>` points somewhere else, `--copy` makes
a real copy instead, and `--force` replaces whatever is already there. Run in the main checkout
it just says there is nothing to do.

## Photo workflow

Rebuild the technical catalog after a fresh Lightroom export:

```powershell
python scripts\build_photo_catalog.py photos data\photo-catalog.json
```

It prints a diff against the catalog it is about to overwrite — added, removed, and re-keyed
photos — so you can see at a glance whether a re-export actually moved anything.

**Always follow it with `build_photo_assets.py`.** The catalog build writes every photo's `assets`
paths back as empty strings; it is `build_photo_assets.py` that fills them in. A catalog build on
its own leaves the catalog pointing at nothing, and the next `build_trip_content.py` run will
publish a payload with no images. The two are one step, not two.

### Sync conflicts and empty files

OneDrive drops conflict copies (`DSC00036-LAPTOP-73TG5O6M.jpg`) beside the real export. Normally
those are stale duplicates at the wrong size and the script skips them. But the failure also
arrives **inverted**: OneDrive can leave the *base* name as a 0-byte placeholder and put the real
bytes in the conflict copy. So the rule is:

- A conflict copy is skipped only when a **non-empty** base file exists.
- Otherwise it is *recovered* — used as the real export, but keyed to the **base** stem, so the
  photo id, the derivative filenames, and every `photo-edits.json` entry stay exactly where they
  were. Fixing OneDrive later changes nothing downstream.
- 0-byte files are never ingested. If one has no usable copy beside it the build **fails** rather
  than writing a catalog that is quietly missing a photo.

Both cases are reported. Renaming the recovered copies over their empty base files keeps the
folder tidy, but is not required for a correct build.

Photo ids are `<filename-slug>-<sha1(decoded pixels)[:10]>` — a hash of what the photo *looks
like*, not of the bytes it is stored in. Lightroom stamps a fresh export timestamp into every
file it writes, so hashing file bytes meant **a re-export changed every id even when nothing had
changed**: every derivative got a new filename, git stored a second full copy (~125 MB), and the
old ones stayed in history forever. Hashing decoded pixels means a re-export at unchanged settings
mints the *same* ids and git stores nothing new, while any real edit (exposure, crop, size,
quality) still moves the id so caches can't serve a stale image.

So a re-export normally needs **no** migration. You only need to re-key when ids actually move —
i.e. you changed a photo in Lightroom, or you changed the export size. The catalog build tells
you which case you are in: it prints `Re-keyed N — ... run migrate_photo_edits.py` when any
filename's id changed, and `No photos added, removed, or re-keyed.` when nothing did. Copy the
catalog aside *before* overwriting it if you expect a re-key, then join the two on filename:

```powershell
python scripts\migrate_photo_edits.py `
  data\photo-catalog.prev.json `
  data\photo-catalog.json `
  data\photo-edits.json
```

The script is idempotent, writes a `.bak`, and keeps (rather than drops) anything it can't match.

Generate the public card/thumb derivatives for the current export:

```powershell
python scripts\build_photo_assets.py photos data\photo-catalog.json assets\photos
```

**Derivatives that already exist are kept, never rebuilt.** A photo id is a hash of the decoded
pixels, so an existing `<id>-card.avif` is by definition the right picture — but the AVIF encoder
is not byte-reproducible, so re-encoding it produces a *different file with identical content*.
Committing that churn once cost ~92 MB of duplicate binaries in git history. The skip is what
makes a re-run of this script free, in both time and repo size.

The encode settings live in `assets\photos\build-settings.json`. Change `--card`, `--quality`,
`--fallback` or `--sharpen` and the script notices, says which knob moved, and rebuilds
everything — because then the output genuinely is different. `--force` rebuilds regardless.

Old derivatives are still **not** deleted automatically, but the script now lists any
`*-card.*` / `*-thumb.jpg` in the output folder that the catalog no longer references. Delete
those before committing. Files without an id-shaped name (`jaguar.jpg`, `cover.jpg`, …) are
hand-placed stock and must be kept, as is `build-settings.json`. Pruning matters: anything
committed stays in git history forever, and JPEG/AVIF are already compressed so git can't pack
them down — every stale copy costs its full size in every clone.

### Photo quality

The Lightroom export **is** the master — export at 3840px on the long edge, JPEG quality 100,
sRGB, and the script publishes from those pixels. 3840px is deliberate: the photo pane is 75% of
the viewport, so a maximised window on a 27" 4K monitor already wants ~2900px, and fullscreen with
the map collapsed wants the full 3840px. An intermediate JPEG costs nothing measurable — encoding
AVIF from the master versus from a q100 JPEG scores identically (42.29 dB PSNR either way).

Three derivatives are published per photo:

| File | Size | Encoding | Used for |
| --- | --- | --- | --- |
| `*-card.avif` | 3840px | AVIF q68, ICC preserved | the photo pane, on every browser that can decode AVIF |
| `*-card.jpg` | 2048px | JPEG q85, **4:4:4**, ICC preserved | fallback only, for browsers without AVIF |
| `*-thumb.jpg` | 360px | JPEG q88 | map dots, filmstrip, and the smart-fit colour probe |

AVIF q68 was chosen by measurement: against the masters it beat WebP q82 on *both* axes
(SSIM 0.9989 vs 0.9980, and fewer bytes), and beat JPEG q92 by ~2.5x on size at a difference
you can't see.

`index.html` picks the format at runtime by actually decoding a 1x1 AVIF data-URI — UA sniffing
and `canvas.toDataURL` both lie. It can **not** use the usual two-declaration CSS fallback:
`support.js`'s `cssToObj()` parses these style strings into an object, so a duplicate
`background-image` property is silently collapsed to the last one.

Rules for anyone touching `build_photo_assets.py`:

- When a source is already at or below `--card`, the JPEG card path is a **verbatim copy** of the
  export's compressed data. No re-encode, so no generation loss. Metadata (EXIF, GPS, XMP) is
  stripped at the JPEG marker level, which is lossless and keeps the ICC profile.
- When a source has to shrink, it is encoded with **4:4:4 chroma** and the ICC profile preserved,
  plus a `--sharpen` unsharp mask to replace the output sharpening a plain LANCZOS downscale loses.
- Never re-encode a card at the same pixel size "to save bytes" — that is pure quality loss with
  nothing bought. Lower `--card` instead, so the resize is real and the sharpening pass can
  compensate.
- Never remove the existing-output skip, and never make it depend on anything but the encode
  settings. The whole point is that an unchanged photo produces byte-identical output; the AVIF
  encoder does not, so the only way to get that is to not run it.
- Never point the map dots or the colour probe at a card. They render at 44px and 24px
  respectively; using the card pulls tens of MB for pixels nobody sees.

## Writing captions for a new batch

Judging subject, place and sequence across a batch means looking at every frame, and the
published cards (2048–3840px) are far too heavy to page through. Generate scratch previews:

```powershell
python scripts\make_previews.py photos previews `
  --catalog data\photo-catalog.json --uncaptioned data\photo-edits.json
```

`--uncaptioned` narrows it to photos with no `body` yet — i.e. exactly the new arrivals.
`--filter "Por Maycon*"` narrows by filename instead. With `--catalog`, previews are named
`<photo-id>.jpg`, so they map straight back to catalog and `photo-edits.json` entries. `previews\`
is gitignored and safe to delete at any time.

The catalog's `date`, `utcOffset`, `latitude`/`longitude` and `camera` fields do most of the
placement work before you look at a single pixel: clustering a batch by GPS and capture time
usually reconstructs the day's itinerary stop by stop, which is what `legId` and `order` should
follow.

Start the review server from this folder (not the plain `http.server` — this one also exposes the Save button's endpoint), then open `http://localhost:8000/photo-review.html`:

```powershell
python review_server.py
```

The review page loads every photo automatically — no folder picker needed, since `photos\` is already right here. Each card shows the photo's real capture date, time, and timezone (e.g. "Jul 13, 2026 · 7:44 AM · UTC-03:00"), read from the catalog's `date`/`utcOffset` fields — this is read-only context, not an editable field. Photos are grouped into sections for each destination (São Paulo, Amazon, Pantanal, Rio). For each photo, fill in:
- **Subject** (`title`) — a short headline, e.g. "The otter on the boulder"
- **Caption** (`body`) — a sentence or two of story/context
- **Species** — the animal's common name where known, e.g. "Neotropical Otter"
- **Narrative link** (`subjectId`, optional) — bind a frame to an entry in `data/narrative.json` (`jaguar`, `sp_01`, `closing`, etc.) to inherit its kicker/title/body
- **Latitude / Longitude** — pre-filled from EXIF GPS; edit if the GPS was wrong or missing
- **Feedback for next edit pass** — a private note-to-Copilot field, e.g. "wrong animal", "make this punchier". See "Feedback field workflow" below.

There is no **Location** field in the review page anymore (the new design drops the kicker line from photo pages — see `reference/` handoff in the design mockups). The underlying `kicker` key still exists in the data model for backward compatibility, but nothing writes to it going forward, and `build_trip_content.py` no longer invents a value for it — an untagged photo gets `""`, not the old `"Awaiting caption"` placeholder, which read like an unfinished-work flag on finished photos.

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

The final argument names the JSON output; `data\trip.js` is written alongside it automatically.

Then preview the site locally at `http://localhost:8000/index.html` (the review server above already serves it, or use plain `python -m http.server 8000`).

## Schema notes

- `subjectId` binds a real photo to an existing narrative slot from `data/narrative.json`, so a tagged frame can inherit the already-written kicker/title/body.
- `body` is the canonical long-caption field in Journal. The review tool and merge script also accept legacy `caption` values if they ever appear in imported edits.
- `featured` controls which real photo becomes a stop thumbnail when a leg has tagged real images. There is no checkbox for this in the review UI (removed for a cleaner card); set it directly in `data/photo-edits.json` or ask Copilot to flip it for a specific photo.
- `star` maps to the `★ TRIP STANDOUT` chip.
- `excluded` (set via the review tool's Exclude toggle) removes a photo from `trip.json` without deleting it from the catalog or overlay.
- `species` is a free-text common name (e.g. "Jaguar"); not yet surfaced on the public site, but carried through the merge pipeline for future use.
- `feedback` is a private note field the reviewer uses to leave instructions for the next editing pass (e.g. "wrong animal", "make punchier"). It is **never** read by `build_trip_content.py` and never appears on the site — see "Feedback field workflow" below.

## Feedback field workflow

The **Feedback for next edit pass** box on each photo card is how the reviewer hands off notes without writing finished prose themselves. When asked to "process feedback" or "apply my notes":

1. Read the full current `data/photo-edits.json` and find every photo with a non-empty `feedback` value.
2. For each one, look at its current `title`/`body` (and `species`, `subjectId`, the image itself, and surrounding sequence context if relevant) and rewrite `title`/`body` to address the note — following the editorial checklist below (always name the animal/plant in the visible text, keep the sequence coherent).
3. Clear the `feedback` value once it's been addressed (set it to `""`) so it doesn't get reprocessed or confused with a new note later.
4. Rebuild `data/trip.json`, commit, and push per "Publishing to GitHub Pages" below.

## Editorial checklist (read this before writing/reviewing captions)

- **Always put the animal/plant/insect's exact common name in the visible text itself** — in `kicker`, `title`, or `body`. The `species` field is captured and stored, but `build_trip_content.py` currently never reads it when building a real photo's slide, so it is **not** rendered anywhere on the live site. Setting `species` alone is not enough — the name must appear in the prose a reader actually sees.
- When given specific IDs/notes for individual photos (e.g. "1907 is a neotropical otter", "2014 is a yellow-spotted river turtle"), use the **exact** name given, not a generic stand-in ("the otter" / "a turtle"). Re-check every caption after a batch of notes — it's easy to update `species` but forget the prose still just says "the otter."
- After a request like "review all the captions and use these notes," re-read the *entire* `photo-edits.json` file first to see the current order/excluded state (order and exclusions may have changed since the captions were originally written), so the narrative sequence still reads correctly (e.g. don't call a photo "the finale" if an earlier excluded photo means it's now the leg's opening shot).
- **`order` is editorial, not chronological — don't "correct" it against capture dates.** The review page shows each photo's real capture time, which makes an out-of-sequence photo look like a mistake. It usually isn't. The Rio leg runs `IMG_2987` (the genuine Jul 20 morning arrival) and then `IMG_3099`, a Copacabana sunset shot on the **last** evening (Jul 21), ahead of the whole Jul 20 Maycon Nunes shoot — the pair reads as a scene-setting arrival even though the second frame is a day out of order. Before reordering anything by timestamp, assume the break is intentional and ask.
- **Keep Portuguese place and proper names properly accented** — São Paulo, Pão de Açúcar, Escadaria Selarón, Serra dos Órgãos, Rio-Niterói, Os Gêmeos. `legs.json` and `narrative.json` already carry the accents, so an unaccented caption reads as a typo right next to correctly-set chrome. Every file in `data\` is UTF-8 and both writers (`review_server.py` and `build_trip_content.py`) dump with `ensure_ascii=False`, so accented characters survive a save/rebuild round-trip intact — there is no encoding reason to strip them. English-language species names stay unaccented (`yacare caiman`, `jabiru`).

## After excluding a photo: check `data/legs.json` for orphaned sequence slots

Each leg in `data/legs.json` has a `sequence` array of `narrative.json` `subjectId`s that `build_trip_content.py` **guarantees** gets a slide. If you `Exclude` the only real, non-excluded photo bound to one of those `subjectId`s (via that photo's `subjectId` field), the build script doesn't just skip the slot — it falls back to the raw narrative entry instead:
- If that narrative subject has no `stockPhoto` (typical for `kind: "placeholder"` subjects like an arrival/city-hero shot), the live site shows a broken, literal empty "DROP IN — ..." placeholder box.
- If it does have a `stockPhoto` (typical for `kind: "species"` subjects), a generic, non-personal stock image is silently substituted in place of the excluded personal photo — which can also look duplicated if another unlinked real photo of the same animal still exists.

**Whenever you exclude (or re-include) a photo that has a `subjectId`**, check whether any other non-excluded photo is still bound to that same `subjectId`. If not, remove that `subjectId` from the relevant leg's `sequence` array in `legs.json` before rebuilding, so the slot is simply omitted instead of falling back to a placeholder/stock image.

## Publishing to GitHub Pages

Editing captions and rebuilding `data/trip.json` locally does **not** publish anything — GitHub Pages serves whatever is on `origin/main` of this repo (`evanmlew/brazil26`, the source for `https://evanmlew.github.io/brazil26/`). After any edit session:

```powershell
cd "C:\Users\evlew\OneDrive\Personal\1-Projects\Brazil 2026\Websites\Brazil 2026 Journal"
git status --short          # read this before staging; see the warning below
git add -A
git commit -m "Update captions/ordering"
git push origin main
```

**Stage everything, not just `data\`.** A caption-only session really does touch nothing but
`legs.json`, `photo-edits.json`, `trip.json` and `trip.js` — but a session that added photos also
produces `data\photo-catalog.json`, the new `assets\photos\*` derivatives, and
`assets\photos\build-settings.json`, and naming the four data files by hand silently leaves all of
those behind. The result is a `trip.json` on Pages referencing images that 404, plus a missing
settings file that makes the *next* asset build re-encode every derivative. `git status --short`
first is the check: everything listed should be `data\`, `assets\photos\`, or files you knowingly
edited — never `photos/` (gitignored) and never a modified (` M`) binary under `assets\photos\`,
which would mean the encode-skip did not do its job.

**If `git push` fails with a 403 "Permission denied"**, the environment's default GitHub CLI/credential-manager identity may be a different account (e.g. a corporate `evlew_microsoft` account) that lacks write access to the personal `evanmlew/brazil26` repo, even though `gh auth status` may show `evanmlew` already logged in via keyring. Fix by explicitly switching and pushing with that account's token for one command:

```powershell
$env:GH_TOKEN=""; $env:GITHUB_TOKEN=""
gh auth switch --user evanmlew
$token = gh auth token
git -c http.extraheader="AUTHORIZATION: basic $([Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token")))" push origin main
```

New shells default back to the corporate account automatically (it's set via a `GH_TOKEN` env var), so there's nothing to restore afterward.

After pushing, GitHub Pages typically takes 1-2 minutes to rebuild before the live site reflects the change.

Pages is configured to serve the **root of `main`** directly. The empty `.nojekyll` file at the repo
root turns Jekyll off for that build: this is a plain static site with nothing for Jekyll to compile,
and leaving it on only adds build time and the risk that Jekyll silently drops any path beginning
with `_`. Do not delete it.

Because Pages serves the repo root, everything committed here is publicly reachable — including the
local-only tooling (`review_server.py`, `photo-review.*`, `scripts\`, `data\photo-catalog.json`,
`data\photo-edits.json`). None of it is secret and none of it runs server-side on Pages, but "local
only" means "not part of the site", not "not downloadable".
