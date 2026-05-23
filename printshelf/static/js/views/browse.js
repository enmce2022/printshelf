import { api } from "../api.js";
import { state } from "../state.js";
import {
  $,
  buildItemQueryParams,
  escapeHtml,
  formatBytes,
  pluralize,
} from "../utils.js";
import { toast } from "../ui/toast.js";
import { confirmDialog, messageDialog, promptDialog } from "../ui/modal.js";
import { createTagInput } from "../ui/tag-input.js";

let tagInput = null;
let tagsLoadCallback = null;

const AUTO_OPEN_THRESHOLD = 20;
const COLLAPSE_STORAGE_KEY = "psf-group-collapse";
const UNCATEGORIZED_LABEL = "Uncategorized";

export function setTagsLoadCallback(callback) {
  tagsLoadCallback = callback;
}

function getTagSuggestions() {
  return state.tags.map((t) => t.name);
}

function findItemById(id) {
  return state.items.find((item) => item.id === id) || null;
}

function loadCollapseMap() {
  try {
    const raw = window.localStorage?.getItem(COLLAPSE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {};
  }
}

function saveCollapseMap(map) {
  try {
    window.localStorage?.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify(map));
  } catch (_) {
    // localStorage unavailable; collapse state is just session-only then.
  }
}

function setStoredCollapse(groupPath, isOpen) {
  const map = loadCollapseMap();
  map[groupPath] = isOpen ? "open" : "closed";
  saveCollapseMap(map);
}

function hasActiveFilter() {
  return (
    Boolean($("searchInput").value.trim()) ||
    Boolean($("typeFilter").value)
  );
}

function shouldGroupBeOpen(groupPath, itemCount, collapseMap) {
  const stored = collapseMap[groupPath];
  if (stored === "open") return true;
  if (stored === "closed") return false;
  if (hasActiveFilter()) return true;
  return itemCount <= AUTO_OPEN_THRESHOLD;
}

function buildEmptyStateHtml() {
  const hasRoot = Boolean(state.rootPath);
  const hasScanned = Boolean(state.lastLoadedRunId);
  const filtered =
    Boolean($("searchInput").value.trim()) ||
    Boolean($("typeFilter").value);

  if (!hasRoot) {
    return `
      <h2>No library folder selected</h2>
      <p>Pick a folder in the sidebar under <strong>Library</strong> to get started.</p>
    `;
  }
  if (!hasScanned) {
    return `
      <h2>Library not scanned yet</h2>
      <p>Run a scan from the sidebar to index your STL and G-code files.</p>
    `;
  }
  if (filtered) {
    return `
      <h2>No items match your filters</h2>
      <p>Try clearing search or changing the file type.</p>
    `;
  }
  return `
    <h2>No items found</h2>
    <p>The last scan didn't find any STL or G-code files in this folder.</p>
  `;
}

function renderSkeletons() {
  const grid = $("catalogGrid");
  grid.innerHTML = "";
  $("emptyState").classList.add("hidden");
  const inner = document.createElement("div");
  inner.className = "catalog-grid";
  for (let i = 0; i < 8; i += 1) {
    const card = document.createElement("article");
    card.className = "card card-skeleton";
    card.innerHTML = `
      <div class="card-preview skeleton-block"></div>
      <div class="card-body">
        <div class="skeleton-line skeleton-line-short"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line skeleton-line-medium"></div>
      </div>
    `;
    inner.appendChild(card);
  }
  grid.appendChild(inner);
}

function renderCard(item) {
  const card = document.createElement("article");
  card.className = "card";
  card.dataset.itemId = String(item.id);
  card.setAttribute("role", "option");
  if (item.id === state.selectedItemId) {
    card.classList.add("selected");
    card.setAttribute("aria-selected", "true");
  } else {
    card.setAttribute("aria-selected", "false");
  }
  if (state.selectedItemIds.has(item.id)) {
    card.classList.add("checked");
  }

  const tagsHtml = (item.tags || [])
    .slice(0, 6)
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join("");

  const checkboxHtml = state.selectionMode
    ? `<label class="card-check" aria-label="Select item">
         <input type="checkbox" data-item-checkbox="${item.id}"
                ${state.selectedItemIds.has(item.id) ? "checked" : ""}>
       </label>`
    : "";

  card.innerHTML = `
    ${checkboxHtml}
    <div class="card-preview">
      ${item.preview_url ? `<img loading="lazy" src="${escapeHtml(item.preview_url)}" alt="">` : ""}
    </div>
    <div class="card-body">
      <div class="row card-meta-row">
        <div class="pill">${escapeHtml(item.file_type.toUpperCase())}</div>
        <div class="muted">${escapeHtml(formatBytes(item.size_bytes))}</div>
      </div>
      <div class="card-title">${escapeHtml(item.filename)}</div>
      <div class="card-path">${escapeHtml(item.relative_path)}</div>
      <div class="card-description">${escapeHtml(item.description || "No description yet.")}</div>
      <div class="tag-list">${tagsHtml}</div>
    </div>
  `;
  return card;
}

function buildGroupBuckets(items) {
  // Map<group_path, items[]> preserving server-provided item order.
  const buckets = new Map();
  for (const item of items) {
    const key = item.group_path ?? "";
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(item);
  }
  return buckets;
}

function lookupGroupMeta(groupPath) {
  return state.groups.find((g) => g.group_path === groupPath) || null;
}

function renderGroupSection(groupPath, items, collapseMap) {
  const meta = lookupGroupMeta(groupPath);
  const displayName =
    (meta && meta.display_name) ||
    (groupPath
      ? groupPath.split("/").filter(Boolean).pop() || groupPath
      : UNCATEGORIZED_LABEL);
  const hasAlias = Boolean(meta && meta.has_alias);
  const isOpen = shouldGroupBeOpen(groupPath, items.length, collapseMap);

  const details = document.createElement("details");
  details.className = "group";
  details.dataset.groupPath = groupPath;
  if (isOpen) details.open = true;

  const breadcrumb = groupPath
    ? `<span class="muted breadcrumb" title="${escapeHtml(groupPath)}">${escapeHtml(groupPath)}</span>`
    : "";
  const resetButton = hasAlias
    ? `<button class="icon-button group-reset" type="button" data-group-reset
               title="Reset to folder name" aria-label="Reset to folder name">↺</button>`
    : "";

  const summary = document.createElement("summary");
  summary.innerHTML = `
    <span class="group-chevron" aria-hidden="true">▸</span>
    <span class="group-title">${escapeHtml(displayName)}</span>
    ${breadcrumb}
    <span class="pill group-count">${items.length}</span>
    <span class="group-actions">
      <button class="icon-button group-rename" type="button" data-group-rename
              title="Rename group" aria-label="Rename group">✎</button>
      ${resetButton}
    </span>
  `;
  details.appendChild(summary);

  const grid = document.createElement("div");
  grid.className = "catalog-grid";
  for (const item of items) {
    grid.appendChild(renderCard(item));
  }
  details.appendChild(grid);

  details.addEventListener("toggle", () => {
    setStoredCollapse(groupPath, details.open);
  });

  return details;
}

function renderCatalog() {
  const grid = $("catalogGrid");
  const empty = $("emptyState");
  grid.innerHTML = "";
  grid.classList.toggle("selection-mode", state.selectionMode);

  if (!state.items.length) {
    empty.innerHTML = buildEmptyStateHtml();
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");

  const buckets = buildGroupBuckets(state.items);
  const orderedKeys = Array.from(buckets.keys()).sort((a, b) => {
    if (a === b) return 0;
    if (a === "") return 1;
    if (b === "") return -1;
    const metaA = lookupGroupMeta(a);
    const metaB = lookupGroupMeta(b);
    const nameA = (
      (metaA && metaA.display_name) ||
      a.split("/").pop() ||
      a
    ).toLowerCase();
    const nameB = (
      (metaB && metaB.display_name) ||
      b.split("/").pop() ||
      b
    ).toLowerCase();
    return nameA.localeCompare(nameB);
  });

  const collapseMap = loadCollapseMap();
  const fragment = document.createDocumentFragment();
  for (const key of orderedKeys) {
    fragment.appendChild(renderGroupSection(key, buckets.get(key), collapseMap));
  }
  grid.appendChild(fragment);
}

function selectCard(itemId) {
  const previous = state.selectedItemId;
  if (previous === itemId) return;
  state.selectedItemId = itemId;
  const grid = $("catalogGrid");
  if (previous != null) {
    const prevNode = grid.querySelector(`[data-item-id="${previous}"]`);
    if (prevNode) {
      prevNode.classList.remove("selected");
      prevNode.setAttribute("aria-selected", "false");
    }
  }
  if (itemId != null) {
    const nextNode = grid.querySelector(`[data-item-id="${itemId}"]`);
    if (nextNode) {
      nextNode.classList.add("selected");
      nextNode.setAttribute("aria-selected", "true");
    }
  }
}

function updateBulkBar() {
  const bar = $("bulkGroupBar");
  const count = state.selectedItemIds.size;
  if (!state.selectionMode || count === 0) {
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  $("bulkSelectionCount").textContent = `${count} selected`;
}

function clearSelectedItemIds() {
  state.selectedItemIds.clear();
  updateBulkBar();
  // Refresh card visuals without a full re-render.
  document
    .querySelectorAll("#catalogGrid .card.checked")
    .forEach((node) => node.classList.remove("checked"));
  document
    .querySelectorAll("#catalogGrid input[data-item-checkbox]")
    .forEach((node) => {
      node.checked = false;
    });
}

function setSelectionMode(active) {
  state.selectionMode = active;
  const toggle = $("selectionModeToggle");
  if (toggle) {
    toggle.classList.toggle("active", active);
    toggle.setAttribute("aria-pressed", String(active));
  }
  if (!active) state.selectedItemIds.clear();
  renderCatalog();
  updateBulkBar();
}

function toggleItemSelection(itemId, isChecked) {
  if (isChecked) {
    state.selectedItemIds.add(itemId);
  } else {
    state.selectedItemIds.delete(itemId);
  }
  const card = document
    .getElementById("catalogGrid")
    .querySelector(`.card[data-item-id="${itemId}"]`);
  if (card) card.classList.toggle("checked", isChecked);
  updateBulkBar();
}

function buildGroupSuggestionsHtml() {
  const groups = (state.groups || []).filter((g) => g.group_path);
  if (!groups.length) return "";
  const items = groups
    .map((g) => {
      const label = g.display_name || g.group_path;
      return `<li><button type="button" class="group-suggestion" data-group-path="${escapeHtml(g.group_path)}">
        <strong>${escapeHtml(label)}</strong>
        <span class="muted small">${escapeHtml(g.group_path)}</span>
        <span class="muted small">${g.item_count} ${pluralize(g.item_count, "item")}</span>
      </button></li>`;
    })
    .join("");
  return `<p class="muted small">Existing groups (click to pick):</p>
          <ul class="group-suggestion-list">${items}</ul>`;
}

async function pickGroupOverride({
  title = "Move to group",
  message = "Type a folder path relative to your library root, or pick a known group below. Leave blank for Uncategorized.",
  initialValue = "",
  allowReset = true,
} = {}) {
  // Returns: { path: string|null|undefined }
  //   path === undefined → user canceled
  //   path === null      → reset override (use derived path)
  //   path === ""        → explicit Uncategorized (override = "")
  //   path === "<text>"  → override to that string
  const suggestionsHtml = buildGroupSuggestionsHtml();
  const inputId = `group-picker-input-${Date.now()}`;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML = `
    <div class="modal modal-wide" tabindex="-1">
      <div class="modal-header">
        <h2 class="modal-title">${escapeHtml(title)}</h2>
      </div>
      <div class="modal-body">
        <p class="modal-message">${escapeHtml(message)}</p>
        <input id="${inputId}" type="text" class="modal-input"
               value="${escapeHtml(initialValue)}"
               placeholder="e.g. household_utility/storage/box-organizer">
        ${suggestionsHtml}
      </div>
      <div class="modal-footer">
        ${allowReset ? '<button type="button" class="button secondary" data-action="reset">Reset to derived</button>' : ""}
        <button type="button" class="button secondary" data-action="cancel">Cancel</button>
        <button type="button" class="button primary" data-action="confirm">Move</button>
      </div>
    </div>
  `;

  return new Promise((resolve) => {
    const previouslyFocused = document.activeElement;

    function close(value) {
      document.removeEventListener("keydown", onKeydown, true);
      overlay.classList.add("modal-leaving");
      setTimeout(() => {
        overlay.remove();
        if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
      }, 140);
      resolve(value);
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close({ path: undefined });
      } else if (event.key === "Enter" && document.activeElement.id === inputId) {
        event.preventDefault();
        close({ path: overlay.querySelector(`#${inputId}`).value });
      }
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close({ path: undefined });
    });

    overlay.querySelectorAll(".group-suggestion").forEach((node) => {
      node.addEventListener("click", () => {
        overlay.querySelector(`#${inputId}`).value = node.dataset.groupPath;
        overlay.querySelector(`#${inputId}`).focus();
      });
    });

    overlay
      .querySelector('[data-action="cancel"]')
      .addEventListener("click", () => close({ path: undefined }));
    overlay
      .querySelector('[data-action="confirm"]')
      .addEventListener("click", () =>
        close({ path: overlay.querySelector(`#${inputId}`).value }),
      );
    if (allowReset) {
      overlay
        .querySelector('[data-action="reset"]')
        .addEventListener("click", () => close({ path: null }));
    }

    document.addEventListener("keydown", onKeydown, true);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add("modal-shown"));
    overlay.querySelector(`#${inputId}`).focus();
  });
}

function validateMetaJson(value) {
  const errorNode = $("metaError");
  const text = value.trim();
  if (!text) {
    errorNode.classList.add("hidden");
    errorNode.textContent = "";
    $("saveItemButton").disabled = state.saveInFlight;
    return { valid: true, parsed: {} };
  }
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      errorNode.classList.add("hidden");
      errorNode.textContent = "";
      $("saveItemButton").disabled = state.saveInFlight;
      return { valid: true, parsed };
    }
    errorNode.textContent = "Custom metadata must be a JSON object.";
    errorNode.classList.remove("hidden");
    $("saveItemButton").disabled = true;
    return { valid: false };
  } catch (error) {
    errorNode.textContent = `Invalid JSON: ${error.message}`;
    errorNode.classList.remove("hidden");
    $("saveItemButton").disabled = true;
    return { valid: false };
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
  $("detailPath").dataset.path = item.path;
  $("detailPreviewSource").textContent = item.preview_source || "unknown";
  $("detailSize").textContent = formatBytes(item.size_bytes);
  $("descriptionInput").value = item.description || "";
  $("metaInput").value = JSON.stringify(item.meta || {}, null, 2);
  $("indexedMeta").textContent = JSON.stringify(item.indexed_meta || {}, null, 2);
  validateMetaJson($("metaInput").value);

  $("detailGroupName").textContent = item.group_display || UNCATEGORIZED_LABEL;
  $("detailGroupPath").textContent = item.group_path || "";
  const changeBtn = $("changeGroupButton");
  if (changeBtn) {
    changeBtn.dataset.groupPath = item.group_path || "";
    changeBtn.dataset.hasOverride = item.group_override !== null && item.group_override !== undefined ? "1" : "";
  }

  if (tagInput) {
    tagInput.setSuggestions(getTagSuggestions());
    tagInput.setTags(item.tags || []);
  }

  const nativeButtons = [
    $("revealItemButton"),
    $("openItemButton"),
  ];
  const hasNative = state.hasBridge;
  for (const button of nativeButtons) {
    if (!button) continue;
    button.disabled = !hasNative;
    button.title = hasNative
      ? ""
      : "Native actions are only available in desktop mode.";
  }
}

export async function loadGroups() {
  try {
    state.groups = await api("/api/groups");
  } catch (error) {
    // Non-fatal: the catalog still renders with derived display names.
    state.groups = [];
  }
}

export async function loadItems({ skeleton = false } = {}) {
  if (skeleton) renderSkeletons();
  state.itemsLoading = true;
  try {
    const [items] = await Promise.all([
      api(`/api/items?${buildItemQueryParams()}`),
      loadGroups(),
    ]);
    state.items = items;
    state.itemsLoading = false;
    // Drop selection-mode picks that fell out of the current view.
    if (state.selectionMode) {
      const visibleIds = new Set(items.map((it) => it.id));
      for (const id of Array.from(state.selectedItemIds)) {
        if (!visibleIds.has(id)) state.selectedItemIds.delete(id);
      }
    }
    renderCatalog();
    updateBulkBar();
    $("resultCount").textContent = `${items.length} ${pluralize(
      items.length,
      "item",
    )}`;
    if (!items.some((item) => item.id === state.selectedItemId)) {
      state.selectedItemId = null;
      renderDetail(null);
    } else {
      const refreshed = items.find((it) => it.id === state.selectedItemId);
      if (refreshed) renderDetail(refreshed);
    }
  } catch (error) {
    state.itemsLoading = false;
    toast.error(error.message);
    throw error;
  }
}

async function renameGroupPrompt(groupPath) {
  const meta = lookupGroupMeta(groupPath);
  const currentDisplay =
    (meta && meta.display_name) ||
    (groupPath ? groupPath.split("/").pop() : UNCATEGORIZED_LABEL);
  const newName = await promptDialog({
    title: "Rename group",
    message:
      groupPath === ""
        ? "Set a display name for files at the library root."
        : `Folder: ${groupPath}`,
    initialValue: currentDisplay || "",
    placeholder: "Display name",
    confirmLabel: "Save",
  });
  if (newName === null) return;
  const trimmed = String(newName).trim();
  if (!trimmed) {
    toast.error("Display name cannot be empty.");
    return;
  }
  try {
    await api("/api/groups", {
      method: "PATCH",
      body: JSON.stringify({ group_path: groupPath, display_name: trimmed }),
    });
    toast.success("Group renamed.");
    await loadItems();
  } catch (error) {
    toast.error(error.message);
  }
}

async function resetGroupDisplay(groupPath) {
  const confirmed = await confirmDialog({
    title: "Reset display name?",
    message: "The folder name will be shown instead of the alias.",
    confirmLabel: "Reset",
  });
  if (!confirmed) return;
  try {
    await api("/api/groups", {
      method: "PATCH",
      body: JSON.stringify({ group_path: groupPath, display_name: null }),
    });
    toast.success("Display name reset.");
    await loadItems();
  } catch (error) {
    toast.error(error.message);
  }
}

async function changeGroupForSelected() {
  if (!state.selectedItemId) return;
  const result = await pickGroupOverride({
    title: "Move item to group",
    initialValue: "",
  });
  if (result.path === undefined) return;
  try {
    const updated = await api(`/api/items/${state.selectedItemId}`, {
      method: "PUT",
      body: JSON.stringify({
        description: $("descriptionInput").value,
        tags: tagInput ? tagInput.getTags() : [],
        meta: JSON.parse($("metaInput").value || "{}"),
        group_override: result.path,
      }),
    });
    renderDetail(updated);
    toast.success("Group updated.");
    await loadItems();
  } catch (error) {
    toast.error(error.message);
  }
}

async function bulkMoveSelected() {
  if (!state.selectedItemIds.size) return;
  const result = await pickGroupOverride({
    title: `Move ${state.selectedItemIds.size} items to group`,
    initialValue: "",
  });
  if (result.path === undefined) return;
  try {
    const response = await api("/api/items/bulk-group", {
      method: "POST",
      body: JSON.stringify({
        item_ids: Array.from(state.selectedItemIds),
        group_override: result.path,
      }),
    });
    toast.success(`${response.updated} ${pluralize(response.updated, "item")} moved.`);
    state.selectedItemIds.clear();
    await loadItems();
  } catch (error) {
    toast.error(error.message);
  }
}

function expandAllGroups(open) {
  const map = loadCollapseMap();
  document
    .querySelectorAll("#catalogGrid details.group")
    .forEach((details) => {
      const groupPath = details.dataset.groupPath || "";
      details.open = open;
      map[groupPath] = open ? "open" : "closed";
    });
  saveCollapseMap(map);
}

async function saveItem() {
  if (!state.selectedItemId || state.saveInFlight) return;

  if (tagInput) tagInput.flushPending();

  const validation = validateMetaJson($("metaInput").value);
  if (!validation.valid) {
    toast.error("Fix the JSON metadata before saving.");
    return;
  }

  state.saveInFlight = true;
  $("saveItemButton").disabled = true;
  $("saveItemButton").classList.add("loading");

  try {
    const payload = {
      description: $("descriptionInput").value,
      tags: tagInput ? tagInput.getTags() : [],
      meta: validation.parsed,
    };
    const updated = await api(`/api/items/${state.selectedItemId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderDetail(updated);
    toast.success("Saved.");
    await loadItems();
    if (tagsLoadCallback) {
      Promise.resolve(tagsLoadCallback()).catch(() => {});
    }
  } catch (error) {
    toast.error(error.message);
  } finally {
    state.saveInFlight = false;
    $("saveItemButton").classList.remove("loading");
    $("saveItemButton").disabled = false;
  }
}

async function copyDetailPath() {
  const path = $("detailPath").dataset.path || $("detailPath").textContent;
  if (!path) return;
  try {
    await navigator.clipboard.writeText(path);
    toast.success("Path copied to clipboard.");
  } catch (_) {
    toast.error("Could not copy to clipboard.");
  }
}

async function callBridge(method, ...args) {
  const bridge = window.pywebview?.api;
  if (!bridge || typeof bridge[method] !== "function") {
    await messageDialog({
      title: "Desktop only",
      message: "This action is only available when running PrintShelf as a desktop app.",
    });
    return null;
  }
  return bridge[method](...args);
}

async function revealInExplorer() {
  const path = $("detailPath").dataset.path;
  if (!path) return;
  try {
    const result = await callBridge("reveal_in_explorer", path);
    if (result && result.error) toast.error(result.error);
  } catch (error) {
    toast.error(error.message || "Could not open file location.");
  }
}

async function openExternally() {
  const path = $("detailPath").dataset.path;
  if (!path) return;
  try {
    const result = await callBridge("open_file", path);
    if (result && result.error) toast.error(result.error);
  } catch (error) {
    toast.error(error.message || "Could not open file.");
  }
}

export function initBrowseView() {
  tagInput = createTagInput($("tagsInputHost"), {
    placeholder: "Add a tag and press Enter",
    suggestions: getTagSuggestions(),
  });

  $("catalogGrid").addEventListener("click", async (event) => {
    const renameButton = event.target.closest("[data-group-rename]");
    if (renameButton) {
      event.preventDefault();
      event.stopPropagation();
      const details = renameButton.closest("details.group");
      if (details) await renameGroupPrompt(details.dataset.groupPath || "");
      return;
    }
    const resetButton = event.target.closest("[data-group-reset]");
    if (resetButton) {
      event.preventDefault();
      event.stopPropagation();
      const details = resetButton.closest("details.group");
      if (details) await resetGroupDisplay(details.dataset.groupPath || "");
      return;
    }
    const checkbox = event.target.closest("[data-item-checkbox]");
    if (checkbox) {
      // Let the native change event handle state; just don't treat it as card-click.
      event.stopPropagation();
      return;
    }
    const card = event.target.closest("[data-item-id]");
    if (!card) return;
    const itemId = Number(card.dataset.itemId);
    selectCard(itemId);
    const item = findItemById(itemId);
    if (item) renderDetail(item);
  });

  $("catalogGrid").addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-item-checkbox]");
    if (!checkbox) return;
    const itemId = Number(checkbox.dataset.itemCheckbox);
    toggleItemSelection(itemId, checkbox.checked);
  });

  $("selectionModeToggle").addEventListener("click", () => {
    setSelectionMode(!state.selectionMode);
  });

  $("expandAllGroupsButton").addEventListener("click", () => expandAllGroups(true));
  $("collapseAllGroupsButton").addEventListener("click", () => expandAllGroups(false));

  $("bulkMoveButton").addEventListener("click", bulkMoveSelected);
  $("bulkClearButton").addEventListener("click", () => clearSelectedItemIds());

  $("changeGroupButton").addEventListener("click", changeGroupForSelected);

  $("metaInput").addEventListener("input", (event) => {
    validateMetaJson(event.target.value);
  });

  $("saveItemButton").addEventListener("click", () => {
    saveItem();
  });

  $("copyPathButton").addEventListener("click", copyDetailPath);
  $("revealItemButton").addEventListener("click", revealInExplorer);
  $("openItemButton").addEventListener("click", openExternally);
}

export function refreshTagSuggestions() {
  if (tagInput) tagInput.setSuggestions(getTagSuggestions());
}
