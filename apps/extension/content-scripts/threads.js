(function () {
  const { runFill } = window.ProspectOSFill;

  function findThreadsEditor() {
    const selectors = [
      'div[contenteditable="true"][role="textbox"]',
      'div[contenteditable="true"][aria-label*="reply" i]',
      'div[contenteditable="true"][data-lexical-editor="true"]',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) return el;
    }
    return null;
  }

  async function init() {
    await runFill({
      platform: "threads",
      findEditor: findThreadsEditor,
    });
  }

  init();
  const observer = new MutationObserver(() => init());
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 20000);
})();
