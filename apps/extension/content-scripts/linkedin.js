(function () {
  const { runFill } = window.ProspectOSFill;

  function findLinkedInEditor() {
    const selectors = [
      'div.comments-comment-texteditor div.ql-editor[contenteditable="true"]',
      'div.comments-comment-box-comment__text-editor div[contenteditable="true"]',
      'div.comment-box__contenteditable[contenteditable="true"]',
      'div[role="textbox"][contenteditable="true"][aria-label*="comment" i]',
      'div[role="textbox"][contenteditable="true"][data-testid*="comment" i]',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) return el;
    }
    return null;
  }

  function tryOpenCommentBox() {
    const buttons = [
      'button[aria-label*="Comment" i]',
      'button.comments-comment-box__open-button',
      'button[aria-label*="comment on" i]',
    ];
    for (const sel of buttons) {
      const btn = document.querySelector(sel);
      if (btn) {
        btn.click();
        return true;
      }
    }
    return false;
  }

  async function init() {
    tryOpenCommentBox();
    await runFill({
      platform: "linkedin",
      findEditor: findLinkedInEditor,
    });
  }

  init();

  const observer = new MutationObserver(() => {
    init();
  });
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 20000);
})();
