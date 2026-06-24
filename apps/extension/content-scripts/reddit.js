(function () {
  const { runFill } = window.ProspectOSFill;

  function findRedditEditor() {
    const textarea = document.querySelector('textarea[name="body"], textarea#innerTextArea');
    if (textarea) return textarea;
    const ce = document.querySelector(
      'div[contenteditable="true"][role="textbox"], shreddit-composer div[contenteditable="true"]'
    );
    return ce;
  }

  async function init() {
    await runFill({
      platform: "reddit",
      findEditor: findRedditEditor,
    });
  }

  init();
  const observer = new MutationObserver(() => init());
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 20000);
})();
