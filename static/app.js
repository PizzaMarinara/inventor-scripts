/* app.js — Inventor Agent WebSocket client
 * Handles:
 *   - WebSocket connection lifecycle (auto-reconnect)
 *   - Sending chat messages + extract-parameters shortcut
 *   - Rendering server events: tool_start, tool_result, done, error
 *   - File list / outputs list population from REST API
 *   - Parameters table rendering when done event contains a JSON block
 *   - Script management: list, view, run, download
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

const WS_URL = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/chat`;
let ws = null;
let isRunning = false;
let currentAgentBubble = null;   // the <div class="bubble-agent"> being built
let selectedFile = "";           // currently selected input file (relative to input/)
let filePickerOpen = false;
let allFiles = [];               // cached file list from /api/files

// ── WebSocket lifecycle ───────────────────────────────────────────────────────

function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("[ws] connected");
    };

    ws.onclose = () => {
        console.log("[ws] disconnected — retrying in 2s");
        ws = null;
        setTimeout(connect, 2000);
    };

    ws.onerror = (err) => {
        console.error("[ws] error", err);
    };

    ws.onmessage = (ev) => {
        try {
            handleEvent(JSON.parse(ev.data));
        } catch (e) {
            console.error("[ws] bad JSON", ev.data, e);
        }
    };
}

connect();

// ── Event handler ─────────────────────────────────────────────────────────────

function handleEvent(event) {
    switch (event.type) {
        case "text_delta":
            appendToCurrentBubble(event.content);
            break;

        case "tool_start":
            insertToolBadge(event.tool, event.input);
            break;

        case "tool_result":
            updateToolBadge(event.tool, event.result);
            break;

        case "done":
            finaliseCurrentBubble(event.content);
            refreshOutputsList();
            setRunning(false);
            break;

        case "error":
            showErrorAlert(event.message);
            setRunning(false);
            break;

        case "script_list":
            handleScriptListEvent(event);
            break;

        default:
            console.warn("[ws] unknown event type:", event.type);
    }
}

// ── Chat form ─────────────────────────────────────────────────────────────────

document.getElementById("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    if (isRunning || !ws) return;
    const message = document.getElementById("msg-input").value.trim();
    if (!message) return;
    const file = selectedFile;
    const provider = document.getElementById("provider-select").value || undefined;
    const apiKey = document.getElementById("api-key-input").value || undefined;
    ws.send(JSON.stringify({ type: "chat", message, file, provider, api_key: apiKey }));
    appendUserBubble(message);
    document.getElementById("msg-input").value = "";
    currentAgentBubble = null;
    setRunning(true);
});

// Shift+Enter → new line; bare Enter → submit
document.getElementById("msg-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        document.getElementById("chat-form").dispatchEvent(new Event("submit"));
    }
});

// ── Extract button ────────────────────────────────────────────────────────────

document.getElementById("extract-btn").addEventListener("click", () => {
    const file = selectedFile;
    if (!file || isRunning || !ws) return;
    const instruction = `Extract all parameters from ${file} and show them as a table.`;
    const provider = document.getElementById("provider-select").value || undefined;
    const apiKey = document.getElementById("api-key-input").value || undefined;
    ws.send(JSON.stringify({ type: "chat", message: instruction, file, provider, api_key: apiKey }));
    appendUserBubble(instruction);
    currentAgentBubble = null;
    setRunning(true);
});

// ── DOM helpers ───────────────────────────────────────────────────────────────

function appendUserBubble(text) {
    const div = document.createElement("div");
    div.className = "bubble bubble-user";
    div.textContent = text;
    document.getElementById("messages").appendChild(div);
    scrollToBottom();
}

function appendToCurrentBubble(text) {
    if (!currentAgentBubble) {
        currentAgentBubble = document.createElement("div");
        currentAgentBubble.className = "bubble bubble-agent";
        document.getElementById("messages").appendChild(currentAgentBubble);
    }
    currentAgentBubble.textContent += text;
    scrollToBottom();
}

function finaliseCurrentBubble(text) {
    if (text) {
        if (!currentAgentBubble) {
            currentAgentBubble = document.createElement("div");
            currentAgentBubble.className = "bubble bubble-agent";
            document.getElementById("messages").appendChild(currentAgentBubble);
        }
        currentAgentBubble.textContent = text;
        maybeRenderParamsTable(text);
    }
    currentAgentBubble = null;
    scrollToBottom();
}

// Tool badges — keyed by tool name (last-wins if same tool called twice)
const _toolBadges = {};

function insertToolBadge(toolName, input) {
    const details = document.createElement("details");
    details.className = "tool-badge";
    details.dataset.tool = toolName;

    const summary = document.createElement("summary");
    summary.textContent = ` ${toolName}`;
    details.appendChild(summary);

    const pre = document.createElement("pre");
    pre.textContent = "Input: " + JSON.stringify(input, null, 2);
    details.appendChild(pre);

    document.getElementById("messages").appendChild(details);
    _toolBadges[toolName] = pre;
    scrollToBottom();
}

function updateToolBadge(toolName, result) {
    const pre = _toolBadges[toolName];
    if (pre) {
        const resultStr = typeof result === "string" ? result : JSON.stringify(result, null, 2);
        const truncated = resultStr.length > 400 ? resultStr.slice(0, 400) + "\n…(truncated)" : resultStr;
        pre.textContent += "\n\nResult: " + truncated;
    }
}

function showErrorAlert(message) {
    const div = document.createElement("div");
    div.className = "error-alert";
    div.textContent = "⚠ " + message;
    document.getElementById("messages").appendChild(div);
    scrollToBottom();
}

function scrollToBottom() {
    const msgs = document.getElementById("messages");
    msgs.scrollTop = msgs.scrollHeight;
}

// ── setRunning ────────────────────────────────────────────────────────────────

function setRunning(state) {
    isRunning = state;
    document.getElementById("send-btn").disabled = state;
    document.getElementById("extract-btn").disabled = state;
    document.getElementById("status").classList.toggle("hidden", !state);
}

// ── Parameters table ──────────────────────────────────────────────────────────

function maybeRenderParamsTable(text) {
    const jsonMatch = text.match(/```json\s*([\s\S]+?)\s*```/);
    if (!jsonMatch) return;
    try {
        const params = JSON.parse(jsonMatch[1]);
        const tbody = document.querySelector("#params-table tbody");
        tbody.innerHTML = "";
        Object.entries(params).forEach(([name, info]) => {
            const tr = document.createElement("tr");
            tr.innerHTML =
                `<td>${escHtml(name)}</td>` +
                `<td class="mono">${escHtml(String(info.value ?? ""))}</td>` +
                `<td class="mono">${escHtml(String(info.units ?? ""))}</td>` +
                `<td>${escHtml(String(info.comment ?? ""))}</td>`;
            tbody.appendChild(tr);
        });
    } catch (_) { /* not a params block — leave table empty */ }
}

function escHtml(str) {
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// ── File list & outputs ───────────────────────────────────────────────────────

// ── File banner + tree picker ─────────────────────────────────────────────────

async function initFileBanner() {
    try {
        const resp = await fetch("/api/active-document");
        const { file } = await resp.json();
        if (file) {
            selectedFile = file;
            setBannerState("live", file);
        } else {
            setBannerState("none", null);
        }
    } catch (e) {
        setBannerState("none", null);
    }
    await loadFileList();
}

async function loadFileList() {
    try {
        const resp = await fetch("/api/files");
        const { files } = await resp.json();
        allFiles = files;
        renderFileTree(files);
    } catch (e) {
        console.warn("[files] could not load file list", e);
    }
}

function setBannerState(state, filename) {
    // state: "live" | "selected" | "none"
    const banner = document.getElementById("file-banner");
    const dot = document.getElementById("file-banner-dot");
    const name = document.getElementById("file-banner-name");
    banner.className = state === "none" ? "banner-none" : "";
    dot.className = `file-dot file-dot-${state === "live" ? "live" : state === "selected" ? "selected" : "none"}`;
    name.textContent = filename || "No file selected";
}

function renderFileTree(files) {
    const tree = document.getElementById("file-tree");
    tree.innerHTML = "";

    // Group by first directory segment
    const rootFiles = [];
    const dirs = {}; // dirName → [{fullPath, name}]
    files.forEach((f) => {
        const slashIdx = f.indexOf("/");
        if (slashIdx === -1) {
            rootFiles.push(f);
        } else {
            const dir = f.substring(0, slashIdx);
            const name = f.substring(slashIdx + 1);
            if (!dirs[dir]) dirs[dir] = [];
            dirs[dir].push({ fullPath: f, name });
        }
    });

    // Root files
    if (rootFiles.length > 0) {
        const label = document.createElement("div");
        label.className = "file-tree-group-label";
        label.textContent = "input/ (root)";
        tree.appendChild(label);
        rootFiles.forEach((f) => tree.appendChild(makeFileItem(f, f, true)));
    }

    // Subdirectories
    Object.entries(dirs).sort(([a], [b]) => a.localeCompare(b)).forEach(([dir, items]) => {
        const header = document.createElement("div");
        header.className = "file-tree-dir-header";
        const arrow = document.createElement("span");
        arrow.className = "file-tree-dir-arrow";
        arrow.textContent = "▸";
        header.appendChild(arrow);
        header.appendChild(document.createTextNode(" 📁 " + dir + "/"));
        tree.appendChild(header);

        const children = document.createElement("div");
        children.className = "file-tree-dir-children";
        items.forEach(({ fullPath, name }) => children.appendChild(makeFileItem(fullPath, name, false)));
        tree.appendChild(children);

        header.addEventListener("click", () => {
            const expanded = children.classList.toggle("expanded");
            arrow.textContent = expanded ? "▾" : "▸";
        });
    });
}

function makeFileItem(fullPath, displayName, isRoot) {
    const item = document.createElement("div");
    item.className = "file-tree-item" + (isRoot ? " root-item" : "");
    const isLive = fullPath === selectedFile;
    if (isLive) item.classList.add("live-item");

    item.appendChild(document.createTextNode(displayName));
    if (isLive) {
        const badge = document.createElement("span");
        badge.className = "file-tree-live-badge";
        badge.textContent = "LIVE";
        item.appendChild(badge);
    }
    item.addEventListener("click", () => {
        selectedFile = fullPath;
        setBannerState("selected", fullPath);
        togglePicker(false);
    });
    return item;
}

function togglePicker(forceState) {
    filePickerOpen = forceState !== undefined ? forceState : !filePickerOpen;
    document.getElementById("file-picker").classList.toggle("hidden", !filePickerOpen);
}

async function refreshOutputsList() {
    try {
        const resp = await fetch("/api/outputs");
        const { files } = await resp.json();
        const ul = document.getElementById("outputs-list");
        ul.innerHTML = "";
        if (files.length === 0) {
            const li = document.createElement("li");
            li.style.color = "#9ca3af";
            li.textContent = "No outputs yet.";
            ul.appendChild(li);
            return;
        }
        files.forEach((f) => {
            const li = document.createElement("li");
            li.innerHTML = `<a href="/api/download/${encodeURIComponent(f)}" download>${escHtml(f)}</a>`;
            ul.appendChild(li);
        });
    } catch (e) {
        console.warn("[outputs] could not load outputs list", e);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initFileBanner();
    refreshOutputsList();
    loadScriptsList();
    document.getElementById("file-change-btn").addEventListener("click", () => {
        if (!filePickerOpen) renderFileTree(allFiles);
        togglePicker();
    });
    document.getElementById("file-refresh-btn").addEventListener("click", loadFileList);
});

// ── Script management ─────────────────────────────────────────────────────────

let currentScriptFilename = null;

async function loadScriptsList() {
    try {
        const resp = await fetch("/api/scripts");
        const { scripts } = await resp.json();
        renderScriptsList(scripts);
    } catch (e) {
        console.warn("[scripts] could not load scripts list", e);
    }
}

function renderScriptsList(scripts) {
    const ul = document.getElementById("scripts-list");
    ul.innerHTML = "";
    if (!scripts || scripts.length === 0) {
        const li = document.createElement("li");
        li.style.color = "#9ca3af";
        li.textContent = "No scripts yet.";
        ul.appendChild(li);
        return;
    }
    scripts.forEach((s) => {
        const li = document.createElement("li");
        const badge = document.createElement("span");
        badge.className = `script-type-badge ${s.type}`;
        badge.textContent = s.type === "python" ? "PY" : "iL";
        badge.title = s.type === "python" ? "Python script" : "iLogic rule";

        const link = document.createElement("a");
        link.href = "#";
        link.textContent = s.filename;
        link.title = s.description || s.filename;
        link.addEventListener("click", (e) => {
            e.preventDefault();
            openScriptViewer(s.filename);
        });

        li.appendChild(badge);
        li.appendChild(link);
        if (s.description) {
            const desc = document.createElement("span");
            desc.className = "script-desc";
            desc.textContent = s.description;
            desc.title = s.description;
            li.appendChild(desc);
        }
        ul.appendChild(li);
    });
}

async function openScriptViewer(filename) {
    try {
        const resp = await fetch(`/api/scripts/${encodeURIComponent(filename)}`);
        if (!resp.ok) throw new Error("Not found");
        const data = await resp.json();
        currentScriptFilename = filename;

        document.getElementById("script-modal-title").textContent = filename;
        document.getElementById("script-modal-code").textContent = data.content;
        document.getElementById("script-modal-download").href = `/api/scripts/download/${encodeURIComponent(filename)}`;
        document.getElementById("script-modal-download").textContent = "Download";
        document.getElementById("script-modal-run").disabled = isRunning;

        document.getElementById("script-modal").classList.remove("hidden");
    } catch (e) {
        showErrorAlert(`Could not load script: ${e.message}`);
    }
}

function closeScriptViewer() {
    document.getElementById("script-modal").classList.add("hidden");
    currentScriptFilename = null;
}

function runCurrentScript() {
    if (!currentScriptFilename || !ws || isRunning) return;
    ws.send(JSON.stringify({ type: "run_script", filename: currentScriptFilename }));
    closeScriptViewer();
    setRunning(true);
}

// Modal event listeners
document.getElementById("script-modal-close").addEventListener("click", closeScriptViewer);
document.getElementById("script-modal-run").addEventListener("click", runCurrentScript);

// Close modal on overlay click (outside content)
document.getElementById("script-modal").addEventListener("click", (e) => {
    if (e.target.id === "script-modal") {
        closeScriptViewer();
    }
});

// Close modal on Escape key
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("script-modal").classList.contains("hidden")) {
        closeScriptViewer();
    }
});

// Handle script_list events from WebSocket
function handleScriptListEvent(event) {
    renderScriptsList(event.scripts);
}
