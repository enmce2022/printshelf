import { escapeHtml } from "../utils.js";

export function createTagInput(host, { placeholder = "Add a tag", suggestions = [] } = {}) {
  host.classList.add("tag-input");
  host.innerHTML = `
    <div class="tag-input-chips" data-chips></div>
    <input class="tag-input-field" type="text" placeholder="${escapeHtml(placeholder)}" autocomplete="off" data-input>
    <div class="tag-input-suggestions hidden" role="listbox" data-suggestions></div>
  `;

  const chipsNode = host.querySelector("[data-chips]");
  const input = host.querySelector("[data-input]");
  const suggestionsNode = host.querySelector("[data-suggestions]");

  let tags = [];
  let pool = suggestions.slice();
  let highlightedIndex = -1;

  function normalize(value) {
    return value.trim().replace(/\s+/g, " ");
  }

  function lower(value) {
    return value.toLocaleLowerCase();
  }

  function getTags() {
    return tags.slice();
  }

  function setTags(next) {
    const seen = new Set();
    tags = [];
    for (const raw of next || []) {
      const value = normalize(String(raw || ""));
      if (!value) continue;
      const key = lower(value);
      if (seen.has(key)) continue;
      seen.add(key);
      tags.push(value);
    }
    renderChips();
    refreshSuggestions();
  }

  function setSuggestions(next) {
    pool = (next || []).map((s) => normalize(String(s || ""))).filter(Boolean);
    refreshSuggestions();
  }

  function renderChips() {
    chipsNode.innerHTML = "";
    for (const [index, tag] of tags.entries()) {
      const chip = document.createElement("span");
      chip.className = "tag-chip";
      chip.innerHTML = `
        <span>${escapeHtml(tag)}</span>
        <button type="button" class="tag-chip-remove" aria-label="Remove ${escapeHtml(
          tag,
        )}" data-index="${index}">×</button>
      `;
      chip.querySelector(".tag-chip-remove").addEventListener("click", () => {
        tags.splice(index, 1);
        renderChips();
        refreshSuggestions();
        emitChange();
      });
      chipsNode.appendChild(chip);
    }
  }

  function refreshSuggestions() {
    const query = lower(input.value.trim());
    const existing = new Set(tags.map(lower));
    const matches = pool.filter((s) => {
      const key = lower(s);
      if (existing.has(key)) return false;
      if (!query) return true;
      return key.includes(query);
    });
    if (!matches.length || document.activeElement !== input) {
      suggestionsNode.classList.add("hidden");
      highlightedIndex = -1;
      return;
    }
    suggestionsNode.innerHTML = matches
      .slice(0, 8)
      .map(
        (s, idx) =>
          `<button type="button" class="tag-suggestion" data-index="${idx}" role="option">${escapeHtml(
            s,
          )}</button>`,
      )
      .join("");
    suggestionsNode.classList.remove("hidden");
    suggestionsNode.querySelectorAll(".tag-suggestion").forEach((node, idx) => {
      node.addEventListener("mousedown", (event) => {
        event.preventDefault();
        addTag(matches[idx]);
      });
    });
    highlightedIndex = -1;
    updateHighlight();
  }

  function updateHighlight() {
    const items = suggestionsNode.querySelectorAll(".tag-suggestion");
    items.forEach((node, idx) => {
      node.classList.toggle("highlighted", idx === highlightedIndex);
    });
  }

  function addTag(value) {
    const normalized = normalize(value);
    if (!normalized) return;
    const key = lower(normalized);
    if (tags.some((t) => lower(t) === key)) {
      input.value = "";
      refreshSuggestions();
      return;
    }
    tags.push(normalized);
    input.value = "";
    renderChips();
    refreshSuggestions();
    emitChange();
  }

  function emitChange() {
    host.dispatchEvent(new CustomEvent("tagschange", { detail: { tags: tags.slice() } }));
  }

  input.addEventListener("input", refreshSuggestions);
  input.addEventListener("focus", refreshSuggestions);
  input.addEventListener("blur", () => {
    setTimeout(() => suggestionsNode.classList.add("hidden"), 100);
  });
  input.addEventListener("keydown", (event) => {
    const items = suggestionsNode.querySelectorAll(".tag-suggestion");
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      if (highlightedIndex >= 0 && items[highlightedIndex]) {
        addTag(items[highlightedIndex].textContent);
      } else if (input.value.trim()) {
        addTag(input.value);
      }
    } else if (event.key === "Backspace" && !input.value && tags.length) {
      tags.pop();
      renderChips();
      refreshSuggestions();
      emitChange();
    } else if (event.key === "ArrowDown" && items.length) {
      event.preventDefault();
      highlightedIndex = Math.min(highlightedIndex + 1, items.length - 1);
      updateHighlight();
    } else if (event.key === "ArrowUp" && items.length) {
      event.preventDefault();
      highlightedIndex = Math.max(highlightedIndex - 1, 0);
      updateHighlight();
    } else if (event.key === "Escape") {
      suggestionsNode.classList.add("hidden");
    }
  });

  host.addEventListener("click", (event) => {
    if (event.target === host || event.target === chipsNode) input.focus();
  });

  return {
    getTags,
    setTags,
    setSuggestions,
    focus: () => input.focus(),
    flushPending: () => {
      if (input.value.trim()) addTag(input.value);
    },
  };
}
