(function () {
  const { runFill } = window.ProspectOSFill;

  function findDevtoEditor() {
    return (
      document.querySelector("#comment_body") ||
      document.querySelector('textarea[name="comment[body]"]') ||
      document.querySelector('textarea[placeholder*="comment" i]')
    );
  }

  async function init() {
    await runFill({
      platform: "devto",
      findEditor: findDevtoEditor,
    });
  }

  init();
})();
