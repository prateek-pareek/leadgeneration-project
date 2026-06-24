(function () {
  const { runFill } = window.ProspectOSFill;

  function findHnEditor() {
    return document.querySelector('textarea[name="text"]');
  }

  async function init() {
    await runFill({
      platform: "hackernews",
      findEditor: findHnEditor,
    });
  }

  init();
})();
