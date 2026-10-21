// Agent S browser bridge.
//
// Connects to the agent_s process on this computer over a local WebSocket and runs
// its actions in one tab inside the "Agent S" tab group, through the Chrome DevTools
// protocol. Clicks and keys go to that tab only, so your own mouse, keyboard and tabs
// are never used, and the agent keeps working while you are in another tab.

const DEFAULT_PORT = 8765;
const GROUP_TITLE = "Agent S";
const GROUP_COLOR = "purple";
const STATUS_TITLES = { done: "Agent S ✓", failed: "Agent S ✗", stopped: "Agent S" };

const MODIFIER_BITS = { alt: 1, option: 1, ctrl: 2, control: 2, command: 4, cmd: 4, meta: 4, win: 4, super: 4, shift: 8 };
const MODIFIER_KEYS = {
  1: { key: "Alt", code: "AltLeft", keyCode: 18 },
  2: { key: "Control", code: "ControlLeft", keyCode: 17 },
  4: { key: "Meta", code: "MetaLeft", keyCode: 91 },
  8: { key: "Shift", code: "ShiftLeft", keyCode: 16 },
};
const NAMED_KEYS = {
  enter: { key: "Enter", code: "Enter", keyCode: 13, text: "\r" },
  return: { key: "Enter", code: "Enter", keyCode: 13, text: "\r" },
  tab: { key: "Tab", code: "Tab", keyCode: 9 },
  esc: { key: "Escape", code: "Escape", keyCode: 27 },
  escape: { key: "Escape", code: "Escape", keyCode: 27 },
  backspace: { key: "Backspace", code: "Backspace", keyCode: 8 },
  delete: { key: "Delete", code: "Delete", keyCode: 46 },
  del: { key: "Delete", code: "Delete", keyCode: 46 },
  space: { key: " ", code: "Space", keyCode: 32, text: " " },
  up: { key: "ArrowUp", code: "ArrowUp", keyCode: 38 },
  down: { key: "ArrowDown", code: "ArrowDown", keyCode: 40 },
  left: { key: "ArrowLeft", code: "ArrowLeft", keyCode: 37 },
  right: { key: "ArrowRight", code: "ArrowRight", keyCode: 39 },
  home: { key: "Home", code: "Home", keyCode: 36 },
  end: { key: "End", code: "End", keyCode: 35 },
  pageup: { key: "PageUp", code: "PageUp", keyCode: 33 },
  pagedown: { key: "PageDown", code: "PageDown", keyCode: 34 },
};
for (let i = 1; i <= 12; i++) NAMED_KEYS[`f${i}`] = { key: `F${i}`, code: `F${i}`, keyCode: 111 + i };
// On macOS, synthetic key events do not trigger editing shortcuts unless the command is named.
const MAC_EDIT_COMMANDS = { a: "selectAll", c: "copy", x: "cut", v: "paste", z: "undo" };
const IS_MAC = /Mac/.test(navigator.userAgent);

let socket = null;
// The tab Agent S works in: { tabId, groupId, cursor: {x, y} | null, detachReason }
let session = null;
let lastUserTabId = null;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function withTimeout(promise, ms, message) {
  return Promise.race([promise, sleep(ms).then(() => Promise.reject(new Error(message)))]);
}

// ---- Connection to agent_s ------------------------------------------------------

async function setStatus(status) {
  await chrome.storage.local.set({ status });
}

async function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  const { port } = await chrome.storage.local.get("port");
  const ws = new WebSocket(`ws://127.0.0.1:${port || DEFAULT_PORT}`);
  socket = ws;
  ws.onopen = () => {
    setStatus("connected");
    ws.send(JSON.stringify({ type: "hello", version: chrome.runtime.getManifest().version }));
  };
  ws.onmessage = (event) => handleMessage(JSON.parse(event.data));
  ws.onclose = () => {
    if (socket === ws) {
      socket = null;
      setStatus("waiting");
    }
  };
  ws.onerror = () => {};
}

async function handleMessage(message) {
  if (message.type !== "call") return;
  let reply;
  try {
    const command = COMMANDS[message.method];
    if (!command) throw new Error(`Unknown command: ${message.method}`);
    const result = await command(message.params || {});
    reply = { type: "result", id: message.id, result: result === undefined ? null : result };
  } catch (error) {
    reply = { type: "result", id: message.id, error: String((error && error.message) || error) };
  }
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(reply));
}

// Retry every 2 seconds while the service worker is awake; the alarm wakes it up again.
setInterval(connect, 2000);
// Messages keep the service worker alive while connected.
setInterval(() => {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "keepalive" }));
}, 20000);
chrome.alarms.create("reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
setStatus("waiting");
connect();

// ---- The Agent S tab ------------------------------------------------------------

// Chrome's PDF viewer and other built-in pages cannot be debugged, so opening one
// detaches Agent S. Go back to a page it can use and tell the agent what happened.
async function recoverTab() {
  const tab = await chrome.tabs.get(session.tabId).catch(() => null);
  if (!tab) {
    session.detachReason = "the tab was closed";
    return false;
  }
  const url = tab.url || tab.pendingUrl || "the page";
  for (const goBack of [false, true]) {
    if (goBack) {
      await chrome.tabs.goBack(tab.id).catch(() => chrome.tabs.update(tab.id, { url: "about:blank" }));
      await sleep(1000);
    }
    try {
      await chrome.debugger.attach({ tabId: tab.id }, "1.3");
    } catch (error) {
      continue;
    }
    session.detachReason = null;
    session.cursor = null;
    await chrome.debugger.sendCommand({ tabId: tab.id }, "Page.enable");
    await chrome.debugger.sendCommand({ tabId: tab.id }, "Emulation.setFocusEmulationEnabled", { enabled: true });
    if (goBack) {
      session.notes.push(
        `${url} opened in a Chrome page Agent S cannot use (such as the PDF viewer), so the tab went back. ` +
          `To save that file to the computer, use agent.download("${url}").`
      );
    }
    return true;
  }
  session.detachReason = `${url} cannot be controlled`;
  return false;
}

async function cdp(method, params = {}) {
  if (!session) throw new Error("No Agent S tab is open. Start a task first.");
  if (session.detachReason === "target_closed") await recoverTab();
  if (session.detachReason) {
    throw new Error(
      session.detachReason === "canceled_by_user"
        ? "Agent S was stopped from Chrome's debugging banner."
        : `Agent S lost its tab (${session.detachReason}).`
    );
  }
  return chrome.debugger.sendCommand({ tabId: session.tabId }, method, params);
}

async function attach(tabId) {
  await chrome.debugger.attach({ tabId }, "1.3");
  session.tabId = tabId;
  session.detachReason = null;
  await cdp("Page.enable");
  // Let the page behave as if focused even while you are looking at another tab.
  await cdp("Emulation.setFocusEmulationEnabled", { enabled: true });
}

async function findGroup(windowId) {
  const groups = await chrome.tabGroups.query({ windowId });
  return groups.find((group) => (group.title || "").startsWith(GROUP_TITLE));
}

async function addToGroup(tabId, windowId) {
  const existing = await findGroup(windowId);
  const groupId = existing
    ? await chrome.tabs.group({ groupId: existing.id, tabIds: [tabId] })
    : await chrome.tabs.group({ createProperties: { windowId }, tabIds: [tabId] });
  await chrome.tabGroups.update(groupId, { title: GROUP_TITLE, color: GROUP_COLOR });
  return groupId;
}

async function waitForLoad(timeoutMs = 20000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const { result } = await cdp("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
      // Background tabs can take long to load every image; the page is usable once interactive.
      if (result.value === "complete" || (result.value === "interactive" && Date.now() - start > 1500)) return;
    } catch (error) {
      // The page is between documents; try again.
    }
    await sleep(250);
  }
}

async function navigate(url) {
  if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) url = `https://${url}`;
  const result = await cdp("Page.navigate", { url });
  if (result.errorText) throw new Error(`Could not open ${url}: ${result.errorText}`);
  await waitForLoad();
}

// A link the agent opens in a new tab: follow it, keep it in the group, and give you
// back the tab you were on if Chrome switched to it.
chrome.tabs.onCreated.addListener(async (tab) => {
  if (!session || tab.openerTabId !== session.tabId) return;
  try {
    await chrome.debugger.detach({ tabId: session.tabId }).catch(() => {});
    await addToGroup(tab.id, tab.windowId);
    if (tab.active && lastUserTabId !== null) await chrome.tabs.update(lastUserTabId, { active: true }).catch(() => {});
    session.cursor = null;
    await attach(tab.id);
    await waitForLoad();
  } catch (error) {
    session.detachReason = `could not follow the new tab: ${error.message}`;
  }
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  if (!session || tabId !== session.tabId) lastUserTabId = tabId;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (session && tabId === session.tabId) session.detachReason = "the tab was closed";
});

chrome.debugger.onDetach.addListener((source, reason) => {
  if (session && source.tabId === session.tabId) session.detachReason = reason;
});

// Alerts would freeze the page; accept them. Confirmations and prompts are dismissed
// so the agent never agrees to something on your behalf.
chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!session || source.tabId !== session.tabId || method !== "Page.javascriptDialogOpening") return;
  const accept = params.type === "alert" || params.type === "beforeunload";
  chrome.debugger.sendCommand(source, "Page.handleJavaScriptDialog", { accept }).catch(() => {});
});

// ---- The agent's cursor ---------------------------------------------------------

// Runs inside the page: draws the Agent S cursor in a closed shadow root that ignores
// the mouse, so it never blocks the page or your own pointer.
function agentCursor(action, x, y, ms, fromX, fromY) {
  const SVG = "http://www.w3.org/2000/svg";
  let cursor = window.__agentSCursor;
  if (!cursor || !cursor.host.isConnected) {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
    const root = host.attachShadow({ mode: "closed" });
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:fixed;left:0;top:0;pointer-events:none;will-change:transform;";
    const ripple = document.createElement("div");
    ripple.style.cssText =
      "position:absolute;left:-12px;top:-13px;width:30px;height:30px;border-radius:50%;border:2px solid #7c3aed;opacity:0;";
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("width", "24");
    svg.setAttribute("height", "28");
    svg.setAttribute("viewBox", "0 0 24 28");
    svg.style.cssText = "display:block;position:absolute;left:-3px;top:-2px;overflow:visible;filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));";
    const arrow = document.createElementNS(SVG, "path");
    arrow.setAttribute("d", "M3 2 L3 23 L8.6 17.8 L12.6 26.4 L16.6 24.6 L12.7 16.2 L20.4 16.2 Z");
    arrow.setAttribute("fill", "#7c3aed");
    arrow.setAttribute("stroke", "#ffffff");
    arrow.setAttribute("stroke-width", "1.8");
    arrow.setAttribute("stroke-linejoin", "round");
    svg.appendChild(arrow);
    const label = document.createElement("div");
    label.textContent = "Agent S";
    label.style.cssText =
      "position:absolute;left:16px;top:22px;padding:1px 8px;border-radius:999px;background:#7c3aed;color:#fff;" +
      "font:600 11px/16px -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,.3);";
    wrap.append(ripple, svg, label);
    root.appendChild(wrap);
    document.documentElement.appendChild(host);
    cursor = window.__agentSCursor = { host, wrap, ripple };
    if (fromX !== null) {
      wrap.style.transform = `translate(${fromX}px, ${fromY}px)`;
      wrap.getBoundingClientRect();
    }
  }
  if (action === "move") {
    cursor.wrap.style.transition = ms ? `transform ${ms}ms cubic-bezier(.3,.7,.2,1)` : "none";
    cursor.wrap.style.transform = `translate(${x}px, ${y}px)`;
  } else if (action === "click") {
    const ripple = cursor.ripple;
    ripple.style.transition = "none";
    ripple.style.opacity = "0.9";
    ripple.style.transform = "scale(.3)";
    ripple.getBoundingClientRect();
    ripple.style.transition = "transform 450ms ease-out, opacity 450ms ease-out";
    ripple.style.transform = "scale(1.7)";
    ripple.style.opacity = "0";
  } else if (action === "hide") {
    cursor.host.style.display = "none";
  } else if (action === "show") {
    cursor.host.style.display = "";
  } else if (action === "remove") {
    cursor.host.remove();
    delete window.__agentSCursor;
  }
}

async function cursorCall(action, x = 0, y = 0, ms = 0) {
  const from = session && session.cursor;
  const args = [action, x, y, ms, from ? from.x : null, from ? from.y : null].map((a) => JSON.stringify(a)).join(",");
  try {
    await cdp("Runtime.evaluate", { expression: `(${agentCursor.toString()})(${args})` });
  } catch (error) {
    // Some pages do not allow scripts; the cursor is only a visual aid.
  }
}

async function moveCursor(x, y) {
  const from = session.cursor;
  const distance = from ? Math.hypot(x - from.x, y - from.y) : 0;
  const ms = from ? Math.round(Math.min(650, 180 + distance * 0.6)) : 0;
  await cursorCall("move", x, y, ms);
  session.cursor = { x, y };
  if (ms) await sleep(ms);
}

// ---- Input ----------------------------------------------------------------------

function keyInfo(name) {
  const lower = name.toLowerCase();
  if (NAMED_KEYS[lower]) return NAMED_KEYS[lower];
  if (name.length === 1) {
    const upper = name.toUpperCase();
    const letter = /[a-z]/i.test(name);
    const digit = /[0-9]/.test(name);
    const code = letter ? `Key${upper}` : digit ? `Digit${name}` : "";
    return { key: name, code, keyCode: letter || digit ? upper.charCodeAt(0) : 0, text: name };
  }
  throw new Error(`Unknown key: ${name}`);
}

async function pressCombination(keys) {
  const names = keys.map((k) => String(k));
  const modifierBits = names.map((k) => MODIFIER_BITS[k.toLowerCase()]).filter(Boolean);
  const others = names.filter((k) => !MODIFIER_BITS[k.toLowerCase()]);
  let modifiers = 0;
  for (const bit of modifierBits) {
    modifiers |= bit;
    const info = MODIFIER_KEYS[bit];
    await cdp("Input.dispatchKeyEvent", { type: "rawKeyDown", key: info.key, code: info.code, windowsVirtualKeyCode: info.keyCode, modifiers });
  }
  const shortcut = modifiers & (1 | 2 | 4);
  for (const name of others) {
    const info = keyInfo(name);
    const text = shortcut || !info.text ? undefined : modifiers & 8 ? info.text.toUpperCase() : info.text;
    const event = { key: info.key, code: info.code, windowsVirtualKeyCode: info.keyCode, modifiers };
    const command = IS_MAC && modifiers & (2 | 4) ? MAC_EDIT_COMMANDS[info.key.toLowerCase()] : undefined;
    const commands = command ? [command === "undo" && modifiers & 8 ? "redo" : command] : undefined;
    await cdp("Input.dispatchKeyEvent", { ...event, type: text ? "keyDown" : "rawKeyDown", text, unmodifiedText: text, commands });
    await cdp("Input.dispatchKeyEvent", { ...event, type: "keyUp" });
  }
  for (const bit of modifierBits.reverse()) {
    modifiers &= ~bit;
    const info = MODIFIER_KEYS[bit];
    await cdp("Input.dispatchKeyEvent", { type: "keyUp", key: info.key, code: info.code, windowsVirtualKeyCode: info.keyCode, modifiers });
  }
}

const MOUSE_BUTTONS = { left: 1, right: 2, middle: 4 };

const COMMANDS = {
  async start({ url }) {
    if (session) await COMMANDS.stop({ status: "stopped" }).catch(() => {});
    let window = await chrome.windows.getLastFocused({ windowTypes: ["normal"] }).catch(() => null);
    if (!window) window = await chrome.windows.create({ focused: false });
    // Opened in the background so your current tab stays in front.
    const tab = await chrome.tabs.create({ windowId: window.id, url: "about:blank", active: false });
    // notes: things the agent cannot see in a screenshot, passed on with the next one
    session = { tabId: tab.id, groupId: null, cursor: null, detachReason: null, notes: [] };
    session.groupId = await addToGroup(tab.id, window.id);
    await attach(tab.id);
    if (url && url !== "about:blank") await navigate(url);
    return { tabId: tab.id };
  },

  async stop({ status = "stopped" }) {
    if (!session) return;
    const { tabId } = session;
    await cursorCall("remove");
    await chrome.debugger.detach({ tabId }).catch(() => {});
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (tab && tab.groupId !== -1) {
      await chrome.tabGroups.update(tab.groupId, { title: STATUS_TITLES[status] || GROUP_TITLE }).catch(() => {});
    }
    session = null;
  },

  async screenshot() {
    // Show the agent every page at 100%, whatever zoom you saved for the site. Per-tab
    // zoom leaves your own zoom levels alone; navigation resets it, so set it each time.
    await chrome.tabs.setZoomSettings(session.tabId, { scope: "per-tab" }).catch(() => {});
    if ((await chrome.tabs.getZoom(session.tabId).catch(() => 1)) !== 1) {
      await chrome.tabs.setZoom(session.tabId, 1).catch(() => {});
      await sleep(300);
    }
    await cursorCall("hide");
    try {
      const metrics = await cdp("Page.getLayoutMetrics");
      const viewport = metrics.cssVisualViewport || metrics.visualViewport;
      const shot = await withTimeout(cdp("Page.captureScreenshot", { format: "png" }), 15000, "Taking a screenshot of the Agent S tab timed out.");
      return {
        data: shot.data,
        width: Math.round(viewport.clientWidth),
        height: Math.round(viewport.clientHeight),
        notes: session.notes.splice(0),
      };
    } finally {
      await cursorCall("show");
    }
  },

  async navigate({ url }) {
    session.cursor = null;
    await navigate(url);
  },

  async goBack() {
    const history = await cdp("Page.getNavigationHistory");
    if (history.currentIndex > 0) {
      await cdp("Page.navigateToHistoryEntry", { entryId: history.entries[history.currentIndex - 1].id });
      await sleep(300);
      await waitForLoad();
    }
  },

  async click({ x, y, button = "left", clicks = 1, modifiers = 0 }) {
    await moveCursor(x, y);
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, modifiers });
    for (let count = 1; count <= clicks; count++) {
      await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button, buttons: MOUSE_BUTTONS[button] || 1, clickCount: count, modifiers });
      await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button, buttons: 0, clickCount: count, modifiers });
    }
    await cursorCall("click");
  },

  async drag({ x1, y1, x2, y2, modifiers = 0 }) {
    await moveCursor(x1, y1);
    await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: x1, y: y1, modifiers });
    await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x: x1, y: y1, button: "left", buttons: 1, clickCount: 1, modifiers });
    const steps = 15;
    for (let i = 1; i <= steps; i++) {
      const x = x1 + ((x2 - x1) * i) / steps;
      const y = y1 + ((y2 - y1) * i) / steps;
      await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "left", buttons: 1, modifiers });
      await cursorCall("move", x, y, 0);
      await sleep(20);
    }
    await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x: x2, y: y2, button: "left", buttons: 0, clickCount: 1, modifiers });
    session.cursor = { x: x2, y: y2 };
  },

  async scroll({ x, y, dx = 0, dy = 0 }) {
    await moveCursor(x, y);
    await cdp("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: dx, deltaY: dy });
    await sleep(400);
  },

  async typeText({ text }) {
    await cdp("Input.insertText", { text });
  },

  async keys({ keys }) {
    await pressCombination(keys);
  },

  // Saves a file to the Downloads folder with Chrome's download manager, so no viewer
  // or Save dialog gets in the way. Resolves when the download has finished.
  async download({ url }) {
    const id = await chrome.downloads.download({ url, conflictAction: "uniquify" });
    const start = Date.now();
    while (Date.now() - start < 300000) {
      const [item] = await chrome.downloads.search({ id });
      if (item && item.state === "complete") return { filename: item.filename, bytes: item.fileSize };
      if (item && item.state === "interrupted") throw new Error(`The download of ${url} failed: ${item.error}`);
      await sleep(300);
    }
    throw new Error(`The download of ${url} did not finish within 5 minutes.`);
  },

  // agent_s asks for this when the extension files in the repository are newer.
  async reload() {
    setTimeout(() => chrome.runtime.reload(), 100);
  },
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "status") {
    chrome.storage.local.get(["status", "port"]).then(({ status, port }) => {
      sendResponse({ status: status || "waiting", port: port || DEFAULT_PORT, working: Boolean(session) });
    });
    return true;
  }
});
