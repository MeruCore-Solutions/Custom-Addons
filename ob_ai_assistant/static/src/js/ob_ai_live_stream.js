/** @odoo-module **/

// Live AI reasoning stream subscriber.
//
// Strategy: the agent solver publishes events to two bus channels:
//   - per-session: ob_ai_session_<session_uuid>
//   - per-user:    ob_ai_user_<user_id>   <-- this module subscribes here
//
// We subscribe once per page-load to the current user's channel, then render
// each incoming event into every visible .o_ob_ai_live_stream element on the
// page. This avoids needing per-render data attributes (which Odoo's arch
// validator forbids via t-att-*).

import { browser } from "@web/core/browser/browser";

const STREAM_SELECTOR = ".o_ob_ai_live_stream";
const EVENTS_CONTAINER_CLASS = "o_ob_ai_live_stream_events";
const STATUS_CLASS = "o_ob_ai_live_stream_status";

// ---------- Formatting helpers ----------

function formatToolName(toolCode) {
    if (!toolCode) {
        return "";
    }
    return toolCode.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function truncate(text, maxLen = 200) {
    if (!text) {
        return "";
    }
    const str = String(text);
    return str.length <= maxLen ? str : str.slice(0, maxLen) + "...";
}

function previewArgs(args) {
    if (!args || typeof args !== "object") {
        return "";
    }
    const keys = Object.keys(args).slice(0, 4);
    return keys.map((k) => `${k}=${truncate(JSON.stringify(args[k]), 40)}`).join(", ");
}

function escapeHtml(text) {
    if (text === undefined || text === null) {
        return "";
    }
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// ---------- DOM helpers ----------

function getAllStreamRoots() {
    return Array.from(document.querySelectorAll(STREAM_SELECTOR));
}

function ensureEventsContainer(streamRoot) {
    let container = streamRoot.querySelector("." + EVENTS_CONTAINER_CLASS);
    if (!container) {
        container = document.createElement("div");
        container.className = EVENTS_CONTAINER_CLASS;
        streamRoot.appendChild(container);
    }
    return container;
}

function updateStreamStatus(text) {
    document.querySelectorAll("." + STATUS_CLASS).forEach((el) => {
        el.textContent = text;
    });
}

function clearAllStreams() {
    getAllStreamRoots().forEach((streamRoot) => {
        const container = streamRoot.querySelector("." + EVENTS_CONTAINER_CLASS);
        if (container) {
            container.innerHTML = "";
        }
    });
}

function renderEventIntoAllStreams(event) {
    const payload = event.payload || event || {};
    const eventType = event.type || payload.type;
    let icon = "•";
    let label = "";
    let detail = "";

    switch (eventType) {
        case "session_started":
            icon = "▸";
            label = "Session started";
            clearAllStreams();
            updateStreamStatus("AI started thinking...");
            break;
        case "thinking":
            icon = "◌";
            label = payload.phase === "reflect"
                ? "Reflecting on tool results..."
                : `Planning (step ${payload.step || ""})`;
            updateStreamStatus("AI is thinking...");
            break;
        case "tool_call":
            icon = "→";
            label = `Calling ${formatToolName(payload.tool)}`;
            detail = previewArgs(payload.arguments);
            break;
        case "tool_result": {
            icon = payload.status === "success" ? "✓"
                : (payload.status === "pending_approval" ? "⏸" : "✗");
            label = `${formatToolName(payload.tool)} → ${payload.status || "?"}`;
            if (payload.preview && typeof payload.preview === "object") {
                if (Array.isArray(payload.preview.keys)) {
                    detail = `returned: ${payload.preview.keys.join(", ")}`;
                } else if (payload.preview.error) {
                    detail = `error: ${truncate(payload.preview.error, 120)}`;
                }
            }
            break;
        }
        case "reflection":
            icon = "💭";
            label = "Reflection";
            detail = truncate(payload.text, 240);
            break;
        case "final_answer":
            icon = "✓";
            label = "Final answer ready";
            updateStreamStatus("Done");
            break;
        case "done":
            icon = "✓";
            label = "Done";
            updateStreamStatus("Done");
            break;
        case "error":
            icon = "✗";
            label = "Error";
            detail = truncate(payload.message, 240);
            updateStreamStatus("Error");
            break;
        default:
            label = eventType || "event";
    }

    const html = `
        <span class="o_ob_ai_stream_icon">${escapeHtml(icon)}</span>
        <span class="o_ob_ai_stream_label">${escapeHtml(label)}</span>
        ${detail ? `<span class="o_ob_ai_stream_detail">${escapeHtml(detail)}</span>` : ""}
    `;

    getAllStreamRoots().forEach((streamRoot) => {
        const container = ensureEventsContainer(streamRoot);
        const item = document.createElement("div");
        item.className = "o_ob_ai_stream_event o_ob_ai_stream_event_" + (eventType || "info");
        item.innerHTML = html;
        container.appendChild(item);
        container.scrollTop = container.scrollHeight;
    });
}

// ---------- Bus subscription ----------

let subscribed = false;

function getCurrentUserId() {
    try {
        if (window.odoo && window.odoo.session_info && window.odoo.session_info.uid) {
            return window.odoo.session_info.uid;
        }
        if (window.odoo && window.odoo.__WOWL_DEBUG__) {
            const env = window.odoo.__WOWL_DEBUG__.root && window.odoo.__WOWL_DEBUG__.root.env;
            if (env && env.services && env.services.user && env.services.user.userId) {
                return env.services.user.userId;
            }
        }
    } catch (e) { /* ignore */ }
    return null;
}

function getBusService() {
    try {
        if (window.odoo && window.odoo.__WOWL_DEBUG__) {
            const env = window.odoo.__WOWL_DEBUG__.root && window.odoo.__WOWL_DEBUG__.root.env;
            if (env && env.services && env.services.bus_service) {
                return env.services.bus_service;
            }
        }
    } catch (e) { /* ignore */ }
    return null;
}

function subscribeToUserChannel() {
    if (subscribed) {
        return;
    }
    const userId = getCurrentUserId();
    const bus = getBusService();
    if (!userId || !bus) {
        // Retry shortly — services may not be ready yet on first paint
        browser.setTimeout(subscribeToUserChannel, 600);
        return;
    }
    const channel = "ob_ai_user_" + userId;
    try {
        bus.addChannel(channel);
        bus.addEventListener("notification", (ev) => {
            const notifications = ev && ev.detail ? ev.detail : [];
            notifications.forEach((notif) => {
                if (!notif || notif.type !== "ob_ai_event") {
                    return;
                }
                renderEventIntoAllStreams(notif.payload || {});
            });
        });
        subscribed = true;
    } catch (e) {
        // Try again later
        browser.setTimeout(subscribeToUserChannel, 1000);
    }
}

// ---------- Init ----------

if (!browser.__obAiLiveStreamInitialized) {
    browser.__obAiLiveStreamInitialized = true;
    const init = () => {
        subscribeToUserChannel();
    };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
}
