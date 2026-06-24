(function () {
  const { runFill } = window.ProspectOSFill;

  function findTwitterEditor() {
    const selectors = [
      'div[data-testid="tweetTextarea_0"]',
      'div[contenteditable="true"][role="textbox"][data-testid*="tweet" i]',
      'div.public-DraftEditor-content[contenteditable="true"]',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) return el;
    }
    return null;
  }

  async function init() {
    await runFill({
      platform: "twitter",
      findEditor: findTwitterEditor,
    });
  }

  init();
  const observer = new MutationObserver(() => init());
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 20000);
})();
