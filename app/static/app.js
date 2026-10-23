"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const API = "/api";
const BUTTONS = new Set(["up", "down", "left", "right", "a", "b", "start", "select"]);
const KEYMAP = {
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
  z: "a",
  Z: "a",
  k: "a",
  K: "a",
  x: "b",
  X: "b",
  j: "b",
  J: "b",
  Enter: "start",
  Shift: "select",
};
const PRESETS = {
  ollama: { base_url: "http://localhost:11434/v1", model: "llava", poll_interval: 4 },
  lmstudio: { base_url: "http://localhost:1234/v1", model: "qwen2-vl-7b-instruct", poll_interval: 4 },
  vllm: { base_url: "http://localhost:8000/v1", model: "llava-hf/llava-1.5-7b-hf", poll_interval: 3 },
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", poll_interval: 4 },
};

let games = [];
let selectedId = null;
let selected = null;
let globalSettings = {};
let state = {};
let agent = {};
let memory = [];
let events = [];
let manual = false;
let paused = false;
let running = false;
let aiMode = "default";
let socket = null;
let socketGame = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
let takeControlPromise = null;
let frameSeq = -1;
let latestFrame = null;
let latestFrameSeq = -1;
let drawnFrameSeq = -1;
let fpsFrames = 0;
let fpsSince = performance.now();
let toastTimer = null;
let keyHeld = new Set();
let openingSettings = false;
const heldButtons = new Set();
const canvas = $("#screen");
const ctx = canvas.getContext("2d", { alpha: false });
ctx.imageSmoothingEnabled = false;

// ---------------- utilities ----------------
async function api(path, options = {}) {
  const request = { headers: {}, ...options };
  if (request.body && typeof request.body !== "string") {
    request.headers["content-type"] = "application/json";
    request.body = JSON.stringify(request.body);
  }
  const response = await fetch(API + path, request);
  let data = null;
  try { data = await response.json(); } catch (error) { data = null; }
  if (!response.ok) {
    throw new Error((data && data.detail) || `Request failed (${response.status})`);
  }
  return data;
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  const element = $("#toast");
  element.textContent = message;
  element.dataset.error = error ? "true" : "false";
  element.hidden = false;
  toastTimer = setTimeout(() => { element.hidden = true; }, 4500);
}

function setConnection(stateName, text) {
  $("#connection").dataset.state = stateName;
  $("#connection-text").textContent = text;
}

function fmtNumber(value) {
  return Number(value || 0).toLocaleString();
}

function fmtMoney(value) {
  return "₽" + fmtNumber(value);
}

function fmtClock(timestamp) {
  try {
    return new Date(timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch (error) { return "—"; }
}

function actionLabel(actions) {
  if (!Array.isArray(actions) || !actions.length) return "—";
  return actions.map((action) => {
    const buttons = Array.isArray(action.buttons) ? action.buttons : [];
    return buttons.map((button) => String(button).toUpperCase()).join("+") + " ×" + (action.frames || 4) + "f";
  }).join(" · ");
}

function statusLabel(value) {
  const labels = {
    starting: "starting",
    thinking: "thinking",
    acting: "acting",
    waiting: "waiting",
    idle: "idle",
    manual: "manual",
    paused: "paused",
    error: "error",
  };
  return labels[value] || value || "idle";
}

// ---------------- games ----------------
async function loadGames({ keepSelection = true } = {}) {
  const data = await api("/games");
  games = data.games || [];
  globalSettings = data.ai || {};
  renderGameOptions();
  if (!games.length) {
    selectedId = null;
    selected = null;
    renderAll();
    setConnection("error", "No games");
    toast("No ROMs found. Add a .gb/.gbc file to the roms folder and refresh.", true);
    return;
  }
  const wanted = keepSelection && games.some((game) => game.id === selectedId)
    ? selectedId
    : games[0].id;
  if (wanted !== selectedId || !selected) {
    await chooseGame(wanted);
  } else {
    selected = games.find((game) => game.id === selectedId) || selected;
    applySummary(selected);
    renderAll();
  }
}

function renderGameOptions() {
  const select = $("#game-select");
  select.replaceChildren();
  if (!games.length) {
    const option = document.createElement("option");
    option.textContent = "No games";
    option.value = "";
    select.append(option);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  for (const game of games) {
    const option = document.createElement("option");
    option.value = game.id;
    option.textContent = `${game.name}${game.demo ? " · demo" : ""}${game.running ? "" : " · stopped"}`;
    select.append(option);
  }
  select.value = selectedId || games[0].id;
}

async function chooseGame(gameId) {
  if (!gameId) return;
  selectedId = gameId;
  selected = games.find((game) => game.id === gameId) || { id: gameId, name: gameId };
  reconnectDelay = 1000;
  closeSocket();
  state = {};
  agent = {};
  memory = [];
  events = [];
  manual = false;
  paused = false;
  running = false;
  $("#game-select").value = gameId;
  applySummary(selected);
  renderAll();
  setConnection("connecting", "Loading game…");
  try {
    if (!selected.running) {
      selected = await api(`/games/${gameId}/start`, { method: "POST" });
      applySummary(selected);
    }
  } catch (error) {
    toast(error.message, true);
    setConnection("error", "Start failed");
    renderAll();
  }
  connectSocket(gameId);
}

function applySummary(summary) {
  if (!summary) return;
  running = Boolean(summary.running);
  paused = Boolean(summary.paused);
  manual = Boolean(summary.manual);
  aiMode = summary.ai_mode || "default";
  if (summary.state) state = summary.state;
  if (summary.agent) agent = summary.agent;
  if (summary.memory) memory = summary.memory;
  if (summary.events) events = summary.events;
  if (summary.ai) globalSettings = summary.ai;
  const modeSelect = $("#ai-mode");
  if (modeSelect.value !== aiMode) modeSelect.value = aiMode;
  $("#game-title").textContent = summary.title || summary.name || "Pokémon";
  $("#demo-chip").hidden = !summary.demo;
}

// ---------------- socket ----------------
function connectSocket(gameId) {
  closeSocket();
  socketGame = gameId;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const url = `${protocol}://${location.host}/ws/games/${gameId}`;
  setConnection("connecting", "Connecting stream…");
  let opened = false;
  try {
    socket = new WebSocket(url);
  } catch (error) {
    setConnection("error", "No stream");
    scheduleReconnect();
    return;
  }
  socket.onopen = () => {
    opened = true;
    reconnectDelay = 1000;
    setConnection("live", "Live");
  };
  socket.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (error) { return; }
    handleMessage(message);
  };
  socket.onerror = () => {
    if (!opened) setConnection("error", "Stream error");
  };
  socket.onclose = () => {
    socket = null;
    if (socketGame !== gameId) return;
    setConnection("error", "Reconnecting…");
    scheduleReconnect();
  };
}

function closeSocket() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  const old = socket;
  socket = null;
  socketGame = null;
  if (old) {
    old.onclose = null;
    old.onerror = null;
    old.onmessage = null;
    try { old.close(); } catch (error) { /* already closed */ }
  }
}

function scheduleReconnect() {
  if (!socketGame) return;
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    if (socketGame) connectSocket(socketGame);
  }, reconnectDelay);
  reconnectDelay = Math.min(10000, reconnectDelay * 1.7);
}

function handleMessage(message) {
  switch (message.type) {
    case "hello":
      if (message.game) applySummary(message.game);
      if (message.state) state = message.state;
      if (message.agent) agent = message.agent;
      if (message.memory) memory = message.memory;
      if (message.events) events = message.events;
      if (message.ai) globalSettings = message.ai;
      renderAll();
      break;
    case "frame":
      queueFrame(message.data, Number(message.seq || 0));
      break;
    case "state":
      if (message.state) state = message.state;
      renderState();
      break;
    case "agent":
      if (message.agent) agent = message.agent;
      renderAgent();
      renderControls();
      break;
    case "memory":
      if (Array.isArray(message.memory)) memory = message.memory;
      renderMemory();
      break;
    case "events":
      if (Array.isArray(message.events)) events = message.events;
      renderEvents();
      break;
    case "error":
      toast(message.message || "Stream error", true);
      break;
    case "ping":
      break;
    default:
      break;
  }
}

function queueFrame(base64, seq) {
  if (!base64 || seq < latestFrameSeq) return;
  const image = new Image();
  image.onload = () => {
    if (seq >= latestFrameSeq) {
      latestFrame = image;
      latestFrameSeq = seq;
    }
  };
  image.onerror = () => { /* keep the previous frame */ };
  image.src = "data:image/png;base64," + base64;
}

function drawLoop(now) {
  if (latestFrame && latestFrameSeq !== drawnFrameSeq) {
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(latestFrame, 0, 0, canvas.width, canvas.height);
    drawnFrameSeq = latestFrameSeq;
    fpsFrames += 1;
  }
  if (now - fpsSince >= 1000) {
    const fps = Math.round((fpsFrames * 1000) / (now - fpsSince));
    $("#frame-rate").textContent = `${fps} fps · frame ${Math.max(0, latestFrameSeq)}`;
    fpsFrames = 0;
    fpsSince = now;
  }
  requestAnimationFrame(drawLoop);
}
requestAnimationFrame(drawLoop);

// ---------------- rendering ----------------
function renderAll() {
  renderState();
  renderAgent();
  renderControls();
  renderMemory();
  renderEvents();
}

function renderState() {
  state = state || {};
  $("#trainer").textContent = state.trainer || "—";
  $("#badges").textContent = `${state.badge_count || 0}/8`;
  $("#location").textContent = state.map_name || "—";
  $("#coords").textContent = state.map_name ? `${state.x ?? "?"}, ${state.y ?? "?"}` : "";
  $("#money").textContent = fmtMoney(state.money);
  $("#playtime").textContent = state.playtime || "00:00:00";
  $("#pokedex").textContent = `${fmtNumber(state.pokedex_owned)} owned`;
  $("#pokedex-seen").textContent = `${fmtNumber(state.pokedex_seen)} seen`;
  $("#battle-chip").textContent = state.battle ? state.battle[0].toUpperCase() + state.battle.slice(1) : "Overworld";
  $("#screen-location").textContent = state.map_name || "—";
  $("#game-title").textContent = state.game || (selected && (selected.title || selected.name)) || "Pokémon";

  const bank = $("#badge-bank");
  bank.replaceChildren();
  const names = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth"];
  const badges = Array.isArray(state.badges) ? state.badges : [];
  for (let index = 0; index < 8; index += 1) {
    const dot = document.createElement("span");
    dot.className = "badge-dot";
    dot.dataset.earned = badges[index] ? "true" : "false";
    dot.title = `${names[index]}: ${badges[index] ? "earned" : "not earned"}`;
    dot.setAttribute("aria-label", dot.title);
    bank.append(dot);
  }

  const party = Array.isArray(state.party) ? state.party : [];
  $("#party-count").textContent = `${party.length} / 6`;
  const list = $("#party");
  list.replaceChildren();
  if (!party.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "No party yet. Press START and A on the title screen.";
    list.append(item);
  }
  for (const mon of party) {
    const item = document.createElement("li");
    item.className = "mon";
    const slot = document.createElement("span");
    slot.className = "mon-slot";
    slot.textContent = String(mon.slot || party.indexOf(mon) + 1).padStart(2, "0");
    const body = document.createElement("div");
    const name = document.createElement("div");
    name.className = "mon-name";
    name.textContent = mon.species || "Unknown";
    const level = document.createElement("small");
    level.textContent = `Lv ${mon.level ?? "?"}`;
    name.append(level);
    if (mon.status && mon.status !== "OK") {
      const status = document.createElement("span");
      status.className = "mon-status";
      status.textContent = mon.status;
      name.append(status);
    }
    const bar = document.createElement("div");
    bar.className = "hp";
    const maxHp = Number(mon.max_hp || 0);
    const hp = Number(mon.hp || 0);
    const ratio = maxHp > 0 ? Math.max(0, Math.min(1, hp / maxHp)) : 0;
    if (ratio <= 0.25) bar.dataset.low = "true";
    else if (ratio <= 0.5) bar.dataset.mid = "true";
    const fill = document.createElement("i");
    fill.style.width = `${ratio * 100}%`;
    bar.append(fill);
    body.append(name, bar);
    const hpText = document.createElement("span");
    hpText.className = "mon-hp";
    hpText.textContent = maxHp ? `${hp}/${maxHp}` : "—";
    item.append(slot, body, hpText);
    list.append(item);
  }
  renderControls();
}

function renderAgent() {
  agent = agent || {};
  const mode = agent.mode || aiMode;
  const status = agent.status || "idle";
  const chip = $("#agent-chip");
  chip.textContent = statusLabel(status);
  chip.dataset.status = status;
  $("#agent-thought").textContent = agent.thought || "The agent has not taken a turn yet.";
  $("#agent-turn").textContent = `turn ${agent.turn || 0}`;
  $("#agent-action").textContent = agent.last_action || "—";
  const model = agent.model || globalSettings.model || "";
  const endpoint = agent.endpoint || globalSettings.base_url || "";
  if (mode === "vision") {
    $("#agent-model").textContent = model ? `${model}${endpoint ? " @ " + endpoint : ""}` : "Vision endpoint not configured";
  } else if (mode === "manual") {
    $("#agent-model").textContent = "Manual control";
  } else {
    $("#agent-model").textContent = "Built-in autopilot · no API";
  }
  const planList = $("#agent-plan");
  planList.replaceChildren();
  const plan = Array.isArray(agent.plan) ? agent.plan : [];
  if (!plan.length) {
    const item = document.createElement("li");
    item.className = "muted";
    item.textContent = "No plan yet.";
    planList.append(item);
  } else {
    for (const step of plan) {
      const item = document.createElement("li");
      item.textContent = String(step);
      planList.append(item);
    }
  }
  const error = $("#agent-error");
  if (agent.error) {
    error.textContent = agent.error;
    error.hidden = false;
  } else {
    error.hidden = true;
  }
  if (agent.paused) {
    $("#agent-status-line").textContent = "Agent paused";
  } else if (agent.manual) {
    $("#agent-status-line").textContent = "Manual control";
  } else {
    $("#agent-status-line").textContent = `Agent ${statusLabel(status)}`;
  }
}

function renderControls() {
  const overlay = $("#screen-overlay");
  let overlayTitle = "";
  let overlayDetail = "";
  if (!running) {
    overlayTitle = selected && selected.status === "error" ? "Could not start" : "Stopped";
    overlayDetail = (selected && selected.error) || "Choose a game or add a ROM to begin.";
  } else if (paused) {
    overlayTitle = "Paused";
    overlayDetail = "Press Resume to continue.";
  }
  overlay.hidden = !overlayTitle;
  if (overlayTitle) {
    $("#overlay-title").textContent = overlayTitle;
    $("#overlay-detail").textContent = overlayDetail;
  }
  $("#game-status").textContent = !running ? (selected && selected.status === "error" ? "Error" : "Stopped") : paused ? "Paused" : "Live";
  const take = $("#take-control");
  take.textContent = manual ? "Handover to AI" : "Take control";
  take.classList.toggle("btn--primary", !manual);
  take.classList.toggle("btn--ghost", manual);
  $("#pause").textContent = paused ? "Resume" : "Pause";
  const hint = $("#control-hint");
  if (!running) hint.textContent = "Start a game to play.";
  else if (paused) hint.textContent = "The emulator is paused.";
  else if (manual) hint.textContent = "You have control. Take your time.";
  else if (aiMode === "vision") hint.textContent = "The vision agent is playing. Press a control to take over.";
  else hint.textContent = "The default autopilot is playing. Press a control to take over.";
}

function renderMemory() {
  const list = $("#memory");
  list.replaceChildren();
  $("#memory-count").textContent = `${memory.length} turn${memory.length === 1 ? "" : "s"}`;
  if (!memory.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "Turns will appear here as the agent observes and acts.";
    list.append(item);
    return;
  }
  const recent = memory.slice(-10).reverse();
  for (const turn of recent) {
    const item = document.createElement("li");
    item.className = "memory-item";
    item.dataset.error = turn.error ? "true" : "false";
    const top = document.createElement("div");
    top.className = "memory-top";
    const left = document.createElement("span");
    left.textContent = `#${turn.turn} · ${fmtClock(turn.timestamp)}`;
    const right = document.createElement("span");
    right.textContent = turn.summary || "";
    top.append(left, right);
    const thought = document.createElement("p");
    thought.className = "memory-thought";
    thought.textContent = turn.error ? `Error: ${turn.error}` : (turn.thought || "No thought recorded.");
    const actions = document.createElement("div");
    actions.className = "memory-actions";
    actions.textContent = `${actionLabel(turn.actions)} — ${turn.result || ""}`;
    item.append(top, thought, actions);
    list.append(item);
  }
}

function renderEvents() {
  const list = $("#events");
  list.replaceChildren();
  if (!events.length) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "No events yet.";
    list.append(item);
    return;
  }
  for (const event of events.slice(-25).reverse()) {
    const item = document.createElement("li");
    item.className = "event";
    const time = document.createElement("time");
    time.textContent = fmtClock(event.time);
    const message = document.createElement("strong");
    message.textContent = event.message || event.kind;
    item.append(time, message);
    list.append(item);
  }
}

// ---------------- control ----------------
async function control(action, silent = false) {
  if (!selectedId) return null;
  try {
    const result = await api(`/games/${selectedId}/control`, {
      method: "POST",
      body: { action },
    });
    if (result) {
      selected = { ...(selected || {}), ...result };
      applySummary(selected);
      if (result.agent) agent = result.agent;
      renderAll();
    }
    return result;
  } catch (error) {
    if (!silent) toast(error.message, true);
    throw error;
  }
}

async function takeControl() {
  if (manual) return;
  if (takeControlPromise) return takeControlPromise;
  takeControlPromise = control("take_control")
    .then(() => { manual = true; renderAll(); })
    .finally(() => { takeControlPromise = null; });
  return takeControlPromise;
}

async function toggleControl() {
  try {
    if (manual) {
      await control("handover");
      toast("Handed back to the AI.");
    } else {
      await takeControl();
      toast("You have control.");
    }
  } catch (error) { /* control() already reported */ }
}

async function togglePause() {
  try {
    await control(paused ? "resume" : "pause");
    toast(paused ? "Game paused." : "Game resumed.");
  } catch (error) { /* reported */ }
}

async function sendInput(button, action = "press", frames = 4) {
  if (!selectedId || !running) {
    toast("Start a game first.", true);
    return;
  }
  if (paused) {
    toast("The game is paused. Press Resume first.", true);
    return;
  }
  try {
    if (!manual) await takeControl();
    await api(`/games/${selectedId}/input`, {
      method: "POST",
      body: { button, action, frames },
    });
  } catch (error) {
    toast(error.message, true);
  }
}

function bindController() {
  for (const button of $$("[data-button]")) {
    const name = button.dataset.button;
    if (!BUTTONS.has(name)) continue;
    const isDirection = ["up", "down", "left", "right"].includes(name);
    const down = (event) => {
      event.preventDefault();
      if (heldButtons.has(name)) return;
      heldButtons.add(name);
      button.classList.add("is-down");
      sendInput(name, isDirection ? "down" : "press", isDirection ? 4 : 5);
    };
    const up = (event) => {
      if (!isDirection || !heldButtons.has(name)) return;
      event.preventDefault();
      heldButtons.delete(name);
      button.classList.remove("is-down");
      sendInput(name, "up", 1);
    };
    button.addEventListener("pointerdown", down);
    button.addEventListener("pointerup", up);
    button.addEventListener("pointerleave", up);
    button.addEventListener("pointercancel", up);
    button.addEventListener("contextmenu", (event) => event.preventDefault());
  }

  document.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    if (!$("#settings-drawer").hidden) return;
    const button = KEYMAP[event.key];
    if (!button) return;
    event.preventDefault();
    if (event.repeat) return;
    if (keyHeld.has(button)) return;
    keyHeld.add(button);
    const isDirection = ["up", "down", "left", "right"].includes(button);
    sendInput(button, isDirection ? "down" : "press", isDirection ? 4 : 5);
    const element = document.querySelector(`[data-button="${button}"]`);
    if (element) element.classList.add("is-down");
  });

  document.addEventListener("keyup", (event) => {
    if (isTypingTarget(event.target)) return;
    const button = KEYMAP[event.key];
    if (!button) return;
    const isDirection = ["up", "down", "left", "right"].includes(button);
    if (isDirection) {
      event.preventDefault();
      if (!keyHeld.has(button)) return;
      keyHeld.delete(button);
      sendInput(button, "up", 1);
    } else {
      keyHeld.delete(button);
    }
    const element = document.querySelector(`[data-button="${button}"]`);
    if (element) element.classList.remove("is-down");
  });

  window.addEventListener("blur", () => {
    for (const button of Array.from(keyHeld)) {
      if (["up", "down", "left", "right"].includes(button)) sendInput(button, "up", 1);
    }
    keyHeld.clear();
  });
}

function isTypingTarget(target) {
  if (!target) return false;
  const tag = String(target.tagName || "").toLowerCase();
  return ["input", "textarea", "select"].includes(tag) || target.isContentEditable;
}

// ---------------- settings drawer ----------------
async function openSettings() {
  if (openingSettings) return;
  openingSettings = true;
  try {
    const data = await api("/settings");
    globalSettings = data;
    fillSettingsForm(data);
    if (selectedId) {
      try {
        const snapshot = await api(`/games/${selectedId}`);
        selected = snapshot;
        fillOverrides((snapshot.overrides) || {});
        if (snapshot.state) state = snapshot.state;
        if (snapshot.agent) agent = snapshot.agent;
        if (snapshot.memory) memory = snapshot.memory;
        if (snapshot.events) events = snapshot.events;
        renderAll();
      } catch (error) {
        fillOverrides({});
      }
    }
    $("#scrim").hidden = false;
    $("#settings-drawer").hidden = false;
    $("#base-url").focus();
  } catch (error) {
    toast(error.message, true);
  } finally {
    openingSettings = false;
  }
}

function closeSettings() {
  $("#scrim").hidden = true;
  $("#settings-drawer").hidden = true;
}

function fillSettingsForm(settings) {
  $("#base-url").value = settings.base_url || "";
  $("#api-key").value = "";
  $("#key-state").textContent = settings.has_api_key ? "· saved" : "· not set";
  $("#model").value = settings.model || "";
  $("#poll-interval").value = settings.poll_interval ?? 4;
  $("#context-turns").value = settings.max_context_turns ?? 8;
  $("#image-history").value = settings.image_history ?? 2;
  $("#max-actions").value = settings.max_actions ?? 8;
  $("#max-frames").value = settings.max_frames ?? 240;
  $("#temperature").value = settings.temperature ?? 0.2;
  $("#timeout").value = settings.timeout ?? 120;
  $("#test-result").textContent = "";
  $("#preset").value = "";
}

function fillOverrides(overrides) {
  $("#override-base-url").value = overrides.base_url || "";
  $("#override-model").value = overrides.model || "";
  $("#override-poll").value = overrides.poll_interval || "";
}

function numberValue(selector, fallback) {
  const raw = String($(selector).value ?? "").trim();
  if (!raw) return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

async function saveSettings(event) {
  event.preventDefault();
  const button = $("#save-settings");
  button.disabled = true;
  try {
    const baseUrl = $("#base-url").value.trim();
    const model = $("#model").value.trim();
    if (!baseUrl || !model) {
      toast("A base URL and model ID are required.", true);
      return;
    }
    const payload = {
      base_url: baseUrl,
      model,
      poll_interval: numberValue("#poll-interval", 4),
      max_context_turns: numberValue("#context-turns", 8),
      image_history: numberValue("#image-history", 2),
      max_actions: numberValue("#max-actions", 8),
      max_frames: numberValue("#max-frames", 240),
      temperature: numberValue("#temperature", 0.2),
      timeout: numberValue("#timeout", 120),
    };
    const key = $("#api-key").value.trim();
    if (key) payload.api_key = key;
    globalSettings = await api("/settings", { method: "PUT", body: payload });
    $("#key-state").textContent = globalSettings.has_api_key ? "· saved" : "· not set";
    $("#api-key").value = "";

    if (selectedId) {
      const overridePayload = {};
      const overrideBase = $("#override-base-url").value.trim();
      const overrideModel = $("#override-model").value.trim();
      const poll = $("#override-poll").value.trim();
      if (overrideBase) overridePayload.base_url = overrideBase;
      if (overrideModel) overridePayload.model = overrideModel;
      if (poll) overridePayload.poll_interval = Number(poll);
      if (Object.keys(overridePayload).length) {
        const result = await api(`/games/${selectedId}`, { method: "PATCH", body: overridePayload });
        selected = { ...(selected || {}), ...result };
        applySummary(selected);
      }
    }
    toast("Model settings saved.");
    closeSettings();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function testEndpoint() {
  const button = $("#test-endpoint");
  const result = $("#test-result");
  button.disabled = true;
  result.dataset.ok = "";
  result.textContent = "Testing…";
  try {
    const payload = {
      base_url: $("#base-url").value.trim() || null,
      model: $("#model").value.trim() || null,
    };
    const key = $("#api-key").value.trim();
    if (key) payload.api_key = key;
    const data = await api("/settings/test", { method: "POST", body: payload });
    result.dataset.ok = "true";
    const names = Array.isArray(data.models) ? data.models.slice(0, 4).join(", ") : "";
    result.textContent = `Connected${names ? " · " + names : ""}`;
  } catch (error) {
    result.dataset.ok = "false";
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

// ---------------- events ----------------
function bindEvents() {
  $("#game-select").addEventListener("change", (event) => chooseGame(event.target.value));
  $("#refresh-games").addEventListener("click", async () => {
    const button = $("#refresh-games");
    button.disabled = true;
    try {
      await api("/roms/refresh", { method: "POST" });
      await loadGames();
      toast("ROM folder rescanned.");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  $("#ai-mode").addEventListener("change", async (event) => {
    if (!selectedId) return;
    const mode = event.target.value;
    try {
      const summary = await api(`/games/${selectedId}`, { method: "PATCH", body: { ai_mode: mode } });
      selected = { ...(selected || {}), ...summary };
      applySummary(selected);
      renderAll();
      if (mode === "vision") {
        toast(globalSettings.model ? "Vision agent enabled." : "Vision agent selected. Add a model endpoint in Settings.");
      } else if (mode === "default") {
        toast("Default autopilot enabled — no model API needed.");
      } else {
        toast("Manual mode. Use the controller or keyboard.");
      }
    } catch (error) {
      toast(error.message, true);
      event.target.value = aiMode;
    }
  });
  $("#take-control").addEventListener("click", toggleControl);
  $("#pause").addEventListener("click", togglePause);
  $("#reset-agent").addEventListener("click", async () => {
    if (!selectedId) return;
    try {
      await api(`/games/${selectedId}/agent/reset`, { method: "POST" });
      memory = [];
      renderMemory();
      toast("Agent memory cleared.");
    } catch (error) { toast(error.message, true); }
  });
  $("#settings-toggle").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-cancel").addEventListener("click", closeSettings);
  $("#scrim").addEventListener("click", closeSettings);
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#test-endpoint").addEventListener("click", testEndpoint);
  $("#preset").addEventListener("change", (event) => {
    const preset = PRESETS[event.target.value];
    if (!preset) return;
    $("#base-url").value = preset.base_url;
    $("#model").value = preset.model;
    $("#poll-interval").value = preset.poll_interval;
    $("#api-key").value = "";
    $("#key-state").textContent = globalSettings.has_api_key ? "· saved" : "· not set";
  });
  $("#clear-overrides").addEventListener("click", async () => {
    fillOverrides({});
    if (!selectedId) {
      toast("No game selected.");
      return;
    }
    try {
      const result = await api(`/games/${selectedId}`, {
        method: "PATCH",
        body: { clear_overrides: true },
      });
      selected = { ...(selected || {}), ...result };
      applySummary(selected);
      toast("Game overrides cleared. This game now uses the global endpoint.");
    } catch (error) {
      toast(error.message, true);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#settings-drawer").hidden) closeSettings();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && socketGame && !socket) {
      reconnectDelay = 1000;
      connectSocket(socketGame);
    }
  });
  bindController();
}

async function boot() {
  bindEvents();
  renderAll();
  try {
    await loadGames();
    if (selectedId) setConnection("connecting", "Starting…");
  } catch (error) {
    setConnection("error", "Offline");
    toast(error.message, true);
  }
}

boot();
