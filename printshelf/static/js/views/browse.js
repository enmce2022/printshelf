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
import { messageDialog } from "../ui/modal.js";
import { createTagInput } from "../ui/tag-input.js";

let tagInput = null;
let tagsLoadCallback = null;

export function setTagsLoadCallback(callback) {
  tagsLoadCallback = callback;
}

function getTagSuggestions() {
  return state.tags.map((t) => t.name);
}

function findItemById(id) {
  return state.items.find((item) => item.id === id) || null;
}

function buildEmptyStateHtml() {
  const root = $("rootPathInput").value.trim();
  const hasRoot = Boolean(root);
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
    grid.appendChild(card);
  }
}

function renderCatalog() {
  const grid = $("catalogGrid");
  const empty = $("emptyState");
  grid.innerHTML = "";

  if (!state.items.length) {
    empty.innerHTML = buildEmptyStateHtml();
    empty.classList.remove("hidden");
    return;
  }

  empty.classList.add("hidden");

  const fragment = document.createDocumentFragment();
  for (const item of state.items) {
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

    const tagsHtml = (item.tags || [])
      .slice(0, 6)
      .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
      .join("");

    card.innerHTML = `
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
    fragment.appendChild(card);
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

export async function loadItems({ skeleton = false } = {}) {
  if (skeleton) renderSkeletons();
  state.itemsLoading = true;
  try {
    const items = await api(`/api/items?${buildItemQueryParams()}`);
    state.items = items;
    state.itemsLoading = false;
    renderCatalog();
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
    const card = event.target.closest("[data-item-id]");
    if (!card) return;
    const itemId = Number(card.dataset.itemId);
    selectCard(itemId);
    const item = findItemById(itemId);
    if (item) renderDetail(item);
  });

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
