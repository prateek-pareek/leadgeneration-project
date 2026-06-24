/**
 * Bridge between ProspectOS web app and the extension.
 * Listens for postMessage from the dashboard and stores pending comments.
 */

(function () {
  const ORIGIN = window.location.origin;

  function announceReady() {
    window.postMessage({ type: "PROSPECTOS_EXTENSION_READY", version: "1.0.0" }, ORIGIN);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== ORIGIN) return;

    const data = event.data;
    if (!data || typeof data.type !== "string") return;

    if (data.type === "PROSPECTOS_PING_EXTENSION") {
      announceReady();
      return;
    }

    if (data.type === "PROSPECTOS_SET_COMMENT") {
      chrome.runtime.sendMessage(
        {
          action: "setPendingComment",
          payload: {
            text: data.text,
            postUrl: data.postUrl,
            platform: data.platform,
            draftId: data.draftId,
          },
        },
        (response) => {
          window.postMessage(
            {
              type: "PROSPECTOS_COMMENT_STORED",
              ok: Boolean(response?.ok),
              draftId: data.draftId,
            },
            ORIGIN
          );
        }
      );
      return;
    }

    if (data.type === "PROSPECTOS_CLEAR_COMMENT") {
      chrome.runtime.sendMessage({ action: "clearPendingComment" });
    }
  });

  announceReady();
})();
