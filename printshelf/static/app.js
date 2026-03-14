const state = {
  items: [],
  selectedItemId: null,
  hasBridge: false,
  scanPollTimer: null,
  lastLoadedRunId: null,
  currentView: "browse",
  tags: [],
  activeTag: null,
  taggedItems: [],
  checkedTagItemIds: new Set(),
  tagListRequestId: 0,
  taggedItemsRequestId: 0,
};

const $ = (id) => document.getElementById(id);
const ACTIVE_SCAN_STATUSES = new Set(["counting", "running", "canceling"]);

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) message = payload.detail;
    } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

async function loadConfig() {
  const config = await api("/api/config");
  $("rootPathInput").value = config.root_path || "";
}

function buildItemQueryParams({ tag = "" } = {}) {
  const params = new URLSearchParams();
  params.set("q", $("searchInput").value.trim());
  params.set("file_type", $("typeFilter").value);
  params.set("sort", $("sortFilter").value || "date_added_desc");
  if (tag) params.set("tag", tag);
  return params.toString();
}

async function loadItems() {
  const items = await api(`/api/items?${buildItemQueryParams()}`);
  state.items = items;
  renderCatalog();
  $("resultCount").textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;
  if (!items.some((item) => item.id === state.selectedItemId)) {
    state.selectedItemId = null;
    renderDetail(null);
  }
}

function renderCatalog() {
  const grid = $("catalogGrid");
  const empty = $("emptyState");
  grid.innerHTML = "";

  if (!state.items.length) {
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");

  for (const item of state.items) {
    const card = document.createElement("article");
    card.className = "card";
    if (item.id === state.selectedItemId) card.classList.add("selected");
    card.addEventListener("click", async () => {
      state.selectedItemId = item.id;
      renderCatalog();
      const fullItem = await api(`/api/items/${item.id}`);
      renderDetail(fullItem);
    });

    const tagsHtml = (item.tags || [])
      .slice(0, 6)
      .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
      .join("");

    card.innerHTML = `
      <div class="card-preview">
        ${item.preview_url ? `<img loading="lazy" src="${escapeHtml(item.preview_url)}" alt="">` : ""}
      </div>
      <div class="card-body">
        <div class="row" style="justify-content: space-between; align-items: center;">
          <div class="pill">${escapeHtml(item.file_type.toUpperCase())}</div>
          <div class="muted">${escapeHtml(formatBytes(item.size_bytes))}</div>
        </div>
        <div class="card-title">${escapeHtml(item.filename)}</div>
        <div class="card-path">${escapeHtml(item.relative_path)}</div>
        <div class="card-description">${escapeHtml(item.description || "No description yet.")}</div>
        <div class="tag-list">${tagsHtml}</div>
      </div>
    `;
    grid.appendChild(card);
  }
}

function renderDetail(item) {
  const empty = $("detailEmpty");
  const view = $("detailView");
  if (!item) {
    empty.classList.remove("hidden");
    view.classList.add("hidden");
    return;
  }

  empty.classList.add("hidden");
  view.classList.remove("hidden");

  $("detailTitle").textContent = item.filename;
  $("detailType").textContent = item.file_type.toUpperCase();
  $("detailPreview").src = item.preview_url || "";
  $("detailPath").textContent = item.path;
  $("detailPreviewSource").textContent = item.preview_source || "unknown";
  $("detailSize").textContent = formatBytes(item.size_bytes);
  $("tagsInput").value = (item.tags || []).join(", ");
  $("descriptionInput").value = item.description || "";
  $("metaInput").value = JSON.stringify(item.meta || {}, null, 2);
  $("indexedMeta").textContent = JSON.stringify(item.indexed_meta || {}, null, 2);
}

async function saveItem() {
  if (!state.selectedItemId) return;

  let meta = {};
  const rawMeta = $("metaInput").value.trim();
  if (rawMeta) {
    try {
      meta = JSON.parse(rawMeta);
    } catch (error) {
      alert(`Custom metadata must be valid JSON.\n\n${error.message}`);
      return;
    }
  }

  const payload = {
    description: $("descriptionInput").value,
    tags: $("tagsInput").value.split(",").map((tag) => tag.trim()).filter(Boolean),
    meta,
  };

  const updated = await api(`/api/items/${state.selectedItemId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  renderDetail(updated);
  await loadItems();
}

async function saveRootPath() {
  const rootPath = $("rootPathInput").value.trim();
  const result = await api("/api/config", {
    method: "POST",
    body: JSON.stringify({ root_path: rootPath }),
  });
  $("rootPathInput").value = result.root_path || "";
}

function setTagsStatus(message) {
  $("tagsStatus").textContent = message || "";
}

function setView(view) {
  state.currentView = view === "tags" ? "tags" : "browse";
  $("browseView").classList.toggle("hidden", state.currentView !== "browse");
  $("tagsView").classList.toggle("hidden", state.currentView !== "tags");
  $("viewBrowseButton").classList.toggle("active", state.currentView === "browse");
  $("viewTagsButton").classList.toggle("active", state.currentView === "tags");
}

function parseTagInput(value) {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function updateTagActionState() {
  const hasActiveTag = Boolean(state.activeTag);
  $("renameTagButton").disabled = !hasActiveTag;
  $("deleteTagButton").disabled = !hasActiveTag;
  $("bulkApplyButton").disabled =
    !hasActiveTag || state.checkedTagItemIds.size <= 0;
  $("checkedItemCount").textContent = `${state.checkedTagItemIds.size} checked`;
}

function renderTagList() {
  const list = $("tagList");
  list.innerHTML = "";

  if (!state.tags.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "No tags found.";
    list.appendChild(empty);
    return;
  }

  for (const tag of state.tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-row";
    if (state.activeTag && state.activeTag.id === tag.id) {
      button.classList.add("active");
    }
    button.innerHTML = `
      <span class="tag-row-name">${escapeHtml(tag.name)}</span>
      <span class="tag-row-count">${Number(tag.item_count || 0)} items</span>
    `;
    button.addEventListener("click", () => {
      const isAlreadySelected =
        state.activeTag && state.activeTag.id === Number(tag.id);
      if (isAlreadySelected) {
        state.activeTag = null;
        state.taggedItems = [];
        state.checkedTagItemIds.clear();
        renderTagList();
        renderTaggedItems();
        updateTagActionState();
        return;
      }
      state.activeTag = { id: Number(tag.id), name: String(tag.name || "") };
      state.checkedTagItemIds.clear();
      renderTagList();
      renderTaggedItems();
      updateTagActionState();
      loadTaggedItems().catch((error) => {
        setTagsStatus(error.message);
      });
    });
    list.appendChild(button);
  }
}

function renderTaggedItems() {
  const activeTagTitle = $("activeTagTitle");
  const activeTagCount = $("activeTagCount");
  const resultCount = $("taggedResultCount");
  const list = $("taggedItemsList");
  list.innerHTML = "";

  if (!state.activeTag) {
    activeTagTitle.textContent = "No tag selected";
    activeTagCount.textContent = "0 items";
    resultCount.textContent = "Choose a tag to show matching items.";
    updateTagActionState();
    return;
  }

  activeTagTitle.textContent = `Tag: ${state.activeTag.name}`;
  activeTagCount.textContent = `${state.taggedItems.length} item${
    state.taggedItems.length === 1 ? "" : "s"
  }`;
  resultCount.textContent = `${state.taggedItems.length} matching item${
    state.taggedItems.length === 1 ? "" : "s"
  }`;

  if (!state.taggedItems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<p>No items match this tag with current filters.</p>";
    list.appendChild(empty);
    updateTagActionState();
    return;
  }

  for (const item of state.taggedItems) {
    const row = document.createElement("article");
    row.className = "tagged-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.checkedTagItemIds.has(item.id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.checkedTagItemIds.add(item.id);
      } else {
        state.checkedTagItemIds.delete(item.id);
      }
      updateTagActionState();
    });

    const meta = document.createElement("div");
    meta.className = "tagged-item-meta";
    const tagsHtml = (item.tags || [])
      .slice(0, 8)
      .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
      .join("");
    meta.innerHTML = `
      <div class="tagged-item-title">${escapeHtml(item.filename)}</div>
      <div class="tagged-item-path">${escapeHtml(item.relative_path)}</div>
      <div class="row">
        <span class="pill">${escapeHtml(item.file_type.toUpperCase())}</span>
        <span class="muted">${escapeHtml(formatBytes(item.size_bytes))}</span>
      </div>
      <div class="tagged-item-tags">${tagsHtml}</div>
    `;

    row.appendChild(checkbox);
    row.appendChild(meta);
    list.appendChild(row);
  }
  updateTagActionState();
}

async function loadTags() {
  const requestId = ++state.tagListRequestId;
  const query = encodeURIComponent($("tagSearchInput").value.trim());
  const tags = await api(`/api/tags?q=${query}`);
  if (requestId !== state.tagListRequestId) return;

  state.tags = tags.map((tag) => ({
    id: Number(tag.id),
    name: String(tag.name || ""),
    item_count: Number(tag.item_count || 0),
  }));

  if (state.activeTag) {
    const updated = state.tags.find((tag) => tag.id === state.activeTag.id);
    if (updated) {
      state.activeTag = { id: updated.id, name: updated.name };
    } else {
      state.activeTag = null;
      state.taggedItems = [];
      state.checkedTagItemIds.clear();
    }
  }

  renderTagList();
  renderTaggedItems();
}

async function loadTaggedItems() {
  if (!state.activeTag) {
    state.taggedItems = [];
    state.checkedTagItemIds.clear();
    renderTaggedItems();
    return;
  }

  const requestId = ++state.taggedItemsRequestId;
  const selectedTagName = state.activeTag.name;
  const items = await api(
    `/api/items?${buildItemQueryParams({ tag: selectedTagName })}`
  );
  if (requestId !== state.taggedItemsRequestId) return;
  if (!state.activeTag || state.activeTag.name !== selectedTagName) return;

  state.taggedItems = items;
  const validIds = new Set(items.map((item) => item.id));
  state.checkedTagItemIds = new Set(
    [...state.checkedTagItemIds].filter((itemId) => validIds.has(itemId))
  );
  renderTaggedItems();
}

async function renameActiveTag() {
  if (!state.activeTag) return;
  const nextName = window.prompt("Rename tag", state.activeTag.name);
  if (nextName === null) return;

  const updated = await api(`/api/tags/${state.activeTag.id}`, {
    method: "PATCH",
    body: JSON.stringify({ name: nextName }),
  });
  state.activeTag = { id: Number(updated.id), name: String(updated.name || "") };
  setTagsStatus(`Tag renamed to "${state.activeTag.name}".`);
  await loadTags();
  await loadTaggedItems();
  await loadItems();
}

async function deleteActiveTag() {
  if (!state.activeTag) return;
  const confirmed = window.confirm(
    `Delete tag "${state.activeTag.name}" from all items?`
  );
  if (!confirmed) return;

  const deletedTagName = state.activeTag.name;
  await api(`/api/tags/${state.activeTag.id}`, { method: "DELETE" });
  state.activeTag = null;
  state.taggedItems = [];
  state.checkedTagItemIds.clear();
  setTagsStatus(`Tag "${deletedTagName}" deleted.`);
  await loadTags();
  await loadItems();
  renderTaggedItems();
}

async function applyBulkTagUpdate() {
  if (!state.activeTag) {
    setTagsStatus("Select a tag first.");
    return;
  }

  const itemIds = [...state.checkedTagItemIds];
  if (!itemIds.length) {
    setTagsStatus("Check at least one item before applying bulk update.");
    return;
  }

  const addTags = parseTagInput($("bulkAddTagsInput").value);
  const removeTags = parseTagInput($("bulkRemoveTagsInput").value);
  if (!addTags.length && !removeTags.length) {
    setTagsStatus("Enter tags to add or remove.");
    return;
  }

  const result = await api("/api/tags/bulk-update", {
    method: "POST",
    body: JSON.stringify({
      item_ids: itemIds,
      add_tags: addTags,
      remove_tags: removeTags,
    }),
  });

  $("bulkAddTagsInput").value = "";
  $("bulkRemoveTagsInput").value = "";
  setTagsStatus(`Bulk update applied to ${result.updated_items || 0} item(s).`);

  await loadTags();
  await loadTaggedItems();
  await loadItems();
}

async function browseRoot() {
  if (!state.hasBridge || !window.pywebview?.api?.pick_folder) return;
  const result = await window.pywebview.api.pick_folder();
  if (!result || typeof result !== "object") return;
  $("rootPathInput").value = result.root_path || $("rootPathInput").value || "";
}

function scanStatusText(scan) {
  const status = String(scan?.status || "idle");
  const message = String(scan?.message || "");
  const error = String(scan?.error || "");

  if (status === "failed") {
    return error || message || "Scan failed.";
  }
  if (ACTIVE_SCAN_STATUSES.has(status) || status === "completed") {
    return message || "Scanning...";
  }
  return "No scan started yet.";
}

function applyScanStatus(scan) {
  const status = String(scan?.status || "idle");
  const runId = String(scan?.run_id || "");
  const isActive = ACTIVE_SCAN_STATUSES.has(status);

  $("scanButton").textContent = isActive ? "Restart scan" : "Scan library";
  $("scanStatus").textContent = scanStatusText(scan);

  if (!isActive && status === "completed" && runId && runId !== state.lastLoadedRunId) {
    state.lastLoadedRunId = runId;
    Promise.all([
      loadItems(),
      loadTags(),
      state.activeTag ? loadTaggedItems() : Promise.resolve(),
    ]).catch((error) => {
      $("scanStatus").textContent = error.message;
    });
  }

  if (!isActive && state.scanPollTimer) {
    clearInterval(state.scanPollTimer);
    state.scanPollTimer = null;
  }
}

async function pollScanStatus() {
  const scan = await api("/api/scan/status");
  applyScanStatus(scan);
  return scan;
}

function ensureScanPolling() {
  if (state.scanPollTimer) return;
  state.scanPollTimer = setInterval(() => {
    pollScanStatus().catch((error) => {
      $("scanStatus").textContent = error.message;
    });
  }, 500);
}

async function scanLibrary() {
  $("scanButton").disabled = true;
  try {
    await saveRootPath();
    const scan = await api("/api/scan", { method: "POST" });
    applyScanStatus(scan);
    ensureScanPolling();
    await pollScanStatus();
  } catch (error) {
    $("scanStatus").textContent = error.message;
  } finally {
    $("scanButton").disabled = false;
  }
}

function detectBridge() {
  state.hasBridge = Boolean(window.pywebview && window.pywebview.api);
  $("browseButton").disabled = !state.hasBridge;
}

let searchTimer = null;
function queueSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    Promise.all([
      loadItems(),
      state.currentView === "tags" && state.activeTag
        ? loadTaggedItems()
        : Promise.resolve(),
    ]).catch((error) => {
      $("scanStatus").textContent = error.message;
    });
  }, 180);
}

let tagSearchTimer = null;
function queueTagSearch() {
  clearTimeout(tagSearchTimer);
  tagSearchTimer = setTimeout(() => {
    loadTags()
      .then(() => (state.activeTag ? loadTaggedItems() : Promise.resolve()))
      .catch((error) => {
        setTagsStatus(error.message);
      });
  }, 180);
}

async function init() {
  $("viewBrowseButton").addEventListener("click", () => setView("browse"));
  $("viewTagsButton").addEventListener("click", () => {
    setView("tags");
    Promise.all([
      loadTags(),
      state.activeTag ? loadTaggedItems() : Promise.resolve(),
    ]).catch((error) => {
      setTagsStatus(error.message);
    });
  });
  $("saveRootButton").addEventListener("click", () => saveRootPath().catch((error) => {
    $("scanStatus").textContent = error.message;
  }));
  $("browseButton").addEventListener("click", () => browseRoot().catch((error) => {
    $("scanStatus").textContent = error.message;
  }));
  $("scanButton").addEventListener("click", () => scanLibrary().catch((error) => {
    $("scanStatus").textContent = error.message;
  }));
  $("saveItemButton").addEventListener("click", () => saveItem().catch((error) => {
    $("scanStatus").textContent = error.message;
  }));
  $("searchInput").addEventListener("input", queueSearch);
  $("typeFilter").addEventListener("change", queueSearch);
  $("sortFilter").addEventListener("change", queueSearch);
  $("tagSearchInput").addEventListener("input", queueTagSearch);
  $("renameTagButton").addEventListener("click", () => renameActiveTag().catch((error) => {
    setTagsStatus(error.message);
  }));
  $("deleteTagButton").addEventListener("click", () => deleteActiveTag().catch((error) => {
    setTagsStatus(error.message);
  }));
  $("bulkApplyButton").addEventListener("click", () => applyBulkTagUpdate().catch((error) => {
    setTagsStatus(error.message);
  }));

  detectBridge();
  setInterval(detectBridge, 1000);

  setView("browse");
  await loadConfig();
  await Promise.all([loadItems(), loadTags()]);
  renderTaggedItems();
  try {
    const scan = await pollScanStatus();
    if (ACTIVE_SCAN_STATUSES.has(String(scan?.status || ""))) {
      ensureScanPolling();
    }
  } catch (error) {
    $("scanStatus").textContent = error.message;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  init().catch((error) => {
    $("scanStatus").textContent = error.message;
  });
});
