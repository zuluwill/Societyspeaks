(function () {
  if (!navigator.clipboard || !window.isSecureContext) return;

  function setButtonState(btn, text, resetAfterMs) {
    var original = btn.textContent;
    btn.textContent = text;
    if (resetAfterMs) {
      setTimeout(function () {
        btn.textContent = original;
      }, resetAfterMs);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".code-block").forEach(function (block) {
      var btn = block.querySelector(".copy-btn");
      if (!btn) return;
      btn.addEventListener("click", function () {
        var el = block.querySelector("pre:not([hidden])") || block.querySelector("pre") || block.querySelector("code");
        if (!el) return;
        navigator.clipboard
          .writeText(el.textContent.trim())
          .then(function () {
            setButtonState(btn, "Copied!", 2000);
          })
          .catch(function () {
            setButtonState(btn, "Copy failed", 2000);
          });
      });
    });
  });
})();
