"use strict";

const state = {
  status: null,
  urlButtons: [],
  options: [],
};

const encoder = new TextEncoder();
const byId = (id) => document.getElementById(id);
const all = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function setupThemeToggle() {
  const button = byId("theme-toggle");
  button.addEventListener("click", () => {
    const explicitTheme = document.documentElement.dataset.theme;
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = explicitTheme ? explicitTheme === "dark" : systemDark;
    document.documentElement.dataset.theme = isDark ? "light" : "dark";
    button.setAttribute("aria-label", `Switch to ${isDark ? "dark" : "light"} theme`);
  });
}

function setText(id, value) {
  const element = byId(id);
  if (element) element.textContent = value;
}

function navigate(pageName) {
  const target = document.querySelector(`[data-page-panel="${pageName}"]`);
  if (!target) return;
  all("[data-page-panel]").forEach((panel) => {
    const active = panel === target;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  all(".nav-item").forEach((item) => {
    const active = item.dataset.page === pageName;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  if (window.location.hash !== `#${pageName}`) history.replaceState(null, "", `#${pageName}`);
  const heading = target.querySelector("h1");
  if (heading) {
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setupNavigation() {
  all("[data-page], [data-navigate]").forEach((control) => {
    control.addEventListener("click", (event) => {
      const page = control.dataset.page || control.dataset.navigate;
      if (page) {
        event.preventDefault();
        navigate(page);
      }
    });
  });
  const initial = window.location.hash.slice(1);
  navigate(document.querySelector(`[data-page-panel="${initial}"]`) ? initial : "overview");
  window.addEventListener("hashchange", () => {
    const page = window.location.hash.slice(1);
    if (document.querySelector(`[data-page-panel="${page}"]`)) navigate(page);
  });
}

async function apiRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch (_error) {
    throw new Error("Could not reach the local API.");
  }
  let body = null;
  try {
    body = await response.json();
  } catch (_error) {
    body = null;
  }
  if (!response.ok) {
    const error = new Error(formatBackendDetail(response.status, body?.detail));
    error.status = response.status;
    throw error;
  }
  return body;
}

function formatBackendDetail(status, detail) {
  if (status === 503) return "Telegram notification failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((entry) => entry?.msg).filter((message) => typeof message === "string");
    if (messages.length) return messages.join(" · ");
  }
  return status === 422 ? "The request did not pass backend validation." : "The local API rejected the request.";
}

function updateGlobalStatus(kind, text) {
  const indicator = byId("global-service-indicator");
  indicator.className = `service-indicator is-${kind}`;
  indicator.lastChild.textContent = text;
}

async function loadStatus() {
  const refresh = byId("refresh-status");
  if (refresh) {
    refresh.disabled = true;
    refresh.textContent = "Refreshing…";
  }
  try {
    state.status = await apiRequest("/api/v1/console/status", { method: "GET", headers: {} });
    renderStatus(state.status);
    updateGlobalStatus("success", "Service online");
  } catch (error) {
    updateGlobalStatus("danger", "Service unavailable");
    setText("status-api", "Unavailable");
    setText("status-polling", "Unavailable");
  } finally {
    if (refresh) {
      refresh.disabled = false;
      refresh.textContent = "Refresh status";
    }
  }
}

function renderStatus(status) {
  const targetCount = status.callback.targets.length;
  setText("status-api", status.service.status === "ok" ? "Online" : "Unavailable");
  setText("status-polling", capitalize(status.runtime.polling));
  setText("status-targets", `${targetCount} configured`);
  setText("status-fallback", `Legacy fallback ${status.callback.legacy_fallback_configured ? "enabled" : "disabled"}`);
  setText("status-telegram", status.telegram.token_configured ? "Configured" : "Not configured");
  setText("status-chat", `${status.telegram.client_initialized ? "Client initialized" : "Client not initialized"} · Default chat ${status.telegram.default_chat_configured ? "set" : "not set"}`);
  setText("sidebar-version", `v${status.service.version}`);
  setText("about-version", status.service.version);
  renderRouting(status.callback);
  renderCallbackTargets(status.callback);
}

function renderRouting(callback) {
  setText("routing-count", String(callback.targets.length));
  setText("routing-fallback", callback.legacy_fallback_configured ? "Enabled" : "Disabled");
  const body = byId("routing-table-body");
  body.replaceChildren();
  callback.targets.forEach((target) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    const endpoint = document.createElement("td");
    const configured = document.createElement("td");
    name.textContent = target.name;
    endpoint.textContent = target.endpoint_display;
    endpoint.className = "endpoint-cell";
    const badge = document.createElement("span");
    badge.className = "badge badge-success";
    badge.textContent = "Configured";
    configured.append(badge);
    row.append(name, endpoint, configured);
    body.append(row);
  });
  byId("routing-empty").hidden = callback.targets.length !== 0;
  body.closest(".table-wrap").hidden = callback.targets.length === 0;
}

function renderCallbackTargets(callback) {
  const select = byId("callback-target");
  const previous = select.value;
  select.replaceChildren();
  callback.targets.forEach((target) => {
    const option = document.createElement("option");
    option.value = target.name;
    option.textContent = target.name;
    select.append(option);
  });
  if (callback.legacy_fallback_configured) {
    const fallback = document.createElement("option");
    fallback.value = "__fallback__";
    fallback.textContent = "Legacy / default fallback";
    fallback.className = "legacy-option";
    select.append(fallback);
  }
  if (!select.options.length) {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "No callback route configured";
    select.append(empty);
    select.disabled = true;
  } else {
    select.disabled = false;
    if (all("option", select).some((option) => option.value === previous)) select.value = previous;
  }
  updateInteractionView();
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "Unavailable";
}

function jsonPreview(id, payload) {
  byId(id).textContent = JSON.stringify(payload, null, 2);
}

function parseChatId(raw) {
  const value = raw.trim();
  if (!/^-?\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function createBuilderItem(templateId, values = {}) {
  const item = byId(templateId).content.firstElementChild.cloneNode(true);
  Object.entries(values).forEach(([key, value]) => {
    const input = item.querySelector(`[data-field="${key}"]`);
    if (input) input.value = value;
  });
  return item;
}

function bindBuilderLabels(item, prefix, index) {
  all("[data-field]", item).forEach((input) => {
    input.id = `${prefix}-${index + 1}-${input.dataset.field.replace("_", "-")}`;
    const label = item.querySelector(`[data-label="${input.dataset.field}"]`);
    if (label) label.htmlFor = input.id;
  });
}

function moveItem(collection, index, direction) {
  const destination = index + direction;
  if (destination < 0 || destination >= collection.length) return;
  [collection[index], collection[destination]] = [collection[destination], collection[index]];
}

function bindBuilderItem(item, collection, render, update) {
  item.addEventListener("input", () => {
    const index = all(".builder-item", item.parentElement).indexOf(item);
    all("[data-field]", item).forEach((input) => {
      collection[index][input.dataset.field] = input.value;
    });
    update();
  });
  item.querySelector("[data-remove]").addEventListener("click", () => {
    const index = all(".builder-item", item.parentElement).indexOf(item);
    collection.splice(index, 1);
    render();
  });
  all("[data-move]", item).forEach((button) => {
    button.addEventListener("click", () => {
      const index = all(".builder-item", item.parentElement).indexOf(item);
      moveItem(collection, index, button.dataset.move === "up" ? -1 : 1);
      render();
    });
  });
}

function buildMessagePayload() {
  const payload = { text: byId("message-text").value.trim() };
  const override = document.querySelector('input[name="message-chat-mode"]:checked').value === "override";
  if (override) {
    const chatId = parseChatId(byId("message-chat-id").value);
    if (chatId !== null) payload.chat_id = chatId;
  }
  if (state.urlButtons.length) {
    payload.buttons = state.urlButtons.map((button) => ({
      type: "url",
      text: button.text.trim(),
      url: button.url.trim(),
    }));
  }
  return payload;
}

function validateMessage() {
  const errors = [];
  if (!byId("message-text").value.trim()) errors.push("Message is required.");
  const override = document.querySelector('input[name="message-chat-mode"]:checked').value === "override";
  if (override && parseChatId(byId("message-chat-id").value) === null) errors.push("Enter a valid integer chat ID.");
  state.urlButtons.forEach((button, index) => {
    if (!button.text.trim()) errors.push(`URL button ${index + 1} needs button text.`);
    try {
      const url = new URL(button.url.trim());
      if (!["http:", "https:"].includes(url.protocol)) throw new Error();
    } catch (_error) {
      errors.push(`URL button ${index + 1} must use http:// or https://.`);
    }
  });
  return errors;
}

function renderUrlButtons() {
  const list = byId("url-button-list");
  list.replaceChildren();
  state.urlButtons.forEach((button, index) => {
    const item = createBuilderItem("url-button-template", button);
    bindBuilderLabels(item, "url-button", index);
    item.querySelector(".item-number").textContent = `URL Button ${index + 1}`;
    const moveButtons = all("[data-move]", item);
    moveButtons[0].disabled = index === 0;
    moveButtons[1].disabled = index === state.urlButtons.length - 1;
    bindBuilderItem(item, state.urlButtons, renderUrlButtons, updateMessageView);
    list.append(item);
  });
  byId("url-button-empty").hidden = state.urlButtons.length !== 0;
  updateMessageView();
}

function updateMessageView() {
  setText("message-count", `${byId("message-text").value.length} / 4096`);
  jsonPreview("message-preview", buildMessagePayload());
  const errors = validateMessage();
  const validation = byId("message-validation");
  validation.hidden = errors.length === 0;
  validation.textContent = errors[0] || "";
  byId("send-message-button").disabled = errors.length > 0;
}

function setupMessageForm() {
  byId("message-text").addEventListener("input", updateMessageView);
  byId("message-chat-id").addEventListener("input", updateMessageView);
  all('input[name="message-chat-mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const override = radio.value === "override" && radio.checked;
      if (override || radio.value === "default") byId("message-chat-override").hidden = !override;
      updateMessageView();
    });
  });
  byId("add-url-button").addEventListener("click", () => {
    state.urlButtons.push({ text: "", url: "" });
    renderUrlButtons();
    all(".url-button-item input").at(-2)?.focus();
  });
  byId("message-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const errors = validateMessage();
    if (errors.length) return renderResult("message-result", "error", "Invalid request", errors.join(" "));
    await submitMessage(buildMessagePayload(), "message-result", "Message sent successfully.", byId("send-message-button"));
  });
  renderUrlButtons();
}

function encodeInteractionCallbackPreview(target, interactionId, optionId) {
  const normalizedTarget = target || "";
  const targetLength = Array.from(normalizedTarget).length;
  const interactionLength = Array.from(interactionId).length;
  return `h1|${targetLength}|${interactionLength}|${normalizedTarget}${interactionId}${optionId}`;
}

function callbackBytes(option) {
  const targetValue = byId("callback-target").value;
  const target = targetValue === "__fallback__" ? "" : targetValue;
  const encoded = encodeInteractionCallbackPreview(target, byId("interaction-id").value.trim(), option.option_id.trim());
  return { encoded, bytes: encoder.encode(encoded).length };
}

function buildInteractionPayload() {
  const targetValue = byId("callback-target").value;
  const payload = {
    text: byId("interaction-message").value.trim(),
    interaction_id: byId("interaction-id").value.trim(),
  };
  if (targetValue && targetValue !== "__fallback__") payload.callback_target = targetValue;
  payload.buttons = state.options.map((option) => ({
    type: "action",
    text: option.text.trim(),
    option_id: option.option_id.trim(),
  }));
  return payload;
}

function validateInteraction() {
  const errors = [];
  const interactionId = byId("interaction-id").value.trim();
  if (!interactionId) errors.push("Interaction ID is required.");
  if (!byId("interaction-message").value.trim()) errors.push("Message is required.");
  if (byId("callback-target").disabled || !byId("callback-target").value) errors.push("No callback delivery route is configured.");
  if (!state.options.length) errors.push("Add at least one option.");
  const ids = new Map();
  state.options.forEach((option, index) => {
    const id = option.option_id.trim();
    if (!option.text.trim()) errors.push(`Option ${index + 1} needs display text.`);
    if (!id) errors.push(`Option ${index + 1} needs an option ID.`);
    else if (ids.has(id)) errors.push(`Duplicate option_id: "${id}"`);
    else ids.set(id, index);
    if (id && callbackBytes(option).bytes > 64) errors.push(`Option "${id}" exceeds the 64-byte callback_data limit.`);
  });
  return [...new Set(errors)];
}

function renderOptions() {
  const list = byId("option-list");
  list.replaceChildren();
  state.options.forEach((option, index) => {
    const item = createBuilderItem("option-template", option);
    bindBuilderLabels(item, "interaction-option", index);
    item.querySelector(".item-number").textContent = `Option ${index + 1}`;
    const moveButtons = all("[data-move]", item);
    moveButtons[0].disabled = index === 0;
    moveButtons[1].disabled = index === state.options.length - 1;
    bindBuilderItem(item, state.options, renderOptions, updateInteractionView);
    list.append(item);
  });
  byId("option-empty").hidden = state.options.length !== 0;
  updateInteractionView();
}

function renderBudget() {
  const budget = byId("callback-budget");
  budget.replaceChildren();
  if (!state.options.length) {
    const empty = document.createElement("p");
    empty.className = "budget-empty";
    empty.textContent = "Add options to calculate callback_data size.";
    budget.append(empty);
    return;
  }
  state.options.forEach((option, index) => {
    const result = callbackBytes(option);
    const valid = result.bytes <= 64;
    const row = document.createElement("div");
    row.className = `budget-row ${valid ? "is-valid" : "is-invalid"}`;
    const id = document.createElement("code");
    id.textContent = option.option_id.trim() || `option-${index + 1}`;
    const meter = document.createElement("div");
    meter.className = "budget-meter";
    const fill = document.createElement("span");
    fill.style.width = `${Math.min(100, (result.bytes / 64) * 100)}%`;
    meter.append(fill);
    const size = document.createElement("strong");
    size.textContent = `${result.bytes} / 64 bytes ${valid ? "✓" : "✕"}`;
    row.append(id, meter, size);
    budget.append(row);
  });
}

function updateInteractionView() {
  setText("interaction-message-count", `${byId("interaction-message").value.length} / 4096`);
  jsonPreview("interaction-preview", buildInteractionPayload());
  renderBudget();
  const errors = validateInteraction();
  const validation = byId("interaction-validation");
  validation.hidden = errors.length === 0;
  validation.textContent = errors[0] || "";
  byId("send-interaction-button").disabled = errors.length > 0;
}

function generateDemoId() {
  const now = new Date();
  const parts = [now.getFullYear(), now.getMonth() + 1, now.getDate(), now.getHours(), now.getMinutes(), now.getSeconds()].map((part) => String(part).padStart(2, "0"));
  return `demo-${parts.slice(0, 3).join("")}-${parts.slice(3).join("")}`;
}

function setupInteractionForm() {
  ["interaction-id", "interaction-message", "callback-target"].forEach((id) => byId(id).addEventListener("input", updateInteractionView));
  byId("generate-demo-id").addEventListener("click", () => {
    byId("interaction-id").value = generateDemoId();
    updateInteractionView();
  });
  byId("add-option").addEventListener("click", () => {
    state.options.push({ text: "", option_id: "" });
    renderOptions();
    all(".option-item input").at(-2)?.focus();
  });
  byId("interaction-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const errors = validateInteraction();
    if (errors.length) return renderResult("interaction-result", "error", "Invalid request", errors.join(" "));
    const payload = buildInteractionPayload();
    await submitMessage(payload, "interaction-result", "Interaction message was sent to Telegram.", byId("send-interaction-button"), payload.interaction_id);
  });
  state.options = [
    { text: "Retry", option_id: "retry" },
    { text: "Manual review", option_id: "manual" },
  ];
  renderOptions();
}

async function submitMessage(payload, resultId, successTitle, button, interactionId = null) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Sending…";
  renderResult(resultId, "loading", "Sending request", "Waiting for the local API response.");
  try {
    const result = await apiRequest("/api/v1/messages", { method: "POST", body: JSON.stringify(payload) });
    const details = [`chat_id: ${result.chat_id}`, `message_id: ${result.message_id}`];
    if (interactionId) details.unshift(`interaction_id: ${interactionId}`);
    renderResult(resultId, "success", successTitle, details.join("\n"));
  } catch (error) {
    renderResult(resultId, "error", error.status === 422 ? "Invalid request" : "Message could not be sent", error.message);
  } finally {
    button.textContent = original;
    if (resultId === "message-result") updateMessageView();
    else updateInteractionView();
  }
}

function renderResult(id, kind, title, detail) {
  const panel = byId(id);
  const heading = panel.querySelector("h2");
  panel.replaceChildren(heading);
  const box = document.createElement("div");
  box.className = `result-box is-${kind}`;
  const strong = document.createElement("strong");
  strong.textContent = title;
  const text = document.createElement("pre");
  text.textContent = detail;
  box.append(strong, text);
  panel.append(box);
}

function setupCopyButtons() {
  all("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const original = button.textContent;
      try {
        await navigator.clipboard.writeText(byId(button.dataset.copy).textContent);
        button.textContent = "Copied";
      } catch (_error) {
        button.textContent = "Copy unavailable";
      }
      window.setTimeout(() => { button.textContent = original; }, 1400);
    });
  });
}

function init() {
  setupThemeToggle();
  setupNavigation();
  setupMessageForm();
  setupInteractionForm();
  setupCopyButtons();
  byId("refresh-status").addEventListener("click", loadStatus);
  loadStatus();
}

window.RuyiConsole = {
  encodeInteractionCallbackPreview,
  buildMessagePayload,
  buildInteractionPayload,
};

document.addEventListener("DOMContentLoaded", init);
