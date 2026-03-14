const state = {
  items: [],
  selectedItemId: null,
  hasBridge: false,
  scanPollTimer: null,
  lastLoadedRunId: null,
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

async function loadItems() {
  const q = encodeURIComponent($("searchInput").value.trim());
  const fileType = encodeURIComponent($("typeFilter").value);
  const sort = encodeURIComponent($("sortFilter").value || "date_added_desc");
  const items = await api(`/api/items?q=${q}&file_type=${fileType}&sort=${sort}`);
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
    loadItems().catch((error) => {
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
    loadItems().catch((error) => {
      $("scanStatus").textContent = error.message;
    });
  }, 180);
}

async function init() {
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

  detectBridge();
  setInterval(detectBridge, 1000);

  await loadConfig();
  await loadItems();
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
