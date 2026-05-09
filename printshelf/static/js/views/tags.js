import { api } from "../api.js";
import { state } from "../state.js";
import {
  $,
  buildItemQueryParams,
  escapeHtml,
  formatBytes,
  parseTagInput,
  pluralize,
} from "../utils.js";
import { toast } from "../ui/toast.js";
import { confirmDialog, promptDialog } from "../ui/modal.js";

let onTagsChanged = null;

export function setOnTagsChanged(callback) {
  onTagsChanged = callback;
}

function setTagsStatus(message) {
  $("tagsStatus").textContent = message || "";
}

function updateTagActionState() {
  const hasActiveTag = Boolean(state.activeTag);
  $("renameTagButton").disabled = !hasActiveTag;
  $("deleteTagButton").disabled = !hasActiveTag;
  const hasChecks = state.checkedTagItemIds.size > 0;
  $("bulkApplyButton").disabled =
    !hasActiveTag || !hasChecks || state.bulkInFlight;
  $("checkedItemCount").textContent = `${state.checkedTagItemIds.size} checked`;
  $("checkedOnlyToggle").classList.toggle("hidden", !hasChecks);
}

function renderTagList() {
  const list = $("tagList");
  list.innerHTML = "";

  if (!state.tags.length) {
    const empty = document.createElement("div");
    empty.className = "tags-empty-state";
    empty.innerHTML = $("tagSearchInput").value.trim()
      ? "<p class='muted'>No tags match your search.</p>"
      : "<p class='muted'>No tags yet. Tag items in <strong>Browse</strong> to see them grouped here.</p>";
    list.appendChild(empty);
    return;
  }

  for (const tag of state.tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-row";
    if (state.activeTag && state.activeTag.id === tag.id) {
      button.classList.add("active");
      button.setAttribute("aria-pressed", "true");
    } else {
      button.setAttribute("aria-pressed", "false");
    }
    button.innerHTML = `
      <span class="tag-row-name">${escapeHtml(tag.name)}</span>
      <span class="tag-row-count">${Number(tag.item_count || 0)} ${pluralize(
        Number(tag.item_count || 0),
        "item",
      )}</span>
    `;
    button.addEventListener("click", () => {
      const isAlreadySelected =
        state.activeTag && state.activeTag.id === Number(tag.id);
      if (isAlreadySelected) {
        state.activeTag = null;
        state.taggedItems = [];
        state.checkedTagItemIds.clear();
        state.showCheckedOnly = false;
        renderTagList();
        renderTaggedItems();
        return;
      }
      state.activeTag = { id: Number(tag.id), name: String(tag.name || "") };
      state.checkedTagItemIds.clear();
      state.showCheckedOnly = false;
      renderTagList();
      renderTaggedItems();
      loadTaggedItems().catch((error) => toast.error(error.message));
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

  const allItems = state.taggedItems;
  const visibleItems = state.showCheckedOnly
    ? allItems.filter((it) => state.checkedTagItemIds.has(it.id))
    : allItems;

  activeTagTitle.textContent = `Tag: ${state.activeTag.name}`;
  activeTagCount.textContent = `${allItems.length} ${pluralize(allItems.length, "item")}`;
  if (state.showCheckedOnly) {
    resultCount.textContent = `Showing ${visibleItems.length} checked of ${allItems.length}`;
  } else {
    resultCount.textContent = `${allItems.length} matching ${pluralize(
      allItems.length,
      "item",
    )}`;
  }

  if (!visibleItems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    if (!allItems.length) {
      empty.innerHTML = "<p>No items match this tag with current filters.</p>";
    } else {
      empty.innerHTML = "<p>No checked items.</p>";
    }
    list.appendChild(empty);
    updateTagActionState();
    return;
  }

  for (const item of visibleItems) {
    const row = document.createElement("article");
    row.className = "tagged-item";
    if (state.checkedTagItemIds.has(item.id)) row.classList.add("checked");
    row.dataset.itemId = String(item.id);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "tagged-item-check";
    checkbox.checked = state.checkedTagItemIds.has(item.id);
    checkbox.setAttribute("aria-label", `Select ${item.filename}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.checkedTagItemIds.add(item.id);
        row.classList.add("checked");
      } else {
        state.checkedTagItemIds.delete(item.id);
        row.classList.remove("checked");
      }
      updateTagActionState();
      if (state.showCheckedOnly) renderTaggedItems();
    });

    const meta = document.createElement("div");
    meta.className = "tagged-item-meta";
    const tagsHtml = (item.tags || [])
      .slice(0, 8)
      .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
      .join("");
    const previewHtml = item.preview_url
      ? `<img loading="lazy" src="${escapeHtml(item.preview_url)}" alt="">`
      : "";
    meta.innerHTML = `
      <div class="tagged-item-thumb">${previewHtml}</div>
      <div class="tagged-item-text">
        <div class="tagged-item-title">${escapeHtml(item.filename)}</div>
        <div class="tagged-item-path">${escapeHtml(item.relative_path)}</div>
        <div class="row">
          <span class="pill">${escapeHtml(item.file_type.toUpperCase())}</span>
          <span class="muted">${escapeHtml(formatBytes(item.size_bytes))}</span>
        </div>
        <div class="tagged-item-tags">${tagsHtml}</div>
      </div>
    `;

    row.appendChild(checkbox);
    row.appendChild(meta);
    list.appendChild(row);
  }
  updateTagActionState();
}

export async function loadTags() {
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
  if (onTagsChanged) onTagsChanged();
}

export async function loadTaggedItems() {
  if (!state.activeTag) {
    state.taggedItems = [];
    state.checkedTagItemIds.clear();
    renderTaggedItems();
    return;
  }

  const requestId = ++state.taggedItemsRequestId;
  const selectedTagName = state.activeTag.name;
  const items = await api(
    `/api/items?${buildItemQueryParams({ tag: selectedTagName })}`,
  );
  if (requestId !== state.taggedItemsRequestId) return;
  if (!state.activeTag || state.activeTag.name !== selectedTagName) return;

  state.taggedItems = items;
  const validIds = new Set(items.map((item) => item.id));
  state.checkedTagItemIds = new Set(
    [...state.checkedTagItemIds].filter((itemId) => validIds.has(itemId)),
  );
  renderTaggedItems();
}

async function renameActiveTag() {
  if (!state.activeTag) return;
  const nextName = await promptDialog({
    title: "Rename tag",
    message: `Renaming will merge into an existing tag if the name matches another tag (case-insensitive).`,
    initialValue: state.activeTag.name,
    placeholder: "Tag name",
    confirmLabel: "Rename",
    validate: (value) => {
      if (!value.trim()) return "Tag name cannot be empty.";
      return null;
    },
  });
  if (nextName === null) return;

  try {
    const updated = await api(`/api/tags/${state.activeTag.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: nextName }),
    });
    state.activeTag = {
      id: Number(updated.id),
      name: String(updated.name || ""),
    };
    setTagsStatus(`Tag renamed to "${state.activeTag.name}".`);
    toast.success(`Tag renamed to "${state.activeTag.name}".`);
    await loadTags();
    await loadTaggedItems();
    if (onTagsChanged) onTagsChanged();
  } catch (error) {
    toast.error(error.message);
  }
}

async function deleteActiveTag() {
  if (!state.activeTag) return;
  const confirmed = await confirmDialog({
    title: "Delete tag",
    message: `Delete tag "${state.activeTag.name}" from all items? Items and files remain.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!confirmed) return;

  const deletedTagName = state.activeTag.name;
  try {
    await api(`/api/tags/${state.activeTag.id}`, { method: "DELETE" });
    state.activeTag = null;
    state.taggedItems = [];
    state.checkedTagItemIds.clear();
    state.showCheckedOnly = false;
    setTagsStatus(`Tag "${deletedTagName}" deleted.`);
    toast.success(`Tag "${deletedTagName}" deleted.`);
    await loadTags();
    renderTaggedItems();
    if (onTagsChanged) onTagsChanged();
  } catch (error) {
    toast.error(error.message);
  }
}

async function applyBulkTagUpdate() {
  if (!state.activeTag) {
    setTagsStatus("Select a tag first.");
    return;
  }
  if (state.bulkInFlight) return;

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

  state.bulkInFlight = true;
  $("bulkApplyButton").classList.add("loading");
  updateTagActionState();

  try {
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
    const count = result.updated_items || 0;
    setTagsStatus(`Bulk update applied to ${count} ${pluralize(count, "item")}.`);
    toast.success(`Updated ${count} ${pluralize(count, "item")}.`);

    await loadTags();
    await loadTaggedItems();
    if (onTagsChanged) onTagsChanged();
  } catch (error) {
    toast.error(error.message);
  } finally {
    state.bulkInFlight = false;
    $("bulkApplyButton").classList.remove("loading");
    updateTagActionState();
  }
}

export function initTagsView() {
  $("renameTagButton").addEventListener("click", renameActiveTag);
  $("deleteTagButton").addEventListener("click", deleteActiveTag);
  $("bulkApplyButton").addEventListener("click", applyBulkTagUpdate);

  $("checkedOnlyToggle").addEventListener("click", () => {
    state.showCheckedOnly = !state.showCheckedOnly;
    $("checkedOnlyToggle").classList.toggle("active", state.showCheckedOnly);
    $("checkedOnlyToggle").setAttribute(
      "aria-pressed",
      state.showCheckedOnly ? "true" : "false",
    );
    renderTaggedItems();
  });

  $("taggedItemsList").addEventListener("click", (event) => {
    const checkbox = event.target.closest(".tagged-item-check");
    if (checkbox) return;
    const titleOrThumb = event.target.closest(".tagged-item-text, .tagged-item-thumb");
    if (!titleOrThumb) return;
    const row = event.target.closest("[data-item-id]");
    if (!row) return;
    const itemId = Number(row.dataset.itemId);
    if (!Number.isFinite(itemId)) return;
    document.dispatchEvent(
      new CustomEvent("printshelf:open-item", { detail: { itemId } }),
    );
  });
}
