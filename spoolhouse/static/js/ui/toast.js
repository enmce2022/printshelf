import { escapeHtml } from "../utils.js";

const DEFAULT_DURATION = 3500;
const ERROR_DURATION = 6000;

let region = null;

function ensureRegion() {
  if (region) return region;
  region = document.getElementById("toastRegion");
  if (!region) {
    region = document.createElement("div");
    region.id = "toastRegion";
    region.className = "toast-region";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    document.body.appendChild(region);
  }
  return region;
}

function show(kind, message, duration) {
  const root = ensureRegion();
  const node = document.createElement("div");
  node.className = `toast toast-${kind}`;
  node.innerHTML = `
    <span class="toast-icon" aria-hidden="true"></span>
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close" type="button" aria-label="Dismiss">×</button>
  `;
  const close = () => {
    node.classList.add("toast-leaving");
    setTimeout(() => node.remove(), 180);
  };
  node.querySelector(".toast-close").addEventListener("click", close);
  root.appendChild(node);
  requestAnimationFrame(() => node.classList.add("toast-shown"));
  if (duration > 0) {
    setTimeout(close, duration);
  }
  return close;
}

export const toast = {
  success(message, duration = DEFAULT_DURATION) {
    return show("success", message, duration);
  },
  error(message, duration = ERROR_DURATION) {
    return show("error", message, duration);
  },
  info(message, duration = DEFAULT_DURATION) {
    return show("info", message, duration);
  },
};
