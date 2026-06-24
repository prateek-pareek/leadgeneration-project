const STORAGE_KEY = "prospectos_pending_comment";
const TTL_MS = 30 * 60 * 1000; // 30 minutes

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action === "setPendingComment") {
    const payload = message.payload ?? {};
    const record = {
      text: payload.text ?? "",
      postUrl: payload.postUrl ?? "",
      platform: payload.platform ?? "",
      draftId: payload.draftId ?? "",
      createdAt: Date.now(),
    };
    chrome.storage.session.set({ [STORAGE_KEY]: record }, () => {
      sendResponse({ ok: true });
    });
    return true;
  }

  if (message?.action === "getPendingComment") {
    chrome.storage.session.get(STORAGE_KEY, (data) => {
      const record = data[STORAGE_KEY];
      if (!record || Date.now() - record.createdAt > TTL_MS) {
        sendResponse({ pending: null });
        return;
      }
      sendResponse({ pending: record });
    });
    return true;
  }

  if (message?.action === "clearPendingComment") {
    chrome.storage.session.remove(STORAGE_KEY, () => sendResponse({ ok: true }));
    return true;
  }

  if (message?.action === "ping") {
    sendResponse({ ok: true, version: "1.0.0" });
    return true;
  }
});
