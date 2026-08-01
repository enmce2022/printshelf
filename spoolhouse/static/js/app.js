import { state } from "./state.js";
import { $, debounce } from "./utils.js";
import { toast } from "./ui/toast.js";
import {
  initBrowseView,
  loadItems,
  refreshTagSuggestions,
  renderCatalog,
  setTagsLoadCallback,
} from "./views/browse.js";
import {
  initTagsView,
  loadTags,
  loadTaggedItems,
  setOnTagsChanged,
} from "./views/tags.js";
import {
  ensureScanPolling,
  initScanControls,
  initialScanStatus,
  loadConfig,
  parseIgnoreDirsInput,
  setIgnoreDirs,
  setOnCompletedRun,
} from "./views/scan.js";

function setView(view) {
  state.currentView = view === "tags" ? "tags" : "browse";
  $("browseView").classList.toggle("hidden", state.currentView !== "browse");
  $("tagsView").classList.toggle("hidden", state.currentView !== "tags");

  const browseTab = $("viewBrowseButton");
  const tagsTab = $("viewTagsButton");
  browseTab.classList.toggle("active", state.currentView === "browse");
  tagsTab.classList.toggle("active", state.currentView === "tags");
  browseTab.setAttribute("aria-selected", state.currentView === "browse");
  tagsTab.setAttribute("aria-selected", state.currentView === "tags");
  browseTab.setAttribute("tabindex", state.currentView === "browse" ? "0" : "-1");
  tagsTab.setAttribute("tabindex", state.currentView === "tags" ? "0" : "-1");
}

const queueSearch = debounce(() => {
  Promise.all([
    loadItems({ skeleton: true }),
    state.currentView === "tags" && state.activeTag
      ? loadTaggedItems()
      : Promise.resolve(),
  ]).catch((error) => toast.error(error.message));
}, 180);

const queueTagSearch = debounce(() => {
  loadTags()
    .then(() => (state.activeTag ? loadTaggedItems() : Promise.resolve()))
    .catch((error) => toast.error(error.message));
}, 180);

// The desktop server may still be bringing a worker online when the webview
// first loads (heavy VTK/pyvista import per worker process). The backend waits
// for a worker before opening the window, but on a slow machine the very first
// requests can still lose the race — so retry the initial load a few times
// before surfacing an error, instead of leaving the UI inert with no data.
async function retryInitial(fn, attempts = 10, delayMs = 500) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }
  throw lastError;
}

function detectBridge() {
  const present = Boolean(window.pywebview && window.pywebview.api);
  state.hasBridge = present;
  const browseButton = $("browseButton");
  browseButton.disabled = !present;
  browseButton.title = present
    ? ""
    : "Native folder picker only available in desktop mode — paste a path or run via `uv run python run.py`.";

  const revealButton = $("revealItemButton");
  const openButton = $("openItemButton");
  if (revealButton) revealButton.disabled = !present || !state.selectedItemId;
  if (openButton) openButton.disabled = !present || !state.selectedItemId;

  if (!state.bridgeDetected && present) {
    state.bridgeDetected = true;
    return true;
  }
  return false;
}

async function init() {
  $("viewBrowseButton").addEventListener("click", () => setView("browse"));
  $("viewTagsButton").addEventListener("click", () => {
    setView("tags");
    Promise.all([
      loadTags(),
      state.activeTag ? loadTaggedItems() : Promise.resolve(),
    ]).catch((error) => toast.error(error.message));
  });

  $("searchInput").addEventListener("input", queueSearch);
  $("typeFilter").addEventListener("change", queueSearch);
  $("sortFilter").addEventListener("change", queueSearch);
  // Within-group sort is a pure client-side re-sort of already-loaded items —
  // re-render only, no server round-trip.
  $("groupSortFilter").addEventListener("change", () => renderCatalog());
  $("tagSearchInput").addEventListener("input", queueTagSearch);

  // Save the ignore-dirs list on blur (so editing a multi-line list doesn't
  // hammer the server) — re-fetches items afterward so groups regroup.
  $("ignoreDirsInput").addEventListener("blur", async (event) => {
    try {
      const patterns = parseIgnoreDirsInput(event.target.value);
      await setIgnoreDirs(patterns);
      await loadItems();
    } catch (error) {
      toast.error(error.message);
    }
  });

  initScanControls();
  initBrowseView();
  initTagsView();

  setTagsLoadCallback(loadTags);
  setOnTagsChanged(refreshTagSuggestions);
  setOnCompletedRun(async () => {
    await Promise.all([
      loadItems(),
      loadTags(),
      state.activeTag ? loadTaggedItems() : Promise.resolve(),
    ]);
  });

  document.addEventListener("spoolhouse:open-item", (event) => {
    const itemId = event.detail?.itemId;
    if (!Number.isFinite(itemId)) return;
    setView("browse");
    state.selectedItemId = itemId;
    loadItems().catch((error) => toast.error(error.message));
  });

  detectBridge();
  const bridgePoll = setInterval(() => {
    const justAppeared = detectBridge();
    if (justAppeared || state.hasBridge) {
      clearInterval(bridgePoll);
    }
  }, 500);
  setTimeout(() => clearInterval(bridgePoll), 10000);

  setView("browse");
  await retryInitial(loadConfig);
  await Promise.all([retryInitial(loadItems), retryInitial(loadTags)]);
  const scan = await initialScanStatus();
  if (scan && ["counting", "running", "canceling"].includes(String(scan.status))) {
    ensureScanPolling();
  }
}

window.addEventListener("DOMContentLoaded", () => {
  init().catch((error) => {
    toast.error(error.message);
  });
});
