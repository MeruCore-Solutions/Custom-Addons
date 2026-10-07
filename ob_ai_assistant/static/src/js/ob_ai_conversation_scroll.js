/** @odoo-module **/

import { browser } from "@web/core/browser/browser";

const VIEWPORT_SELECTOR = ".o_ob_ai_conversation_form .o_ob_ai_message_viewport";
const FORM_SELECTOR = ".o_ob_ai_conversation_form";
const CHAT_WORKSPACE_SELECTOR = ".o_ob_ai_workspace_app";

function scrollViewportToLatest(viewport) {
    if (!viewport) {
        return;
    }
    browser.requestAnimationFrame(() => {
        const lastMessage = viewport.querySelector(".o_kanban_record:last-child");
        if (lastMessage) {
            const paddingBottom = parseFloat(getComputedStyle(viewport).paddingBottom || 0);
            const targetScrollTop =
                lastMessage.offsetTop + lastMessage.offsetHeight - viewport.clientHeight + paddingBottom;
            viewport.scrollTop = Math.max(targetScrollTop, 0);
            return;
        }
        viewport.scrollTop = viewport.scrollHeight;
    });
}

function bindViewport(viewport) {
    if (!viewport || viewport.dataset.obAiScrollBound === "1") {
        return;
    }
    viewport.dataset.obAiScrollBound = "1";
    const syncViewport = () => scrollViewportToLatest(viewport);
    const observer = new MutationObserver(() => syncViewport());
    const resizeObserver = new ResizeObserver(() => syncViewport());
    const streamContent =
        viewport.querySelector(".o_kanban_renderer") || viewport.querySelector(".o_ob_ai_message_stream");
    observer.observe(viewport, {
        childList: true,
        subtree: true,
        characterData: true,
    });
    if (streamContent) {
        resizeObserver.observe(streamContent);
    }
    syncViewport();
    browser.setTimeout(syncViewport, 50);
    browser.setTimeout(syncViewport, 250);
    browser.setTimeout(syncViewport, 750);
    browser.setTimeout(syncViewport, 1500);
    browser.setTimeout(syncViewport, 3000);
}

function isVisible(element) {
    return Boolean(element && element.offsetParent !== null);
}

function syncFormScrollLock(formRoot) {
    if (!formRoot) {
        return;
    }
    const workspace = formRoot.querySelector(CHAT_WORKSPACE_SELECTOR);
    const formView = formRoot.closest(".o_form_view");
    const contentContainer = formView && (formView.querySelector(":scope > .o_content") || formView.querySelector(".o_content"));
    if (!contentContainer) {
        return;
    }
    contentContainer.classList.toggle("o_ob_ai_chat_scroll_locked", isVisible(workspace));
}

function bindFormScrollLock(formRoot) {
    if (!formRoot || formRoot.dataset.obAiFormScrollLockBound === "1") {
        return;
    }
    formRoot.dataset.obAiFormScrollLockBound = "1";
    const syncLock = () => syncFormScrollLock(formRoot);
    const observer = new MutationObserver(() => syncLock());
    observer.observe(formRoot, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["class", "style"],
    });
    syncLock();
    browser.setTimeout(syncLock, 50);
    browser.setTimeout(syncLock, 250);
    browser.setTimeout(syncLock, 1000);
}

function initializeViewports(root = document) {
    root.querySelectorAll(VIEWPORT_SELECTOR).forEach((viewport) => bindViewport(viewport));
}

function initializeFormLocks(root = document) {
    root.querySelectorAll(FORM_SELECTOR).forEach((formRoot) => bindFormScrollLock(formRoot));
}

if (!browser.__obAiConversationScrollInitialized) {
    browser.__obAiConversationScrollInitialized = true;
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            initializeViewports();
            initializeFormLocks();
        }, { once: true });
    } else {
        initializeViewports();
        initializeFormLocks();
    }
    const rootObserver = new MutationObserver(() => {
        initializeViewports();
        initializeFormLocks();
    });
    rootObserver.observe(document.documentElement, {
        childList: true,
        subtree: true,
    });
}
