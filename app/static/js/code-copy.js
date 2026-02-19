document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".code-block").forEach(function (block) {
    var btn = block.querySelector(".copy-btn");
    var pre = block.querySelector("pre");
    if (!btn || !pre) return;
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(pre.textContent).then(function () {
        btn.textContent = "Copied!";
        setTimeout(function () {
          btn.textContent = "Copy";
        }, 2000);
      });
    });
  });
});
