import { api } from "../api.js";
import { ACTIVE_SCAN_STATUSES, state } from "../state.js";
import { $ } from "../utils.js";
import { toast } from "../ui/toast.js";

const POLL_ACTIVE_MS = 500;
const POLL_IDLE_MS = 2000;

let onCompletedRunCallback = null;

export function setOnCompletedRun(callback) {
  onCompletedRunCallback = callback;
}

function setScanStatus(message) {
  $("scanStatus").textContent = message || "";
}

function scanStatusText(scan) {
  const status = String(scan?.status || "idle");
  const message = String(scan?.message || "");
  const error = String(scan?.error || "");

  if (status === "failed") {
    return error || message || "Scan failed.";
  }
  if (status === "paused") {
    return message || "Paused.";
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
  const percent = Number.isFinite(scan?.progress_percent)
    ? Math.max(0, Math.min(100, Number(scan.progress_percent)))
    : 0;

  const scanButton = $("scanButton");
  scanButton.textContent = isActive ? "Restart scan" : "Scan library";
  $("cancelScanButton").classList.toggle("hidden", !isActive);
  $("cancelScanButton").disabled = status === "canceling";

  const pauseResumeButton = $("pauseResumeButton");
  if (pauseResumeButton) {
    const showPauseResume = isActive && status !== "canceling";
    pauseResumeButton.classList.toggle("hidden", !showPauseResume);
    if (status === "paused") {
      pauseResumeButton.textContent = "▶";
      pauseResumeButton.title = "Resume";
      pauseResumeButton.setAttribute("aria-label", "Resume");
      pauseResumeButton.dataset.action = "resume";
    } else {
      pauseResumeButton.textContent = "⏸";
      pauseResumeButton.title = "Pause";
      pauseResumeButton.setAttribute("aria-label", "Pause");
      pauseResumeButton.dataset.action = "pause";
    }
    pauseResumeButton.disabled = false;
  }

  setScanStatus(scanStatusText(scan));

  const bar = $("scanProgressBar");
  const fill = $("scanProgressFill");
  if (bar && fill) {
    bar.classList.toggle("hidden", !isActive && status !== "completed");
    fill.style.width = `${percent}%`;
    bar.setAttribute("aria-valuenow", String(Math.round(percent)));
    bar.classList.toggle("scan-progress-canceling", status === "canceling");
  }

  if (
    !isActive &&
    status === "completed" &&
    runId &&
    runId !== state.lastLoadedRunId
  ) {
    state.lastLoadedRunId = runId;
    if (onCompletedRunCallback) {
      Promise.resolve(onCompletedRunCallback()).catch((error) => {
        toast.error(error.message);
      });
    }
  }

  return isActive;
}

async function pollScanStatus() {
  const scan = await api("/api/scan/status");
  applyScanStatus(scan);
  return scan;
}

function clearPollTimer() {
  if (state.scanPollTimer) {
    clearInterval(state.scanPollTimer);
    state.scanPollTimer = null;
    state.scanPollIntervalMs = 0;
  }
}

function setPollInterval(ms) {
  if (state.scanPollIntervalMs === ms) return;
  clearPollTimer();
  if (ms <= 0) return;
  state.scanPollIntervalMs = ms;
  state.scanPollTimer = setInterval(() => {
    if (document.hidden) return;
    pollScanStatus()
      .then((scan) => adjustPolling(scan))
      .catch((error) => {
        toast.error(error.message);
      });
  }, ms);
}

function adjustPolling(scan) {
  const status = String(scan?.status || "idle");
  if (ACTIVE_SCAN_STATUSES.has(status)) {
    setPollInterval(POLL_ACTIVE_MS);
  } else if (state.currentView === "browse" || state.currentView === "tags") {
    setPollInterval(POLL_IDLE_MS);
  } else {
    clearPollTimer();
  }
}

export function ensureScanPolling() {
  if (state.scanPollTimer) return;
  setPollInterval(POLL_ACTIVE_MS);
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

async function startScan() {
  if (state.scanInFlight) return;
  state.scanInFlight = true;
  $("scanButton").disabled = true;
  try {
    await saveRootPath();
    const scan = await api("/api/scan", { method: "POST" });
    applyScanStatus(scan);
    ensureScanPolling();
    await pollScanStatus();
  } catch (error) {
    setScanStatus(error.message);
    toast.error(error.message);
  } finally {
    state.scanInFlight = false;
    $("scanButton").disabled = false;
  }
}

async function cancelScan() {
  $("cancelScanButton").disabled = true;
  try {
    const scan = await api("/api/scan/cancel", { method: "POST" });
    applyScanStatus(scan);
    toast.info("Cancel requested.");
  } catch (error) {
    toast.error(error.message);
    $("cancelScanButton").disabled = false;
  }
}

async function togglePauseResume() {
  const button = $("pauseResumeButton");
  if (!button || button.classList.contains("hidden")) return;
  const isResume = button.dataset.action === "resume";
  button.disabled = true;
  try {
    const endpoint = isResume ? "/api/scan/resume" : "/api/scan/pause";
    const scan = await api(endpoint, { method: "POST" });
    applyScanStatus(scan);
    toast.info(isResume ? "Resuming scan." : "Pause requested.");
  } catch (error) {
    toast.error(error.message);
    button.disabled = false;
  }
}

async function saveRootOnly() {
  try {
    await saveRootPath();
    toast.success("Library path saved.");
  } catch (error) {
    toast.error(error.message);
  }
}

export function initScanControls() {
  $("saveRootButton").addEventListener("click", () => {
    saveRootOnly();
  });
  $("browseButton").addEventListener("click", () => {
    browseRoot().catch((error) => toast.error(error.message));
  });
  $("scanButton").addEventListener("click", () => {
    startScan();
  });
  $("cancelScanButton").addEventListener("click", () => {
    cancelScan();
  });
  $("pauseResumeButton").addEventListener("click", () => {
    togglePauseResume();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearPollTimer();
    } else {
      pollScanStatus()
        .then((scan) => adjustPolling(scan))
        .catch((error) => toast.error(error.message));
    }
  });
}

export async function initialScanStatus() {
  try {
    const scan = await pollScanStatus();
    adjustPolling(scan);
    return scan;
  } catch (error) {
    setScanStatus(error.message);
    return null;
  }
}

export async function loadConfig() {
  const config = await api("/api/config");
  $("rootPathInput").value = config.root_path || "";
}
