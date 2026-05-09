import { escapeHtml } from "../utils.js";

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

let activeModal = null;

function trapFocus(container, event) {
  if (event.key !== "Tab") return;
  const focusable = container.querySelectorAll(FOCUSABLE_SELECTOR);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    last.focus();
    event.preventDefault();
  } else if (!event.shiftKey && document.activeElement === last) {
    first.focus();
    event.preventDefault();
  }
}

function openModal({ title, bodyHtml, buttons, autoFocusSelector }) {
  return new Promise((resolve) => {
    if (activeModal) activeModal.close(null);

    const previouslyFocused = document.activeElement;
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML = `
      <div class="modal" tabindex="-1">
        <div class="modal-header">
          <h2 class="modal-title">${escapeHtml(title || "")}</h2>
        </div>
        <div class="modal-body">${bodyHtml || ""}</div>
        <div class="modal-footer">
          ${buttons
            .map(
              (btn, index) =>
                `<button type="button" class="button ${
                  btn.variant === "primary"
                    ? "primary"
                    : btn.variant === "danger"
                      ? "danger"
                      : "secondary"
                }" data-modal-action="${index}">${escapeHtml(btn.label)}</button>`,
            )
            .join("")}
        </div>
      </div>
    `;

    function close(value) {
      document.removeEventListener("keydown", onKeydown, true);
      overlay.classList.add("modal-leaving");
      setTimeout(() => {
        overlay.remove();
        if (previouslyFocused && previouslyFocused.focus) {
          previouslyFocused.focus();
        }
      }, 140);
      activeModal = null;
      resolve(value);
    }

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close(null);
      } else if (event.key === "Tab") {
        trapFocus(overlay, event);
      }
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });

    overlay.querySelectorAll("[data-modal-action]").forEach((node) => {
      node.addEventListener("click", () => {
        const index = Number(node.dataset.modalAction);
        const handler = buttons[index]?.onClick;
        const result = handler ? handler(overlay) : null;
        if (result === undefined) return;
        close(result);
      });
    });

    document.addEventListener("keydown", onKeydown, true);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add("modal-shown"));

    activeModal = { close };

    const focusTarget = autoFocusSelector
      ? overlay.querySelector(autoFocusSelector)
      : overlay.querySelector(".button.primary") || overlay.querySelector(".button");
    if (focusTarget) focusTarget.focus();
  });
}

export function confirmDialog({
  title = "Confirm",
  message = "",
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
} = {}) {
  return openModal({
    title,
    bodyHtml: `<p class="modal-message">${escapeHtml(message)}</p>`,
    buttons: [
      { label: cancelLabel, variant: "secondary", onClick: () => false },
      {
        label: confirmLabel,
        variant: danger ? "danger" : "primary",
        onClick: () => true,
      },
    ],
  });
}

export function promptDialog({
  title = "Enter value",
  message = "",
  initialValue = "",
  placeholder = "",
  confirmLabel = "Save",
  cancelLabel = "Cancel",
  validate,
} = {}) {
  const inputId = `modal-input-${Date.now()}`;
  return openModal({
    title,
    bodyHtml: `
      ${message ? `<p class="modal-message">${escapeHtml(message)}</p>` : ""}
      <input id="${inputId}" type="text" class="modal-input" value="${escapeHtml(
        initialValue,
      )}" placeholder="${escapeHtml(placeholder)}">
      <p class="modal-error hidden" data-modal-error></p>
    `,
    autoFocusSelector: `#${inputId}`,
    buttons: [
      { label: cancelLabel, variant: "secondary", onClick: () => null },
      {
        label: confirmLabel,
        variant: "primary",
        onClick: (overlay) => {
          const input = overlay.querySelector(`#${inputId}`);
          const errorNode = overlay.querySelector("[data-modal-error]");
          const value = input.value;
          if (validate) {
            const error = validate(value);
            if (error) {
              errorNode.textContent = error;
              errorNode.classList.remove("hidden");
              input.focus();
              return undefined;
            }
          }
          return value;
        },
      },
    ],
  }).then((result) => {
    return result;
  });
}

export function messageDialog({
  title = "Notice",
  message = "",
  confirmLabel = "OK",
} = {}) {
  return openModal({
    title,
    bodyHtml: `<p class="modal-message">${escapeHtml(message)}</p>`,
    buttons: [{ label: confirmLabel, variant: "primary", onClick: () => true }],
  });
}
