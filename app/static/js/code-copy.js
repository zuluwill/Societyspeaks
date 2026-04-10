(function () {
  function setButtonState(btn, text, resetAfterMs) {
    var original = btn.textContent;
    btn.textContent = text;
    if (resetAfterMs) {
      setTimeout(function () {
        btn.textContent = original;
      }, resetAfterMs);
    }
  }

  function fallbackCopyText(text) {
    var textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    try {
      return document.execCommand("copy");
    } finally {
      document.body.removeChild(textarea);
    }
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }

    return new Promise(function (resolve, reject) {
      try {
        if (fallbackCopyText(text)) {
          resolve();
          return;
        }
      } catch (error) {
        reject(error);
        return;
      }

      reject(new Error("Copy unavailable"));
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".code-block").forEach(function (block) {
      var btn = block.querySelector(".copy-btn");
      if (!btn) return;
      if (!btn.getAttribute("aria-label")) {
        btn.setAttribute("aria-label", "Copy code to clipboard");
      }
      btn.addEventListener("click", function () {
        var el = block.querySelector("pre:not([hidden])") || block.querySelector("pre") || block.querySelector("code");
        if (!el) return;
        copyText(el.textContent.trim())
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
