const state = { catalog: [], edits: {}, legs: [] };
const $ = (selector) => document.querySelector(selector);
const UNSORTED_LEG = { id: "unsorted", n: "—", name: "Unsorted", dates: "" };

async function load() {
  const [catalogRes, editsRes, legsRes] = await Promise.all([
    fetch("data/photo-catalog.json"),
    fetch("data/photo-edits.json"),
    fetch("data/legs.json"),
  ]);
  if (!catalogRes.ok) throw new Error(`Could not load catalog (${catalogRes.status})`);
  state.catalog = (await catalogRes.json()).photos;
  state.edits = editsRes.ok ? normalizeEdits((await editsRes.json()).photos || {}) : {};
  state.legs = legsRes.ok ? (await legsRes.json()).legs || [] : [];
  render();
}

// Accept the legacy `caption` alias (pre-existing overlay entries) as `body`,
// so nothing is lost when this simplified tool loads an older edits file.
function normalizeEdits(photos) {
  return Object.fromEntries(Object.entries(photos || {}).map(([id, edit]) => {
    const next = { ...edit };
    if (next.caption && !next.body) next.body = next.caption;
    delete next.caption;
    return [id, next];
  }));
}

function valueFor(photo, field) {
  const edit = state.edits[photo.id] || {};
  const fallback = field === "featured" || field === "excluded" ? false : "";
  return edit[field] ?? photo[field] ?? fallback;
}

function legIdFor(photo) {
  const known = new Set(state.legs.map((leg) => leg.id));
  const value = valueFor(photo, "legId");
  return known.has(value) ? value : UNSORTED_LEG.id;
}

function orderFor(photo) {
  const edit = state.edits[photo.id];
  return edit && typeof edit.order === "number" ? edit.order : Number.MAX_SAFE_INTEGER;
}

function ensureEdit(photoId) {
  if (!state.edits[photoId]) state.edits[photoId] = {};
  return state.edits[photoId];
}

function updateStatus() {
  const excludedCount = state.catalog.filter((photo) => valueFor(photo, "excluded")).length;
  $("#status").textContent = `${state.catalog.length} photos · ${excludedCount} excluded from the site`;
}

function render() {
  const container = $("#sections");
  container.replaceChildren();

  const byLeg = new Map();
  state.catalog.forEach((photo) => {
    const legId = legIdFor(photo);
    if (!byLeg.has(legId)) byLeg.set(legId, []);
    byLeg.get(legId).push(photo);
  });

  const sectionsToRender = [...state.legs];
  if (byLeg.has(UNSORTED_LEG.id)) sectionsToRender.push(UNSORTED_LEG);

  sectionsToRender.forEach((leg) => {
    const photos = (byLeg.get(leg.id) || []).sort((a, b) => {
      return orderFor(a) - orderFor(b) || a.filename.localeCompare(b.filename);
    });
    const section = $("#section-template").content.cloneNode(true);
    const root = section.querySelector(".leg-section");
    root.dataset.leg = leg.id;
    root.querySelector(".leg-name").textContent = leg.name;
    root.querySelector(".leg-dates").textContent = [leg.dates, leg.region].filter(Boolean).join(" · ");
    const grid = root.querySelector(".leg-grid");
    photos.forEach((photo) => grid.append(buildCard(photo)));
    updateLegCount(root);
    attachDropzone(grid);
    container.append(root);
  });

  updateStatus();
}

function updateLegCount(sectionRoot) {
  const count = sectionRoot.querySelectorAll(".photo-card").length;
  sectionRoot.querySelector(".leg-count").textContent = `${count} photo${count === 1 ? "" : "s"}`;
}

function buildCard(photo) {
  const card = $("#photo-template").content.cloneNode(true);
  const root = card.querySelector(".photo-card");
  root.dataset.id = photo.id;
  root.querySelector(".filename").textContent = photo.filename;
  root.querySelector(".preview img").src = `photos/${encodeURIComponent(photo.filename)}`;
  root.querySelector(".preview img").alt = photo.filename;

  root.querySelectorAll("[data-field]").forEach((input) => {
    const field = input.dataset.field;
    const value = valueFor(photo, field);
    if (input.type === "checkbox") input.checked = Boolean(value);
    else input.value = value;
    input.addEventListener("input", () => update(photo, field, input));
    input.addEventListener("change", () => update(photo, field, input));
  });

  setExcludedState(root, valueFor(photo, "excluded"));
  root.querySelector(".exclude-toggle").addEventListener("click", () => {
    const edit = ensureEdit(photo.id);
    edit.excluded = !edit.excluded;
    setExcludedState(root, edit.excluded);
    updateStatus();
  });

  attachDrag(root);
  return root;
}

function setExcludedState(root, excluded) {
  root.classList.toggle("excluded", Boolean(excluded));
  root.querySelector(".exclude-toggle").textContent = excluded ? "Include on site" : "Exclude from site";
}

function update(photo, field, input) {
  const edit = ensureEdit(photo.id);
  let value;
  let isEmpty;
  if (input.type === "checkbox") {
    value = input.checked;
    isEmpty = value === false;
  } else if (input.type === "number") {
    value = input.value === "" ? null : Number(input.value);
    isEmpty = value === null || Number.isNaN(value);
  } else {
    value = input.value;
    isEmpty = value === "";
  }
  if (isEmpty) delete edit[field];
  else edit[field] = value;
  updateStatus();
}

// --- Drag and drop: reorder within a section, or move to a different one ---
// A shared placeholder block shows exactly where the photo will land;
// the card being dragged stays put (dimmed) until the drop actually happens.

let placeholder = null;
function getPlaceholder() {
  if (!placeholder) {
    placeholder = document.createElement("div");
    placeholder.className = "drop-placeholder";
    placeholder.textContent = "Drop here";
  }
  return placeholder;
}

function clearDropTargets() {
  document.querySelectorAll(".leg-section.drop-target").forEach((el) => el.classList.remove("drop-target"));
}

function attachDrag(card) {
  card.addEventListener("dragstart", (event) => {
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.id);
  });
  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    getPlaceholder().remove();
    clearDropTargets();
  });
}

function attachDropzone(grid) {
  grid.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (!document.querySelector(".photo-card.dragging")) return;
    clearDropTargets();
    grid.closest(".leg-section").classList.add("drop-target");
    const ph = getPlaceholder();
    const afterElement = cardAfterPoint(grid, event.clientX, event.clientY);
    if (afterElement == null) grid.append(ph);
    else grid.insertBefore(ph, afterElement);
  });
  grid.addEventListener("drop", (event) => {
    event.preventDefault();
    const dragging = document.querySelector(".photo-card.dragging");
    const ph = getPlaceholder();
    if (dragging) {
      if (ph.parentElement === grid) grid.insertBefore(dragging, ph);
      else grid.append(dragging);
    }
    ph.remove();
    dragging?.classList.remove("dragging");
    clearDropTargets();
    document.querySelectorAll(".leg-section").forEach(updateLegCount);
    persistOrderFromDom();
  });
}

function cardAfterPoint(grid, x, y) {
  const cards = [...grid.querySelectorAll(".photo-card:not(.dragging)")];
  return (
    cards.find((card) => {
      const box = card.getBoundingClientRect();
      const sameRow = y >= box.top && y <= box.bottom;
      return sameRow ? x < box.left + box.width / 2 : y < box.top + box.height / 2;
    }) || null
  );
}

function persistOrderFromDom() {
  document.querySelectorAll(".leg-section").forEach((section) => {
    const legId = section.dataset.leg;
    [...section.querySelectorAll(".photo-card")].forEach((card, index) => {
      const edit = ensureEdit(card.dataset.id);
      edit.legId = legId;
      edit.order = index;
    });
  });
  updateStatus();
}

function editsPayload() {
  return { schemaVersion: 1, photos: state.edits };
}

function downloadEdits() {
  const blob = new Blob([JSON.stringify(editsPayload(), null, 2) + "\n"], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "photo-edits.json";
  link.click();
  URL.revokeObjectURL(link.href);
}

async function saveEdits() {
  const saveButton = $("#save-button");
  const originalLabel = saveButton.textContent;
  saveButton.disabled = true;
  saveButton.textContent = "Saving…";
  try {
    const response = await fetch("/api/save-edits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editsPayload()),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || `Save failed (${response.status})`);
    if (result.rebuildError) {
      saveButton.textContent = "Saved, rebuild failed";
      $("#status").textContent = `Saved, but rebuilding the site failed: ${result.rebuildError}`;
    } else {
      saveButton.textContent = "Saved ✓ site updated";
      updateStatus();
    }
  } catch (error) {
    saveButton.textContent = "Save failed";
    $("#status").textContent = `Save failed: ${error.message}. Falling back to Download backup lets you save the file manually.`;
  } finally {
    setTimeout(() => {
      saveButton.textContent = originalLabel;
      saveButton.disabled = false;
    }, 1800);
  }
}

$("#edits-input").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  const contents = await file.text();
  state.edits = normalizeEdits(JSON.parse(contents).photos || {});
  render();
});
$("#download-button").addEventListener("click", downloadEdits);
$("#save-button").addEventListener("click", saveEdits);
load().catch((error) => { $("#status").textContent = error.message; });
