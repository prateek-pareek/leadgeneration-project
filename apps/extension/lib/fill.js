/**
 * Shared DOM helpers for auto-filling comment boxes.
 * Attached to window.ProspectOSFill for content scripts.
 */
(function () {
  const BANNER_ID = "prospectos-comment-assist-banner";

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitFor(findFn, timeoutMs = 15000, intervalMs = 400) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const el = findFn();
      if (el) return el;
      await sleep(intervalMs);
    }
    return null;
  }

  function fillContentEditable(el, text) {
    el.focus();
    el.innerHTML = "";
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillTextarea(el, text) {
    el.focus();
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value"
    )?.set;
    if (nativeInputValueSetter) {
      nativeInputValueSetter.call(el, text);
    } else {
      el.value = text;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function urlMatchesPost(currentHref, postUrl) {
    if (!postUrl) return true;
    try {
      const current = new URL(currentHref);
      const target = new URL(postUrl);
      if (current.hostname.replace(/^www\./, "") !== target.hostname.replace(/^www\./, "")) {
        return false;
      }
      const currentPath = current.pathname.replace(/\/$/, "");
      const targetPath = target.pathname.replace(/\/$/, "");
      if (currentPath === targetPath) return true;
      if (currentPath.includes(targetPath) || targetPath.includes(currentPath)) return true;
      const currentId = extractActivityId(currentHref);
      const targetId = extractActivityId(postUrl);
      return Boolean(currentId && targetId && currentId === targetId);
    } catch {
      return true;
    }
  }

  function extractActivityId(url) {
    const patterns = [
      /activity[:-](\d+)/i,
      /posts\/([^/?]+)/i,
      /comments\/([^/?]+)/i,
      /status\/(\d+)/i,
    ];
    for (const pat of patterns) {
      const m = url.match(pat);
      if (m) return m[1];
    }
    return null;
  }

  function showBanner(text) {
    let banner = document.getElementById(BANNER_ID);
    if (!banner) {
      banner = document.createElement("div");
      banner.id = BANNER_ID;
      banner.style.cssText = [
        "position:fixed",
        "bottom:20px",
        "right:20px",
        "z-index:2147483647",
        "max-width:360px",
        "padding:12px 16px",
        "border-radius:10px",
        "background:#1e40af",
        "color:#fff",
        "font:14px/1.4 system-ui,-apple-system,sans-serif",
        "box-shadow:0 8px 24px rgba(0,0,0,.2)",
        "display:flex",
        "align-items:flex-start",
        "gap:10px",
      ].join(";");
      document.body.appendChild(banner);
    }
    banner.innerHTML = `
      <div style="flex:1">
        <strong style="display:block;margin-bottom:4px">ProspectOS</strong>
        <span>${text}</span>
      </div>
      <button type="button" id="${BANNER_ID}-close" style="background:transparent;border:none;color:#fff;font-size:18px;cursor:pointer;line-height:1">×</button>
    `;
    document.getElementById(`${BANNER_ID}-close`)?.addEventListener("click", () => banner.remove());
    setTimeout(() => banner?.remove(), 12000);
  }

  function normalizePlatform(p) {
    const v = (p || "").toLowerCase();
    if (v === "x") return "twitter";
    if (v === "hn") return "hackernews";
    if (v === "ph") return "producthunt";
    return v;
  }

  async function getPending(platform) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ action: "getPendingComment" }, (response) => {
        const pending = response?.pending;
        if (!pending?.text) {
          resolve(null);
          return;
        }
        const expected = normalizePlatform(platform);
        const actual = normalizePlatform(pending.platform);
        if (expected && actual && expected !== actual) {
          resolve(null);
          return;
        }
        if (!urlMatchesPost(window.location.href, pending.postUrl)) {
          resolve(null);
          return;
        }
        resolve(pending);
      });
    });
  }

  async function runFill({ platform, findEditor, afterFill }) {
    const pending = await getPending(platform);
    if (!pending) return;

    const editor = await waitFor(findEditor);
    if (!editor) {
      showBanner("Comment draft ready — open the reply box and click Assist again from ProspectOS.");
      return;
    }

    if (editor.tagName === "TEXTAREA") {
      fillTextarea(editor, pending.text);
    } else {
      fillContentEditable(editor, pending.text);
    }

    if (typeof afterFill === "function") afterFill(editor);
    showBanner("Draft comment filled. Review it, then click Post yourself.");
  }

  window.ProspectOSFill = {
    waitFor,
    fillContentEditable,
    fillTextarea,
    showBanner,
    getPending,
    runFill,
    urlMatchesPost,
  };
})();
