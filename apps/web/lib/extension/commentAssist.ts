/**
 * ProspectOS browser extension integration.
 * Communicates with the Comment Assist extension via postMessage.
 */

export type CommentAssistPayload = {
  text: string;
  postUrl: string;
  platform: string;
  draftId: string;
};

type ExtensionMessage =
  | { type: "PROSPECTOS_EXTENSION_READY"; version?: string }
  | { type: "PROSPECTOS_COMMENT_STORED"; ok: boolean; draftId?: string };

let extensionDetected = false;
let detectPromise: Promise<boolean> | null = null;

export function isExtensionInstalled(): boolean {
  return extensionDetected;
}

export function detectExtension(timeoutMs = 800): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (extensionDetected) return Promise.resolve(true);
  if (detectPromise) return detectPromise;

  detectPromise = new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve(extensionDetected);
      detectPromise = null;
    }, timeoutMs);

    function onMessage(event: MessageEvent) {
      if (event.source !== window) return;
      const data = event.data as ExtensionMessage;
      if (data?.type === "PROSPECTOS_EXTENSION_READY") {
        extensionDetected = true;
        window.clearTimeout(timer);
        window.removeEventListener("message", onMessage);
        resolve(true);
        detectPromise = null;
      }
    }

    window.addEventListener("message", onMessage);
    window.postMessage({ type: "PROSPECTOS_PING_EXTENSION" }, window.location.origin);
  });

  return detectPromise;
}

export function storeCommentForExtension(payload: CommentAssistPayload): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof window === "undefined") {
      resolve(false);
      return;
    }

    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve(false);
    }, 3000);

    function onMessage(event: MessageEvent) {
      if (event.source !== window) return;
      const data = event.data as ExtensionMessage;
      if (
        data?.type === "PROSPECTOS_COMMENT_STORED" &&
        data.draftId === payload.draftId
      ) {
        window.clearTimeout(timer);
        window.removeEventListener("message", onMessage);
        resolve(Boolean(data.ok));
      }
    }

    window.addEventListener("message", onMessage);
    window.postMessage(
      {
        type: "PROSPECTOS_SET_COMMENT",
        text: payload.text,
        postUrl: payload.postUrl,
        platform: payload.platform,
        draftId: payload.draftId,
      },
      window.location.origin
    );
  });
}

export async function assistOpenPost(payload: CommentAssistPayload): Promise<{
  extensionUsed: boolean;
  opened: boolean;
}> {
  await navigator.clipboard.writeText(payload.text).catch(() => {});

  const hasExtension = await detectExtension();
  let extensionUsed = false;
  if (hasExtension) {
    extensionUsed = await storeCommentForExtension(payload);
  }

  if (payload.postUrl) {
    window.open(payload.postUrl, "_blank", "noopener,noreferrer");
  }

  return { extensionUsed, opened: Boolean(payload.postUrl) };
}
