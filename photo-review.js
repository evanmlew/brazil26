const state = {
  catalog: [],
  edits: {},
  files: new Map(),
  objectUrls: [],
  legs: [],
  legOrder: [],
  narratives: {},
};

const $ = (selector) => document.querySelector(selector);
const canonicalFields = new Set(["legId", "subjectId", "locationName", "kicker", "title", "body", "chips", "tags", "confidence", "featured", "star", "species", "order"]);

async function load() {
  const [catalogResponse, editsResponse, legsResponse, narrativeResponse] = await Promise.all([
    fetch("data/photo-catalog.json"),
    fetch("data/photo-edits.json"),
    fetch("data/legs.json"),
    fetch("data/narrative.json"),
  ]);
  if (!catalogResponse.ok) throw new Error(`Could not load catalog (${catalogResponse.status})`);
  if (!legsResponse.ok) throw new Error(`Could not load legs (${legsResponse.status})`);
  if (!narrativeResponse.ok) throw new Error(`Could not load narrative (${narrativeResponse.status})`);
  state.catalog = (await catalogResponse.json()).photos;
  state.edits = editsResponse.ok ? normalizeEdits((await editsResponse.json()).photos || {}) : {};
  const legsDoc = await legsResponse.json();
  state.legs = legsDoc.legs || [];
  state.legOrder = ["", ...state.legs.map((leg) => leg.id)];
  state.narratives = (await narrativeResponse.json()).subjects || {};
  populateSubjectOptions();
  render();
}

function normalizeEdits(photos) {
  return Object.fromEntries(Object.entries(photos || {}).map(([id, edit]) => {
    const next = { ...edit };
    if (next.caption && !next.body) next.body = next.caption;
    delete next.caption;
    if (Array.isArray(next.chips)) next.chips = next.chips.filter(Boolean);
    if (Array.isArray(next.tags)) next.tags = next.tags.filter(Boolean);
    return [id, next];
  }));
}

function populateSubjectOptions() {
  const datalist = $("#subject-options");
  datalist.replaceChildren();
  Object.keys(state.narratives).sort().forEach((id) => {
    const option = document.createElement("option");
    const subject = state.narratives[id];
    option.value = id;
    option.label = `${subject.leg || ""} · ${subject.title || subject.common || id}`;
    datalist.append(option);
  });
}

function valueFor(photo, field) {
  const edit = state.edits[photo.id] || {};
  const value = edit[field] ?? photo[field] ?? (field === "chips" || field === "tags" ? [] : field === "featured" || field === "star" ? false : field === "order" ? null : "");
  return field === "body" ? (value || photo.caption || "") : value;
}

function photoEditCount() {
  return Object.values(state.edits).filter((edit) => Object.keys(edit).length).length;
}

function groupSortKey(photo) {
  const order = valueFor(photo, "order");
  return [order == null ? 1 : 0, order ?? 0, photo.date || photo.exportedAt || "", photo.filename];
}

function groupedPhotos() {
  const groups = new Map();
  state.legOrder.forEach((legId) => groups.set(legId, []));
  [...state.catalog].sort((a, b) => {
    const [aMissing, aOrder, aDate, aName] = groupSortKey(a);
    const [bMissing, bOrder, bDate, bName] = groupSortKey(b);
    return aMissing - bMissing || aOrder - bOrder || aDate.localeCompare(bDate) || aName.localeCompare(bName);
  }).forEach((photo) => {
    const legId = valueFor(photo, "legId") || "";
    if (!groups.has(legId)) groups.set(legId, []);
    groups.get(legId).push(photo);
  });
  return groups;
}

function legMeta(legId) {
  return state.legs.find((leg) => leg.id === legId) || null;
}

function technicalBadges(photo) {
  const parts = [`${photo.width} × ${photo.height}`];
  const shotAt = photo.date || photo.exportedAt;
  if (shotAt) parts.push(new Date(shotAt).toLocaleString());
  if (typeof photo.latitude === "number" && typeof photo.longitude === "number") parts.push(`GPS ${photo.latitude.toFixed(4)}, ${photo.longitude.toFixed(4)}`);
  else parts.push("No GPS");
  return parts;
}

function subjectBadges(photo) {
  const badges = [];
  const subjectId = valueFor(photo, "subjectId");
  const subject = state.narratives[subjectId];
  if (subjectId) badges.push({ text: subject ? `${subjectId} · ${subject.title || subject.common || subjectId}` : `${subjectId} · missing`, className: "subject" });
  (photo.flags || []).forEach((flag) => badges.push({ text: flag === "no-gps" ? "NO GPS" : flag, className: "flag" }));
  (subject?.flags || []).forEach((flag) => badges.push({ text: flag, className: "flag" }));
  if (valueFor(photo, "featured")) badges.push({ text: "Featured stop thumb", className: "flag" });
  if (valueFor(photo, "star")) badges.push({ text: "★ Trip standout", className: "flag" });
  return badges;
}

function fillLegOptions(select, activeValue) {
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "Unassigned";
  select.append(empty);
  state.legs.forEach((leg) => {
    const option = document.createElement("option");
    option.value = leg.id;
    option.textContent = `${leg.n}. ${leg.name}`;
    option.selected = leg.id === activeValue;
    select.append(option);
  });
}

function render() {
  const groupList = $("#group-list");
  groupList.replaceChildren();
  const groups = groupedPhotos();
  for (const [legId, photos] of groups.entries()) {
    if (!photos.length) continue;
    const section = $("#group-template").content.cloneNode(true);
    const root = section.querySelector(".photo-group");
    const leg = legMeta(legId);
    root.dataset.legId = legId;
    section.querySelector(".group-kicker").textContent = leg ? `${leg.dates} · ${leg.region}` : "Needs assignment";
    section.querySelector(".group-title").textContent = leg ? leg.name : "Unassigned";
    section.querySelector(".group-count").textContent = `${photos.length} photo${photos.length === 1 ? "" : "s"}`;
    const grid = section.querySelector(".group-grid");
    photos.forEach((photo) => grid.append(renderCard(photo, photos)));
    groupList.append(root);
  }
  $("#status").textContent = `${state.catalog.length} photos · ${photoEditCount()} with editorial edits`;
}

function renderCard(photo, groupPhotos) {
  const card = $("#photo-template").content.cloneNode(true);
  const root = card.querySelector(".photo-card");
  const file = state.files.get(photo.filename);
  root.dataset.id = photo.id;
  root.querySelector(".filename").textContent = photo.filename;

  const preview = root.querySelector(".preview");
  if (file) {
    const url = URL.createObjectURL(file);
    state.objectUrls.push(url);
    preview.querySelector("img").src = url;
    preview.classList.add("has-image");
  }

  const technical = root.querySelector(".technical");
  technical.replaceChildren(...technicalBadges(photo).map((label) => badge(label)));
  const flags = root.querySelector(".flags");
  const flagBadges = subjectBadges(photo);
  flags.replaceChildren(...flagBadges.map((item) => badge(item.text, item.className)));

  const legSelect = root.querySelector('select[data-field="legId"]');
  fillLegOptions(legSelect, valueFor(photo, "legId"));

  root.querySelectorAll("[data-field]").forEach((input) => {
    const field = input.dataset.field;
    const value = valueFor(photo, field);
    if (input.tagName === "SELECT") {
      input.value = value;
    } else if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (field === "chips" || field === "tags") {
      input.value = Array.isArray(value) ? value.join(", ") : value;
    } else {
      input.value = value ?? "";
    }
    input.addEventListener("input", () => update(photo, field, input));
    input.addEventListener("change", () => update(photo, field, input));
  });

  root.querySelectorAll("[data-move]").forEach((button) => {
    button.addEventListener("click", () => movePhoto(groupPhotos, photo.id, Number(button.dataset.move)));
  });
  return root;
}

function badge(text, className = "") {
  const span = document.createElement("span");
  span.className = `badge ${className}`.trim();
  span.textContent = text;
  return span;
}

function parseFieldValue(field, input) {
  if (input.type === "checkbox") return input.checked;
  if (field === "chips" || field === "tags") return input.value.split(",").map((part) => part.trim()).filter(Boolean);
  if (field === "order") return input.value === "" ? null : Number(input.value);
  return input.value.trim();
}

function update(photo, field, input) {
  const edit = { ...(state.edits[photo.id] || {}) };
  const value = parseFieldValue(field, input);
  if (field === "legId") delete edit.order;
  if (field === "body" && !value && edit.caption) delete edit.caption;
  const empty = Array.isArray(value) ? !value.length : value === "" || value === false || value == null;
  if (empty) delete edit[field];
  else edit[field] = value;
  Object.keys(edit).forEach((key) => { if (!canonicalFields.has(key)) delete edit[key]; });
  if (!Object.keys(edit).length) delete state.edits[photo.id];
  else state.edits[photo.id] = edit;
  render();
}

function movePhoto(groupPhotos, photoId, direction) {
  const ordered = [...groupPhotos].sort((a, b) => {
    const [aMissing, aOrder, aDate, aName] = groupSortKey(a);
    const [bMissing, bOrder, bDate, bName] = groupSortKey(b);
    return aMissing - bMissing || aOrder - bOrder || aDate.localeCompare(bDate) || aName.localeCompare(bName);
  });
  const index = ordered.findIndex((photo) => photo.id === photoId);
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= ordered.length) return;
  [ordered[index], ordered[nextIndex]] = [ordered[nextIndex], ordered[index]];
  ordered.forEach((photo, position) => {
    state.edits[photo.id] = { ...(state.edits[photo.id] || {}), order: position };
  });
  render();
}

function serializeEdits() {
  const photos = {};
  Object.entries(state.edits).forEach(([id, edit]) => {
    const clean = {};
    Object.entries(edit).forEach(([key, value]) => {
      if (!canonicalFields.has(key)) return;
      if (Array.isArray(value)) {
        if (value.length) clean[key] = value;
        return;
      }
      if (typeof value === "boolean") {
        if (value) clean[key] = value;
        return;
      }
      if (key === "order") {
        if (Number.isInteger(value)) clean[key] = value;
        return;
      }
      if (value !== "" && value != null) clean[key] = value;
    });
    if (Object.keys(clean).length) photos[id] = clean;
  });
  return { schemaVersion: 1, photos };
}

function downloadEdits() {
  const blob = new Blob([JSON.stringify(serializeEdits(), null, 2) + "\n"], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "photo-edits.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

$("#folder-input").addEventListener("change", (event) => {
  state.files = new Map([...event.target.files].map((file) => [file.name, file]));
  state.objectUrls.forEach((url) => URL.revokeObjectURL(url));
  state.objectUrls = [];
  render();
});

$("#edits-input").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  state.edits = normalizeEdits(JSON.parse(await file.text()).photos || {});
  render();
});

$("#download-button").addEventListener("click", downloadEdits);
load().catch((error) => { $("#status").textContent = error.message; });
