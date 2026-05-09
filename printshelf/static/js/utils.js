export const $ = (id) => document.getElementById(id);

export function formatBytes(bytes) {
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

export function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function parseTagInput(value) {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

export function buildItemQueryParams({ tag = "" } = {}) {
  const params = new URLSearchParams();
  params.set("q", $("searchInput").value.trim());
  params.set("file_type", $("typeFilter").value);
  params.set("sort", $("sortFilter").value || "date_added_desc");
  if (tag) params.set("tag", tag);
  return params.toString();
}

export function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function pluralize(count, singular, plural) {
  return count === 1 ? singular : (plural ?? `${singular}s`);
}
