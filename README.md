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

**A worktree is on its own branch, so nothing you do there is live.** The review tool saves to the
worktree's `data\photo-edits.json` and rebuilds that worktree's `trip.json`/`trip.js`, which looks
identical to editing in the main checkout — but Pages serves `main`, so the site keeps showing the
old captions until the branch is merged and pushed. Assume a review session in a worktree is
unpublished until you have run the merge in "Publishing from a worktree branch" below.

Also: only ever have **one** review server running. `review_server.py` serves whatever folder it was
started in, and two checkouts of this repo look the same in a browser. If the tool seems to be
"losing" edits, check which path the running server was launched from before assuming a bug — the
saves are probably landing correctly, just in the other checkout.

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
- **Narrative link** (`subjectId`, optional) — bind a frame to an entry in `data/narrative.json` (`jaguar`, `sp_01`, `closing`, etc.) to inherit its already-written title/body
- **Note to the assistant** — a private note-to-Copilot field, e.g. "wrong animal", "make this punchier". Enter queues it; it is also flushed on save. See "Note thread workflow" below.

**Latitude / longitude are read-only.** Each photo shows its EXIF fix (or `NO GPS`) as context for writing the caption — there is no editable coordinate field and nothing writes coordinates back, so a wrong or missing fix has to be fixed in Lightroom and re-exported.

A photo whose text differs from what was last saved is marked with a pencil on its thumbnail, so a half-finished pass is visible at a glance. **Reordering is deliberately not counted** — dragging one photo renumbers every frame after it, which would pencil the whole leg. So a pure reorder shows "unsaved edits" in the header with no pencils anywhere; that is correct, not a bug.

There is no **Location** field in the review page, and the `kicker` line it fed is gone from the data model entirely — `build_trip_content.py` no longer emits one and no `kicker` key survives in `trip.json`. (Historically an untagged photo got `"Awaiting caption"`, which read like an unfinished-work flag on finished photos.)

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

- `subjectId` binds a real photo to an existing narrative slot from `data/narrative.json`, so a tagged frame can inherit the already-written title/body.
- `body` is the canonical long-caption field in Journal. The review tool and merge script also accept legacy `caption` values if they ever appear in imported edits.
- `featured` controls which real photo becomes a stop thumbnail when a leg has tagged real images. There is no checkbox for this in the review UI (removed for a cleaner card); set it directly in `data/photo-edits.json` or ask Copilot to flip it for a specific photo.
- `star` is carried through the merge pipeline but has no visual treatment on the photo page — it used to render a `★ TRIP STANDOUT` chip, which the current design drops (the caption pill is species-only now).
- `excluded` (set via the review tool's Exclude toggle) removes a photo from `trip.json` without deleting it from the catalog or overlay.
- `species` is a free-text common name (e.g. "Jaguar"). It is the **only** thing the caption pill renders: a photo with a species gets one pill showing that name uppercased, and a photo without one gets no pill at all. It also drives the wildlife gallery grouping and the map pin label.
- `notes` is a private conversation thread the reviewer uses to leave instructions for the next editing pass (e.g. "wrong animal", "make punchier"). It is **never** read by `build_trip_content.py` and never appears on the site — see "Note thread workflow" below. It replaced an earlier single-string `feedback` field; nothing reads `feedback` any more.
- `pending` marks a caption the assistant has rewritten but the reviewer hasn't accepted — see below.

## Note thread workflow

The **note to the assistant** box on each photo is how the reviewer hands off instructions without writing finished prose themselves. Notes accumulate as a thread on the photo:

```json
"notes": [{ "who": "YOU", "text": "make the text shorter", "at": "2026-08-03T05:38:53.905Z" }]
```

`who` is `"YOU"` for the reviewer and `"ASSISTANT"` for a reply written back into the file. A thread whose last entry is `"YOU"` is unanswered, and the tool badges it as such — which is also the cheapest way to find the work: **every photo whose last note is from `YOU` is a photo waiting on you.**

When asked to "process my notes" or "apply my feedback":

1. Read the **whole** current `data/photo-edits.json`, not just the noted photos. Order and exclusions may have moved since the captions were written, and a note like "this repeats the last one" only makes sense in sequence context.
2. For each unanswered thread, look at the photo's current `title`/`body`, its `species`/`subjectId`, the image itself, and its neighbours in `order`, then write new copy following the editorial checklist below.
3. **Propose, don't overwrite.** Put the new copy straight into `title`/`body`, and record what it replaced so the reviewer can undo it:

   ```json
   "pending": { "was": "<old body>", "wasTitle": "<old title>", "why": "shortened per your note", "at": "<ISO>" }
   ```

   The tool then shows "Assistant rewrote this — … Not accepted yet" with Accept (clears `pending`) and Revert (restores `was`/`wasTitle`).
4. Append your reply to the thread as a `"who": "ASSISTANT"` entry — the reasoning, and any alternatives you considered but didn't pick. That is what makes the next round quick.
5. Rebuild `data/trip.json`, commit, and push per "Publishing to GitHub Pages" below.

Two traps in this loop, both of which have already caused real cleanup:

- **Bump `rev` whenever you edit `data/photo-edits.json` by hand.** `review_server.py` enforces optimistic concurrency: the page posts the `rev` it loaded, and a mismatch is rejected with a 409 so the reviewer reloads instead of silently clobbering. Edit the file without bumping `rev` and a browser tab still open at the same number will save straight over your work the next time the reviewer touches anything. Bumping it is what forces the reload. It also means **a `photo-edits.json` you read a while ago may be stale** — re-read before drawing conclusions about what the reviewer did or didn't save.
- **Editing a caption by hand does not clear its `pending` flag.** If the reviewer rewrites your proposal themselves instead of clicking Accept, the photo keeps showing "Assistant rewrote this — not accepted yet" over their own text, forever. When processing a round of notes, check for `pending` records whose `title`/`body` no longer match anything you proposed and clear them.

## Editorial checklist (read this before writing/reviewing captions)

- **Always put the animal/plant/insect's exact common name in the visible text itself** — in `title` or `body`. `species` now renders as the caption pill, but a pill is a label, not prose: it sits below the caption in 9px uppercase and a reader skimming the paragraph will miss it. Setting `species` alone is not enough — the name must also appear in the sentence a reader actually reads.
- When given specific IDs/notes for individual photos (e.g. "1907 is a neotropical otter", "2014 is a yellow-spotted river turtle"), use the **exact** name given, not a generic stand-in ("the otter" / "a turtle"). Re-check every caption after a batch of notes — it's easy to update `species` but forget the prose still just says "the otter."
- After a request like "review all the captions and use these notes," re-read the *entire* `photo-edits.json` file first to see the current order/excluded state (order and exclusions may have changed since the captions were originally written), so the narrative sequence still reads correctly (e.g. don't call a photo "the finale" if an earlier excluded photo means it's now the leg's opening shot).
- **`order` is editorial, not chronological — don't "correct" it against capture dates.** The review page shows each photo's real capture time, which makes an out-of-sequence photo look like a mistake. It usually isn't. The Rio leg runs `IMG_2987` (the genuine Jul 20 morning arrival) and then `IMG_3099`, a Copacabana sunset shot on the **last** evening (Jul 21), ahead of the whole Jul 20 Maycon Nunes shoot — the pair reads as a scene-setting arrival even though the second frame is a day out of order. Before reordering anything by timestamp, assume the break is intentional and ask.
- **Keep Portuguese place and proper names properly accented** — São Paulo, Pão de Açúcar, Escadaria Selarón, Serra dos Órgãos, Rio-Niterói, Os Gêmeos. `legs.json` and `narrative.json` already carry the accents, so an unaccented caption reads as a typo right next to correctly-set chrome. Every file in `data\` is UTF-8 and both writers (`review_server.py` and `build_trip_content.py`) dump with `ensure_ascii=False`, so accented characters survive a save/rebuild round-trip intact — there is no encoding reason to strip them. English-language species names stay unaccented (`yacare caiman`, `jabiru`).
- **Read consecutive captions as a run, not one at a time.** Rewriting frames individually reliably produces neighbours that state the same fact twice — two Selarón captions both explaining that the tiles came from donors worldwide. Whichever frame states a fact first owns it; the next one has to add something new or say less.
- **Don't attribute a viewpoint or mechanism the EXIF contradicts.** A caption once read "through the branches from the cable car" for a frame the GPS puts at the Mirante Dona Marta lookout, an hour and 4 km from the actual cable-car frames — and Corcovado is reached by cog railway, not cable car, so the sentence was wrong twice over. Coordinates and capture time are right there on the card: check them before writing *how* a shot was taken, and don't name a landmark's access method unless you know it.

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

### Publishing from a worktree branch

A review session run in a `git worktree` commits to that worktree's own branch, which Pages never
serves. Getting it live means merging to `main` — and the one thing that will actually bite you is
that **`main` moves independently while the branch is open.** A photo swap on `main` (say
"Replace Rio photo 313 with 315", which deletes 313's derivatives and adds 315's) is, from the
branch's point of view, just files it still has. Merge blind and git happily reinstates the retired
photo and its assets, because the branch never deleted them. Nothing errors; the site just quietly
regains a frame you removed weeks ago.

So always look at what `main` gained before merging anything into it:

```powershell
git fetch origin main
git --no-pager log --oneline HEAD..origin/main    # commits main has that you don't
git --no-pager diff --stat HEAD...origin/main     # three dots: changes since the fork point
```

If `HEAD..origin/main` is empty the branch is current and the merge is a plain fast-forward. If it
isn't, read those commits before going further, and treat **any** change to
`data\photo-catalog.json` or `assets\photos\` on `main` as a photo add/removal/swap that a careless
merge will undo. Then merge `main` into the branch (not the other way round) so conflicts are
resolved in the worktree rather than in the live checkout:

```powershell
git merge origin/main
```

Two rules for the conflicts:

- **`data\photo-edits.json` is resolved by hand.** It is keyed by photo id, so a photo swap on
  `main` means your branch's edits sit under the *old* id. Move the record onto the new key — keep
  your title/body/order/exclusion, drop the retired id — rather than accepting either side whole.
- **`data\trip.json` and `data\trip.js` are never merged, they are rebuilt.** They are generated
  output; a three-way merge of them produces a payload that matches neither side's sources. Take
  either version to close the conflict, then regenerate from the resolved inputs:

  ```powershell
  python scripts\build_trip_content.py data\legs.json data\narrative.json data\photo-catalog.json data\photo-edits.json data\trip.json
  ```

Verify before publishing — the point of the exercise is the photo set, so check it directly: the
expected number of published slides per leg, the new photo id present, the retired one gone from
`trip.json` *and* from `assets\photos\`. Then commit the merge and push, confirming it is a
fast-forward first so you can never rewrite anyone's `main`:

```powershell
git push origin HEAD                                  # the branch, as a backup
git merge-base --is-ancestor origin/main HEAD; $?     # must print True
git push origin HEAD:main
```

Pushing `HEAD:main` from the worktree is deliberate: it publishes without touching, or needing to
switch branches in, the OneDrive checkout — which is also where the un-gitignored `photos\` folder
lives and is the last place you want a surprise checkout happening.

**If `git push` fails with a 403 "Permission denied"**, the environment's default GitHub CLI/credential-manager identity may be a different account (e.g. a corporate `evlew_microsoft` account) that lacks write access to the personal `evanmlew/brazil26` repo, even though `gh auth status` may show `evanmlew` already logged in via keyring. Fix by explicitly switching and pushing with that account's token for one command:

```powershell
$env:GH_TOKEN=""; $env:GITHUB_TOKEN=""
gh auth switch --user evanmlew
$token = gh auth token
git -c http.extraheader="AUTHORIZATION: basic $([Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token")))" push origin main
```

`gh auth switch` **on its own is not enough**, and clearing the env vars on its own is not either.
Git asks its configured credential helpers in order, and Git Credential Manager sits ahead of the
`gh` helper, so it answers with the cached corporate identity before `gh` is ever consulted — the
push still 403s from an account you just switched away from. The command above sidesteps helpers
entirely by supplying the header itself. The alternative is to reset the helper list for one
command so only `gh` can answer, which keeps the token off the command line:

```powershell
$env:GH_TOKEN=""; $env:GITHUB_TOKEN=""
git -c credential.helper= -c "credential.helper=!'C:\Users\evlew\AppData\Local\copilot-desktop-gh-2.96.0\gh.exe' auth git-credential" push origin HEAD:main
```

The empty `-c credential.helper=` is the load-bearing part: it clears the inherited list, and the
second `-c` then installs `gh` as the only helper. (Adjust the `gh.exe` path — `(Get-Command gh).Source` — if the CLI version in the path has moved on.)

New shells default back to the corporate account automatically (it's set via a `GH_TOKEN` env var), so there's nothing to restore afterward.

After pushing, GitHub Pages typically takes 1-2 minutes to rebuild before the live site reflects the change. Don't verify by polling `gh api repos/evanmlew/brazil26/pages/builds/latest` alone — on this repo's legacy Pages source it can keep reporting the *previous* commit as the latest build well after the new one is live, which reads like a failed deploy. Check the payload the site actually serves instead, with a cache-buster:

```powershell
(Invoke-WebRequest "https://evanmlew.github.io/brazil26/data/trip.json?cb=$(Get-Random)" -UseBasicParsing).Content -match "some new caption text"
```

Pages is configured to serve the **root of `main`** directly. The empty `.nojekyll` file at the repo
root turns Jekyll off for that build: this is a plain static site with nothing for Jekyll to compile,
and leaving it on only adds build time and the risk that Jekyll silently drops any path beginning
with `_`. Do not delete it.

Because Pages serves the repo root, everything committed here is publicly reachable — including the
local-only tooling (`review_server.py`, `photo-review.*`, `scripts\`, `data\photo-catalog.json`,
`data\photo-edits.json`). None of it is secret and none of it runs server-side on Pages, but "local
only" means "not part of the site", not "not downloadable".
