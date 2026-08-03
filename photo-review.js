/* brazil26 review tool — dense list + contact sheet.
   Vanilla DOM, no framework, no build step. Loaded directly by photo-review.html.

   Rendering model: render() rebuilds the list/sheet/bottom panel and is called for
   every structural change (select, filter, leg, drag, exclude, accept, note).
   Typing in a field goes through patchQuiet(), which mutates state and refreshes
   only the chrome — never the node the caret is sitting in. */

const AMBER = "#f0a832";
const CYAN = "#4fd0e0";
const ZOOMS = [72, 96, 128, 172, 232];
const UNSORTED = { id: "", name: "Unsorted", dates: "", region: "", lodge: "", nights: 0 };

// Keys this UI owns on an edit record. Everything else on the record (featured,
// star, chips, …) is carried through untouched so the tool never silently drops
// a field the site consumes.
const OWNED = ["legId", "order", "title", "body", "species", "subjectId", "locationName", "excluded", "notes", "pending"];

const state = {
  photos: [],
  legs: [],
  taxonColors: {},
  speciesTaxon: {},   // lowercase common name -> taxon, from narrative.json
  view: "list",
  leg: null,
  selId: null,
  filter: "all",
  tab: "recos",
  rev: 0,
  dirty: 0,
  log: [],
  dismissed: [],
  dragId: null,
  overId: null,
  zoom: 1,
  paneW: 352,
  err: "",
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

/* ------------------------------------------------------------------ load -- */

async function load() {
  const [catalog, edits, legs, narrative] = await Promise.all([
    getJson("data/photo-catalog.json", true),
    getJson("data/photo-edits.json", false),
    getJson("data/legs.json", false),
    getJson("data/narrative.json", false),
  ]);

  state.legs = (legs && legs.legs) || [];
  state.taxonColors = (legs && legs.taxonColors) || {};
  state.rev = (edits && Number(edits.rev)) || 0;

  const subjects = (narrative && narrative.subjects) || {};
  Object.values(subjects).forEach((s) => {
    if (s && s.common && s.taxon) state.speciesTaxon[String(s.common).toLowerCase()] = s.taxon;
  });

  const editRecords = (edits && edits.photos) || {};
  state.photos = (catalog.photos || []).map((p) => {
    const raw = { ...(editRecords[p.id] || {}) };
    if (raw.caption && !raw.body) raw.body = raw.caption;   // legacy alias
    delete raw.caption;
    const rest = { ...raw };
    OWNED.forEach((k) => delete rest[k]);
    return {
      id: p.id,
      filename: p.filename,
      date: p.date || "",
      utcOffset: p.utcOffset || "",
      lat: numberOrNull(raw.latitude ?? p.latitude),
      lng: numberOrNull(raw.longitude ?? p.longitude),
      // Build-time data-quality marker from build_photo_catalog.py. Coordinates
      // are read-only here, so surface it rather than letting it pass silently.
      noGps: (p.flags || []).includes("no-gps"),
      thumb: (p.assets && p.assets.thumb) || "",
      card: (p.assets && (p.assets.cardAvif || p.assets.card)) || "",
      legId: raw.legId || p.legId || "",
      order: typeof raw.order === "number" ? raw.order : Number.MAX_SAFE_INTEGER,
      title: raw.title || p.title || "",
      body: raw.body || p.body || "",
      species: raw.species || p.species || "",
      subjectId: raw.subjectId || p.subjectId || "",
      locationName: raw.locationName || p.locationName || "",
      excluded: Boolean(raw.excluded),
      notes: Array.isArray(raw.notes) ? raw.notes.map((n) => ({ ...n })) : [],
      pending: raw.pending ? { ...raw.pending } : null,
      rest,
    };
  });
  state.photos.sort((a, b) => a.order - b.order || a.filename.localeCompare(b.filename));
  state.photos.forEach((p) => { if (p.order === Number.MAX_SAFE_INTEGER) p.order = 0; });
  legOrder().forEach((leg) => legPhotos(leg.id).forEach((p, i) => { p.order = i; }));

  state.leg = (legOrder()[0] || UNSORTED).id;
  render();
}

async function getJson(url, required) {
  // Local tool against files that change underneath it (an external edit, or the
  // rebuild this server runs on save) — never serve these from the HTTP cache.
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    if (required) throw new Error(`Could not load ${url} (${res.status})`);
    return null;
  }
  return res.json();
}

const numberOrNull = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/* --------------------------------------------------------------- helpers -- */

// Photos whose legId is not a known leg fall into a synthetic Unsorted bucket
// rather than vanishing — that is where a fresh camera import lands.
function bucketOf(photo) {
  return state.legs.some((l) => l.id === photo.legId) ? photo.legId : UNSORTED.id;
}

function legOrder() {
  const rows = [...state.legs];
  if (state.photos.some((p) => bucketOf(p) === UNSORTED.id)) rows.push(UNSORTED);
  return rows;
}

const legPhotos = (legId) => state.photos.filter((p) => bucketOf(p) === legId);
const legDef = (legId) => legOrder().find((l) => l.id === legId) || UNSORTED;
const photoById = (id) => state.photos.find((p) => p.id === id) || null;
const selected = () => photoById(state.selId);
const needsYou = (p) => !p.excluded && (!p.title || !p.body);

function stamp() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function noteTime(at) {
  if (!at) return "";
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return String(at);
  // Notes are stored as UTC ISO strings; render them in local time so they line
  // up with the run log's timestamps.
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

function toks(s) {
  return String(s || "").split(/\s+/).filter(Boolean)
    .map((raw) => ({ raw, w: raw.toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, "") }))
    .filter((t) => t.w);
}

function shingles(s, n) {
  const t = toks(s);
  const out = new Map();
  for (let i = 0; i + n <= t.length; i++) out.set(t.slice(i, i + n).map((x) => x.w).join(" "), i);
  return out;
}

function quoteShingle(s, n, key) {
  const t = toks(s);
  const i = shingles(s, n).get(key);
  if (i == null) return key;
  return t.slice(i, i + n).map((x) => x.raw).join(" ").replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
}

const sentences = (s) => String(s || "").split(/(?<=[.!?])\s+/).filter(Boolean);

function taxonColorFor(species) {
  if (!species) return "transparent";
  const direct = state.speciesTaxon[species.trim().toLowerCase()];
  if (direct) return state.taxonColors[direct] || "transparent";
  if (/eagle|egret|macaw|jabiru|owl|hawk|kingfisher|caracara|vulture|cardinal|toucan|heron|stork|parrot|tanager/i.test(species)) return state.taxonColors.Bird || "transparent";
  if (/frog|toad/i.test(species)) return state.taxonColors.Amphibian || "transparent";
  if (/caiman|lizard|snake|turtle|tegu/i.test(species)) return state.taxonColors.Reptile || "transparent";
  return state.taxonColors.Mammal || "transparent";
}

/* ---------------------------------------------------------------- checks -- */

const checkKey = (c) => `${c.kind}:${c.a.id}:${c.b ? c.b.id : ""}`;

function checksFor(list) {
  const out = [];
  const live = list.filter((p) => !p.excluded);
  for (let i = 0; i < live.length; i++) {
    for (let j = i + 1; j < live.length; j++) {
      const a = shingles(live[i].body, 6);
      const b = shingles(live[j].body, 6);
      let hit = null;
      for (const k of a.keys()) if (b.has(k)) { hit = k; break; }
      if (hit) out.push({ kind: "dup", a: live[i], b: live[j], phrase: hit, quote: quoteShingle(live[i].body, 6, hit) });
    }
  }
  live.forEach((p) => { if (!p.body) out.push({ kind: "empty", a: p }); });

  const known = {};
  state.photos.forEach((p) => { if (p.species) known[p.species.toLowerCase()] = p.species; });
  live.forEach((p) => {
    if (p.species) return;
    const low = (p.body || "").toLowerCase();
    for (const k in known) if (low.indexOf(k) >= 0) { out.push({ kind: "species", a: p, name: known[k] }); break; }
  });

  return out.filter((c) => state.dismissed.indexOf(checkKey(c)) < 0);
}

/* ------------------------------------------------------------ mutation -- */

function logIt(text) {
  state.log = [{ at: stamp(), text }].concat(state.log).slice(0, 60);
}

function patch(id, fields) {
  const p = photoById(id);
  if (!p) return;
  Object.assign(p, fields);
  state.dirty += 1;
  render();
}

// Same as patch() but does not rebuild the DOM, so the caret survives typing.
function patchQuiet(id, fields) {
  const p = photoById(id);
  if (!p) return;
  Object.assign(p, fields);
  state.dirty += 1;
  renderChrome();
  renderBottom();
}

function toggleExclude(p) {
  logIt((p.excluded ? "re-included · " : "excluded · ") + (p.title || p.filename));
  patch(p.id, { excluded: !p.excluded });
}

function renumber(legId) {
  legPhotos(legId).forEach((p, i) => { p.order = i; });
}

// One move path for list rows, the expanded row, and sheet tiles.
// Reordering is refused across legs; use the LEG field to reassign a photo.
function move(srcId, targetId) {
  state.dragId = null;
  state.overId = null;
  if (!srcId || srcId === targetId) { render(); return; }
  const from = state.photos.findIndex((p) => p.id === srcId);
  const target = photoById(targetId);
  if (from < 0 || !target || bucketOf(state.photos[from]) !== bucketOf(target)) { render(); return; }
  const [moved] = state.photos.splice(from, 1);
  state.photos.splice(state.photos.findIndex((p) => p.id === targetId), 0, moved);
  renumber(bucketOf(moved));
  state.dirty += 1;
  logIt(`moved “${moved.title || moved.filename}” to ${String(moved.order + 1).padStart(2, "0")}`);
  render();
}

function reassignLeg(p, legId) {
  const was = bucketOf(p);
  if (was === legId) return;
  // Land at the end of the target leg rather than wherever the photo happened to
  // sit in the array, so a reassignment never silently jumps the queue.
  state.photos.splice(state.photos.indexOf(p), 1);
  p.legId = legId;
  const members = state.photos.filter((x) => bucketOf(x) === legId);
  const at = members.length ? state.photos.indexOf(members[members.length - 1]) + 1 : state.photos.length;
  state.photos.splice(at, 0, p);
  renumber(was);
  renumber(legId);
  state.dirty += 1;
  state.leg = legId;
  logIt(`moved “${p.title || p.filename}” to ${legDef(legId).name}`);
  render();
}

function sendNote(p) {
  const input = document.querySelector(".reply input, .pane .reply-solo");
  const text = input ? input.value.trim() : "";
  if (!text) return;
  p.notes = p.notes.concat([{ who: "YOU", text, at: new Date().toISOString() }]);
  state.dirty += 1;
  logIt(`note queued · ${text.slice(0, 48)}`);
  render();
}

function acceptPending(p) {
  logIt(`accepted rewrite · ${p.title || p.filename}`);
  patch(p.id, { pending: null });
}

function revertPending(p) {
  const was = p.pending || {};
  logIt(`reverted · ${p.title || p.filename}`);
  patch(p.id, {
    body: was.was != null ? was.was : p.body,
    title: was.wasTitle != null ? was.wasTitle : p.title,
    pending: null,
  });
}

/* ---------------------------------------------------------------- render -- */

function render() {
  renderChrome();
  renderSidebar();
  renderMain();
  renderBottom();
}

function renderChrome() {
  const photos = state.photos;
  const nExcluded = photos.filter((p) => p.excluded).length;
  const nNotes = photos.filter((p) => p.notes.length).length;
  const nChanges = photos.filter((p) => p.pending).length;

  $("#n-photos").textContent = photos.length;
  $("#n-excluded").textContent = nExcluded;
  $("#n-notes").textContent = nNotes;
  $("#n-changes").textContent = nChanges;
  $("#c-photos").textContent = photos.length;
  $("#c-excluded").textContent = `${nExcluded} excl`;
  $("#c-notes").textContent = `${nNotes} notes`;
  $("#c-changes").textContent = `${nChanges} chg`;
  $("#n-changes-2").textContent = nChanges;

  const w = window.innerWidth;
  $("#chips").classList.toggle("hidden", w < 1120);
  $("#chips-compact").classList.toggle("hidden", w >= 1120);
  $("#sync").classList.toggle("hidden", w < 1040);
  $("#zoom").classList.toggle("hidden", state.view !== "sheet");
  $("#zoom-label").textContent = `${ZOOMS[state.zoom]}px`;
  $("#zoom-out").disabled = state.zoom === 0;
  $("#zoom-in").disabled = state.zoom === ZOOMS.length - 1;

  $("#sync-dot").classList.toggle("dirty", state.dirty > 0);
  $("#sync-text").textContent = `rev ${state.rev}${state.dirty ? ` · ${state.dirty} unsaved edits` : " · in sync"}`;

  const nChecks = checksFor(legPhotos(state.leg)).length;
  $("#save-sub").textContent = state.dirty
    ? `saves ${state.dirty} · re-runs ${nChecks} checks`
    : (w >= 1040 ? "nothing to save" : `rev ${state.rev} · in sync`);

  document.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
}

function renderSidebar() {
  const host = $("#legs");
  host.replaceChildren();
  legOrder().forEach((leg) => {
    const list = legPhotos(leg.id);
    const row = el("button", "leg-row");
    row.type = "button";
    row.setAttribute("aria-current", String(leg.id === state.leg));
    row.append(el("span", "name", leg.name));
    const dot = el("span", "dot");
    if (list.some((p) => p.pending)) dot.classList.add("cyan");
    else if (list.some((p) => needsYou(p))) dot.classList.add("amber");
    row.append(dot, el("span", "count", String(list.length)));
    row.addEventListener("click", () => { state.leg = leg.id; state.selId = null; render(); });
    host.append(row);
  });

  const excluded = legPhotos(state.leg).filter((p) => p.excluded).length;
  document.querySelectorAll("#filters button").forEach((b) => {
    b.setAttribute("aria-pressed", String(state.filter === b.dataset.filter));
    if (b.dataset.filter === "excluded") b.textContent = `excluded ${excluded}`;
  });
}

function stateClass(p, flagged) {
  if (p.excluded) return "";
  if (p.pending) return "state-cyan";
  return needsYou(p) || flagged ? "state-amber" : "";
}

function renderMain() {
  const isList = state.view === "list";
  $("#list").classList.toggle("hidden", !isList);
  $("#list-head").classList.toggle("hidden", !isList);
  $("#sheet").classList.toggle("hidden", isList);
  if (isList) renderList(); else renderSheet();
}

function renderList() {
  const leg = legDef(state.leg);
  const all = legPhotos(state.leg);
  const excluded = all.filter((p) => p.excluded).length;
  const flagged = flaggedSet(all);

  $("#leg-name").textContent = leg.name;
  $("#leg-meta").textContent = [leg.dates, leg.region, leg.lodge, `${all.length} photos`, `${excluded} excluded`]
    .filter(Boolean).join(" · ");

  const host = $("#list");
  host.replaceChildren();
  const shown = all.filter((p) => passesFilter(p, flagged));

  shown.forEach((p) => {
    host.append(p.id === state.selId ? buildExpanded(p, all) : buildRow(p, all, flagged));
  });

  if (!shown.length) host.append(el("div", "empty", `Nothing matches this filter in ${leg.name}.`));
}

function flaggedSet(list) {
  const flagged = new Set();
  checksFor(list).forEach((c) => { flagged.add(c.a.id); if (c.b) flagged.add(c.b.id); });
  return flagged;
}

function passesFilter(p, flagged) {
  if (state.filter === "nospecies") return !p.species;
  if (state.filter === "excluded") return p.excluded;
  if (state.filter === "needs") return needsYou(p) || flagged.has(p.id);
  return true;
}

function buildRow(p, all, flagged) {
  const row = el("div", `row ${stateClass(p, flagged.has(p.id))}`);
  if (p.excluded) row.classList.add("excluded");
  row.dataset.id = p.id;
  row.draggable = true;

  row.append(el("div", "rail"), el("div", "grip", "⠿"));
  row.append(el("div", "num", p.excluded ? "—" : String(all.indexOf(p) + 1).padStart(2, "0")));

  const thumb = el("div", "thumb");
  if (p.thumb) thumb.style.backgroundImage = `url("${p.thumb}")`;
  row.append(thumb);

  const copy = el("div", "copy");
  copy.append(el("div", "t", p.title || "Untitled"));
  copy.append(el("div", "c", p.excluded
    ? "excluded — holds its place in the sequence"
    : (p.body || "no caption yet")));
  row.append(copy);

  const badge = p.pending ? "REWRITE" : (p.notes.length ? "NOTE" : (flagged.has(p.id) ? "CHECK" : ""));
  if (badge) row.append(el("div", `badge${badge === "REWRITE" ? " cyan" : ""}`, badge));

  const excl = el("button", "excl", p.excluded ? "RESTORE" : "EXCLUDE");
  excl.type = "button";
  excl.addEventListener("click", (e) => { e.stopPropagation(); toggleExclude(p); });
  row.append(excl);

  const when = el("div", "when");
  when.append(document.createTextNode(shortName(p.filename)), el("br"), document.createTextNode(whenLabel(p)));
  row.append(when);

  row.addEventListener("click", () => { state.selId = state.selId === p.id ? null : p.id; render(); });
  attachDrag(row, p);
  return row;
}

const shortName = (name) => (name.length > 22 ? `…${name.slice(-19)}` : name);
const whenLabel = (p) => `${p.date.slice(5, 10).replace("-", "/")} · ${p.date.slice(11, 16)}`;

function buildExpanded(p, all) {
  const wrap = el("div", `expanded${p.pending ? " state-cyan" : ""}`);
  wrap.dataset.id = p.id;

  const inner = el("div", "inner");
  inner.append(el("div", "rail-pad"));

  const grip = el("div", "grip", "⠿");
  grip.draggable = true;
  grip.title = "drag to reorder";
  inner.append(grip);
  inner.append(el("div", "num", p.excluded ? "—" : String(all.indexOf(p) + 1).padStart(2, "0")));

  const thumb = el("div", "thumb");
  if (p.thumb) thumb.style.backgroundImage = `url("${p.thumb}")`;
  inner.append(thumb);

  const fields = el("div", `fields${p.pending ? " pending-fields" : ""}`);

  // TITLE + close
  const titleRow = el("div", "field");
  titleRow.append(el("div", "key", "TITLE"));
  titleRow.append(textField(p, "title", "input"));
  const close = el("button", "mini", "CLOSE ✕");
  close.type = "button";
  close.title = "collapse (esc)";
  close.addEventListener("click", () => { state.selId = null; render(); });
  titleRow.append(close);
  fields.append(titleRow);

  // CAPTION
  const bodyRow = el("div", "field multiline");
  bodyRow.append(el("div", "key", "CAPTION"));
  bodyRow.append(textField(p, "body", "textarea"));
  fields.append(bodyRow);

  if (p.pending) fields.append(pendingRow(p, "indent"));

  // NOTES
  const notesRow = el("div", "field multiline");
  notesRow.append(el("div", "key", "NOTES"));
  notesRow.append(buildThread(p));
  fields.append(notesRow);

  // SPECIES
  const sp = el("div", "field");
  sp.append(el("div", "key", "SPECIES"));
  sp.append(textField(p, "species", "input", "none — not a wildlife frame"));
  const swatch = el("span", "swatch");
  swatch.style.background = taxonColorFor(p.species);
  sp.append(swatch);
  const set = state.photos.filter((x) => x.species).length;
  sp.append(el("span", "hint", `${set} of ${state.photos.length} set · drives the taxon colour on the site`));
  fields.append(sp);

  // PLACE — feeds alt text and the map pin label on the site.
  const place = el("div", "field");
  place.append(el("div", "key", "PLACE"));
  place.append(textField(p, "locationName", "input", "where this was taken"));
  const named = state.photos.filter((x) => x.locationName).length;
  place.append(el("span", "hint", `${named} of ${state.photos.length} set · used for alt text and the map pin`));
  fields.append(place);

  // LEG — the only way to reassign a photo, since drag is leg-local.
  const legRow = el("div", "field");
  legRow.append(el("div", "key", "LEG"));
  legRow.append(legSelect(p));
  legRow.append(el("span", "hint", "drag reorders within a leg · use this to move between legs"));
  fields.append(legRow);

  // metadata
  const meta = el("div", "meta indent");
  meta.append(el("span", "file", p.filename));
  meta.append(el("span", null, `${p.date.slice(0, 10)} · ${p.date.slice(11, 16)}${p.utcOffset ? ` · UTC${p.utcOffset}` : ""}`));
  const noFix = p.noGps || p.lat == null || p.lng == null;
  meta.append(el("span", noFix ? "warn" : null, noFix ? "NO GPS" : `${p.lat.toFixed(4)}, ${p.lng.toFixed(4)}`));
  meta.append(el("span", null, p.subjectId || "unbound"));
  meta.append(el("span", "spring"));
  meta.append(excludeCheck(p));
  fields.append(meta);

  inner.append(fields);
  wrap.append(inner);

  attachDrag(wrap, p, grip);
  return wrap;
}

function textField(p, field, tag, placeholder) {
  const node = document.createElement(tag);
  node.dataset.f = field;
  if (tag === "input") node.type = "text";
  node.value = p[field] || "";
  if (placeholder) node.placeholder = placeholder;
  node.addEventListener("click", (e) => e.stopPropagation());
  node.addEventListener("input", () => {
    p[field] = node.value;
    state.dirty += 1;
    renderChrome();
    renderBottom();
    syncTileTitle(p);
    if (field === "species") {
      const swatch = node.parentElement.querySelector(".swatch");
      if (swatch) swatch.style.background = taxonColorFor(node.value);
    }
  });
  return node;
}

function legSelect(p) {
  const sel = document.createElement("select");
  sel.dataset.f = "legId";
  legOrder().forEach((leg) => {
    const opt = document.createElement("option");
    opt.value = leg.id;
    opt.textContent = leg.name;
    if (leg.id === bucketOf(p)) opt.selected = true;
    sel.append(opt);
  });
  sel.addEventListener("change", () => reassignLeg(p, sel.value));
  return sel;
}

function pendingRow(p, extraClass) {
  const row = el("div", `pending${extraClass ? ` ${extraClass}` : ""}`);
  row.append(el("span", "why", `Assistant rewrote this — ${p.pending.why || "no reason given"}. Not accepted yet.`));
  row.append(el("span", "spring"));
  const accept = el("button", "sm accept", "Accept");
  accept.type = "button";
  accept.addEventListener("click", () => acceptPending(p));
  const revert = el("button", "sm", "Revert to mine");
  revert.type = "button";
  revert.addEventListener("click", () => revertPending(p));
  row.append(accept, revert);
  return row;
}

function buildThread(p) {
  const thread = el("div", "thread");
  p.notes.forEach((n) => {
    const who = n.who === "ASSISTANT" ? "assistant" : "you";
    const note = el("div", `note ${who}`);
    note.append(el("span", "who", n.who || "YOU"));
    note.append(el("span", "txt", n.text || ""));
    note.append(el("span", "at", noteTime(n.at)));
    thread.append(note);
  });

  const reply = el("div", "reply");
  const unanswered = p.notes.length && p.notes[p.notes.length - 1].who !== "ASSISTANT";
  reply.append(el("span", "who", unanswered ? "QUEUED" : "REPLY"));
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "tell the assistant what to change — enter to queue it";
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); sendNote(p); }
  });
  reply.append(input);
  thread.append(reply);
  return thread;
}

function excludeCheck(p) {
  const btn = el("button", "check", null);
  btn.type = "button";
  btn.setAttribute("aria-pressed", String(p.excluded));
  btn.append(el("i"), document.createTextNode("exclude"));
  btn.addEventListener("click", (e) => { e.stopPropagation(); toggleExclude(p); });
  return btn;
}

/* ----------------------------------------------------------------- sheet -- */

function renderSheet() {
  const grid = $("#grid");
  grid.replaceChildren();
  const tw = ZOOMS[state.zoom];

  legOrder().forEach((leg) => {
    const list = legPhotos(leg.id);
    const head = el("div", "sheet-head");
    head.append(el("div", "n", leg.name));
    head.append(el("div", "m", [leg.dates, list.length, `${list.filter((p) => p.excluded).length} excluded`].filter(Boolean).join(" · ")));
    head.append(el("div", "hr"));
    grid.append(head);

    const flagged = flaggedSet(list);
    list.forEach((p, i) => grid.append(buildTile(p, i, tw, flagged)));
  });

  $("#pane").style.width = `${state.paneW}px`;
  renderPane();
}

function buildTile(p, i, tw, flagged) {
  const tile = el("div", `tile ${stateClass(p, flagged.has(p.id))}`);
  if (p.excluded) tile.classList.add("excluded");
  tile.dataset.id = p.id;
  tile.style.width = `${tw}px`;
  tile.draggable = true;
  tile.setAttribute("aria-selected", String(p.id === state.selId));

  const shot = el("div", "shot");
  shot.style.height = `${Math.round(tw * 0.66)}px`;
  if (p.thumb) shot.style.backgroundImage = `url("${p.thumb}")`;
  shot.append(el("div", "n", p.excluded ? "—" : String(i + 1).padStart(2, "0")));
  const x = el("button", "x", p.excluded ? "↺" : "×");
  x.type = "button";
  x.addEventListener("click", (e) => { e.stopPropagation(); toggleExclude(p); });
  shot.append(x);
  tile.append(shot, el("div", "rail"));

  if (tw >= 232) tile.append(el("div", "cap", p.title || "Untitled"));

  tile.addEventListener("click", () => {
    state.selId = state.selId === p.id ? null : p.id;
    state.leg = bucketOf(p);
    render();
  });
  attachDrag(tile, p);
  return tile;
}

function renderPane() {
  const pane = $("#pane");
  pane.replaceChildren();
  pane.classList.remove("pending-fields");
  const p = selected();
  if (!p) {
    pane.append(el("div", "empty", "Click any frame to edit it here. Arrow keys walk the sheet, drag reorders within a leg."));
    return;
  }

  const list = legPhotos(bucketOf(p));
  const hero = el("div", "hero");
  if (p.card || p.thumb) hero.style.backgroundImage = `url("${p.card || p.thumb}")`;
  pane.append(hero);
  pane.append(el("div", "where", `${legDef(bucketOf(p)).name} · ${String(list.indexOf(p) + 1).padStart(2, "0")} OF ${list.length}`));

  if (p.pending) pane.classList.add("pending-fields");
  pane.append(textField(p, "title", "input"));
  pane.append(textField(p, "body", "textarea"));

  if (p.pending) pane.append(pendingRow(p));

  const reply = document.createElement("input");
  reply.type = "text";
  reply.className = "reply-solo";
  reply.placeholder = "note to the assistant — enter to queue it";
  reply.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); sendNote(p); } });
  pane.append(reply);

  pane.append(textField(p, "species", "input", "species — none"));
  pane.append(textField(p, "locationName", "input", "place — optional"));
  pane.append(legSelect(p));

  const meta = el("div", "meta");
  meta.append(el("span", "file", p.filename));
  meta.append(el("span", null, `${p.date.slice(0, 10)} · ${p.date.slice(11, 16)}`));
  if (p.noGps || p.lat == null || p.lng == null) meta.append(el("span", "warn", "NO GPS"));
  meta.append(el("span", "spring"));
  meta.append(excludeCheck(p));
  pane.append(meta);
}

function syncTileTitle(p) {
  const tile = document.querySelector(`.tile[data-id="${p.id}"] .cap`);
  if (tile) tile.textContent = p.title || "Untitled";
}

/* ---------------------------------------------------------- bottom panel -- */

function renderBottom() {
  const all = legPhotos(state.leg);
  const checks = checksFor(all);
  $("#n-recos").textContent = checks.length;

  document.querySelectorAll(".tabs button[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  $("#panel-recos").classList.toggle("hidden", state.tab !== "recos");
  $("#panel-changes").classList.toggle("hidden", state.tab !== "changes");
  $("#panel-log").classList.toggle("hidden", state.tab !== "log");

  $("#stale-dot").classList.toggle("hidden", state.dirty === 0);
  $("#stale-text").textContent = state.dirty ? "checks re-run on save & draft" : `checks current as of rev ${state.rev}`;

  renderRecos(checks, all);
  renderChanges();
  renderLog();
}

function renderRecos(checks, all) {
  const host = $("#panel-recos");
  host.replaceChildren();
  if (!checks.length) {
    host.append(el("div", "empty", `Nothing flagged in ${legDef(state.leg).name}. Publish will check every leg again before it writes.`));
    return;
  }

  const at = (p) => String(all.indexOf(p) + 1).padStart(2, "0");
  const legTag = (legDef(state.leg).name || "UNSORTED").toUpperCase();

  checks.forEach((c) => {
    const card = el("div", "reco");
    let head = "";
    let text = "";
    let applyLabel = "";
    let apply = () => {};

    if (c.kind === "dup") {
      head = `${legTag} · ${at(c.a)} + ${at(c.b)} · NEAR-DUPLICATE`;
      text = `Both captions run the same line — “${c.quote}”. Suggested: cut the repeated history from ${at(c.b)} and let it be about the moment.`;
      applyLabel = `Trim ${at(c.b)}`;
      apply = () => {
        const keep = sentences(c.b.body).filter((x) => !shingles(x, 6).has(c.phrase));
        logIt("applied near-duplicate fix");
        patch(c.b.id, {
          body: keep.length ? keep.join(" ") : c.b.body,
          pending: c.b.pending || { was: c.b.body, wasTitle: c.b.title, why: "duplicate history removed", at: new Date().toISOString() },
        });
      };
    } else if (c.kind === "empty") {
      head = `${legTag} · ${at(c.a)} · NO CAPTION`;
      text = `“${c.a.title || c.a.filename}” has no caption, so the site will render the frame with nothing under it.`;
      applyLabel = "Write it";
      apply = () => openPhoto(c.a);
    } else {
      head = `${legTag} · ${at(c.a)} · SPECIES UNSET`;
      text = `The caption names a ${c.name} but the species field is empty, so this frame will not pick up its taxon colour on the site.`;
      applyLabel = `Set ${c.name}`;
      apply = () => { logIt(`set species · ${c.name}`); patch(c.a.id, { species: c.name }); };
    }

    card.append(el("div", "head", head));
    card.append(el("div", "text", text));
    const acts = el("div", "acts");
    acts.append(button(applyLabel, "apply", apply));
    acts.append(button("Open", null, () => openPhoto(c.kind === "dup" ? c.b : c.a)));
    acts.append(button("Dismiss", null, () => { state.dismissed = state.dismissed.concat([checkKey(c)]); render(); }));
    card.append(acts);
    host.append(card);
  });
}

function button(label, cls, onClick) {
  const b = el("button", cls || null, label);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function openPhoto(p) {
  state.leg = bucketOf(p);
  state.selId = p.id;
  state.filter = "all";
  render();
  const node = document.querySelector(`.expanded[data-id="${p.id}"], .tile[data-id="${p.id}"]`);
  if (node) node.scrollIntoView({ block: "center" });
}

function renderChanges() {
  const host = $("#panel-changes");
  host.replaceChildren();
  const pending = state.photos.filter((p) => p.pending);
  if (!pending.length) {
    host.append(el("div", "empty", "No unaccepted rewrites. Write a note on any photo to queue one."));
    return;
  }
  pending.forEach((p) => {
    const row = el("div", "change");
    row.append(el("span", "rail"));
    row.append(el("span", "t", p.title || "Untitled"));
    row.append(el("span", "w", p.pending.why || ""));
    row.append(button("Open", null, () => openPhoto(p)));
    row.append(button("Accept", "accept", () => acceptPending(p)));
    host.append(row);
  });
}

function renderLog() {
  const host = $("#panel-log");
  host.replaceChildren();
  if (!state.log.length) {
    host.append(el("div", "empty", "Nothing yet this session."));
    return;
  }
  state.log.forEach((entry) => {
    const line = el("div", "log-line");
    line.append(el("span", "at", entry.at));
    line.append(el("span", null, entry.text));
    host.append(line);
  });
}

/* ------------------------------------------------------------------ drag -- */

function attachDrag(node, photo, handle) {
  const source = handle || node;
  source.addEventListener("dragstart", (e) => {
    e.stopPropagation();
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", photo.id); } catch (_) { /* Safari */ }
    state.dragId = photo.id;
    node.classList.add("dragging");
  });
  node.addEventListener("dragenter", () => {
    if (state.overId === photo.id) return;
    state.overId = photo.id;
    document.querySelectorAll(".drop-over").forEach((n) => n.classList.remove("drop-over"));
    if (state.dragId && state.dragId !== photo.id) node.classList.add("drop-over");
  });
  node.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; });
  node.addEventListener("dragend", () => {
    state.dragId = null;
    state.overId = null;
    node.classList.remove("dragging");
    document.querySelectorAll(".drop-over").forEach((n) => n.classList.remove("drop-over"));
  });
  node.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    move(state.dragId || e.dataTransfer.getData("text/plain"), photo.id);
  });
}

/* -------------------------------------------------------------- keyboard -- */

function sheetOrder() {
  const out = [];
  legOrder().forEach((leg) => legPhotos(leg.id).forEach((p) => out.push(p)));
  return out;
}

function cols() {
  const grid = $("#grid");
  if (!grid) return 1;
  return Math.max(1, Math.floor((grid.clientWidth - 32 + 7) / (ZOOMS[state.zoom] + 7)));
}

document.addEventListener("keydown", (e) => {
  const tag = (document.activeElement || {}).tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    if (e.key === "Escape") document.activeElement.blur();
    return;
  }
  if (e.key === "Escape" && state.selId) { state.selId = null; render(); return; }
  if (state.view !== "sheet") return;

  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols(), ArrowDown: cols() }[e.key];
  if (!step) return;
  e.preventDefault();

  const list = sheetOrder();
  if (!list.length) return;
  const i = list.findIndex((p) => p.id === state.selId);
  const next = list[Math.max(0, Math.min(list.length - 1, i < 0 ? 0 : i + step))];
  if (!next) return;

  state.selId = next.id;
  state.leg = bucketOf(next);
  render();

  const grid = $("#grid");
  const node = grid && grid.querySelector(`.tile[data-id="${next.id}"]`);
  if (!node) return;
  const g = grid.getBoundingClientRect();
  const r = node.getBoundingClientRect();
  if (r.top < g.top + 14) grid.scrollTop += r.top - g.top - 14;
  else if (r.bottom > g.bottom - 14) grid.scrollTop += r.bottom - g.bottom + 14;
});

/* ----------------------------------------------------------------- save -- */

function editsPayload() {
  const photos = {};
  // Emit records in stable id order. The in-memory array is in leg/sequence
  // order, and writing that out would rewrite most of the file every time a
  // photo moves — this keeps save diffs to the fields that actually changed.
  state.photos
    .slice()
    .sort((a, b) => a.id.localeCompare(b.id))
    .forEach((p) => {
      const record = { ...p.rest };
      record.legId = p.legId;
      record.order = p.order;
      if (p.title) record.title = p.title; else delete record.title;
      if (p.body) record.body = p.body; else delete record.body;
      if (p.species) record.species = p.species; else delete record.species;
      if (p.subjectId) record.subjectId = p.subjectId; else delete record.subjectId;
      if (p.locationName) record.locationName = p.locationName; else delete record.locationName;
      if (p.excluded) record.excluded = true; else delete record.excluded;
      if (p.notes.length) record.notes = p.notes; else delete record.notes;
      if (p.pending) record.pending = p.pending; else delete record.pending;
      photos[p.id] = record;
    });
  return { schemaVersion: 1, rev: state.rev, photos };
}

async function saveEdits() {
  const btn = $("#save");
  btn.disabled = true;
  try {
    const res = await fetch("/api/save-edits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editsPayload()),
    });
    const result = await res.json().catch(() => ({}));
    if (res.status === 409) {
      logIt(`save refused · file is at rev ${result.rev}, this tab is at rev ${state.rev} — reload before saving`);
      return;
    }
    if (!res.ok || !result.ok) throw new Error(result.error || `Save failed (${res.status})`);
    state.rev = typeof result.rev === "number" ? result.rev : state.rev + 1;
    state.dirty = 0;
    logIt(result.rebuildError ? `saved · trip.json rebuild failed: ${result.rebuildError}` : "saved · draft rebuilt");
  } catch (error) {
    logIt(`save failed · ${error.message} — use “download backup”`);
  } finally {
    btn.disabled = false;
    state.tab = "log";
    render();
  }
}

function publish() {
  const open = legOrder().reduce((sum, leg) => sum + checksFor(legPhotos(leg.id)).length, 0);
  if (open) {
    state.tab = "recos";
    logIt(`publish blocked · ${open} checks open across all legs`);
    render();
    return;
  }
  if (state.dirty) { saveEdits(); return; }
  logIt("publish · no open checks, data/trip.json is current");
  state.tab = "log";
  render();
}

function downloadEdits() {
  const blob = new Blob([`${JSON.stringify(editsPayload(), null, 2)}\n`], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "photo-edits.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

/* ------------------------------------------------------------------ wire -- */

document.querySelectorAll("[data-view]").forEach((b) => {
  b.addEventListener("click", () => { state.view = b.dataset.view; render(); });
});
document.querySelectorAll("#filters button").forEach((b) => {
  b.addEventListener("click", () => {
    state.filter = state.filter === b.dataset.filter ? "all" : b.dataset.filter;
    render();
  });
});
document.querySelectorAll(".tabs button[data-tab]").forEach((b) => {
  b.addEventListener("click", () => { state.tab = b.dataset.tab; renderBottom(); });
});
$("#zoom-out").addEventListener("click", () => { state.zoom = Math.max(0, state.zoom - 1); render(); });
$("#zoom-in").addEventListener("click", () => { state.zoom = Math.min(ZOOMS.length - 1, state.zoom + 1); render(); });
$("#save").addEventListener("click", saveEdits);
$("#publish").addEventListener("click", publish);
$("#download").addEventListener("click", downloadEdits);
$("#import").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  const parsed = JSON.parse(await file.text());
  const records = parsed.photos || {};
  state.photos.forEach((p) => {
    const raw = records[p.id];
    if (!raw) return;
    const rest = { ...raw };
    OWNED.forEach((k) => delete rest[k]);
    Object.assign(p, {
      rest,
      legId: raw.legId || "",
      order: typeof raw.order === "number" ? raw.order : p.order,
      title: raw.title || "",
      body: raw.body || raw.caption || "",
      species: raw.species || "",
      subjectId: raw.subjectId || "",
      locationName: raw.locationName || "",
      excluded: Boolean(raw.excluded),
      notes: Array.isArray(raw.notes) ? raw.notes : [],
      pending: raw.pending || null,
    });
  });
  state.photos.sort((a, b) => a.order - b.order);
  state.dirty += 1;
  logIt(`imported ${Object.keys(records).length} records from ${file.name}`);
  render();
});

window.addEventListener("resize", renderChrome);

// Pane divider: drag to resize between 260 and 780px, double-click to reset.
$("#divider").addEventListener("pointerdown", (e) => {
  e.preventDefault();
  const x0 = e.clientX;
  const w0 = state.paneW;
  const divider = $("#divider");
  divider.classList.add("resizing");
  const onMove = (ev) => {
    state.paneW = Math.max(260, Math.min(780, w0 - (ev.clientX - x0)));
    $("#pane").style.width = `${state.paneW}px`;
  };
  const onUp = () => {
    divider.classList.remove("resizing");
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerup", onUp);
  };
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onUp);
});
$("#divider").addEventListener("dblclick", () => {
  state.paneW = 352;
  $("#pane").style.width = "352px";
});

load().catch((error) => {
  state.err = error.message;
  $("#leg-name").textContent = "Data failed to load";
  $("#leg-meta").textContent = error.message;
});
