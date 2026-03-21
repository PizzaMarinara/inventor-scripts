/* app.js — Inventor Agent WebSocket client
 * Handles:
 *   - WebSocket connection lifecycle (auto-reconnect)
 *   - Sending chat messages + extract-parameters shortcut
 *   - Rendering server events: tool_start, tool_result, done, error
 *   - File list / outputs list population from REST API
 *   - Parameters table rendering when done event contains a JSON block
 */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────

const WS_URL = `ws://${location.host}/ws/chat`;
let ws = null;
let isRunning = false;
let currentAgentBubble = null;   // the <div class="bubble-agent"> being built

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
    const file = document.getElementById("file-select").value;
    ws.send(JSON.stringify({ type: "chat", message, file }));
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
    const file = document.getElementById("file-select").value;
    if (!file || isRunning || !ws) return;
    const instruction = `Extract all parameters from ${file} and show them as a table.`;
    ws.send(JSON.stringify({ type: "chat", message: instruction, file }));
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

async function loadFileList() {
    try {
        const resp = await fetch("/api/files");
        const { files } = await resp.json();
        const sel = document.getElementById("file-select");
        files.forEach((f) => {
            const opt = document.createElement("option");
            opt.value = f;
            opt.textContent = f;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.warn("[files] could not load file list", e);
    }
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
    loadFileList();
    refreshOutputsList();
});
