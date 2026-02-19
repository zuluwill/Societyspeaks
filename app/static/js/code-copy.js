document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".code-block").forEach(function (block) {
    var btn = block.querySelector(".copy-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var el = block.querySelector("pre:not([hidden])") || block.querySelector("pre") || block.querySelector("code");
      if (!el) return;
      navigator.clipboard.writeText(el.textContent).then(function () {
        btn.textContent = "Copied!";
        setTimeout(function () {
          btn.textContent = "Copy";
        }, 2000);
      });
    });
  });
});
