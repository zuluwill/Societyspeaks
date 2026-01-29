/**
 * Open in Reader App dropdown: share to reader apps (ElevenReader, Pocket, etc.)
 * Reads URLs/title from container data attributes (no inline user content in handlers).
 */
(function () {
  "use strict";

  function toggleListenMenu(button) {
    var menu = button.nextElementSibling;
    var chevron = button.querySelector(".listen-chevron");
    var isHidden = !menu || menu.classList.contains("hidden");

    document.querySelectorAll(".listen-menu").forEach(function (m) {
      if (m !== menu) {
        m.classList.add("hidden");
        var prev = m.previousElementSibling;
        if (prev) {
          prev.setAttribute("aria-expanded", "false");
          var ch = prev.querySelector(".listen-chevron");
          if (ch) ch.style.transform = "";
        }
      }
    });

    if (!menu) return;
    if (isHidden) {
      menu.classList.remove("hidden");
      button.setAttribute("aria-expanded", "true");
      if (chevron) chevron.style.transform = "rotate(180deg)";
    } else {
      menu.classList.add("hidden");
      button.setAttribute("aria-expanded", "false");
      if (chevron) chevron.style.transform = "";
    }
  }

  function shareToReaderApp(app, url, title) {
    var readerUrl =
      url && url.indexOf("/reader") !== -1 ? url : (url || "") + "/reader";

    switch (app) {
      case "elevenreader":
        copyAndNotify(
          readerUrl,
          "Link copied! Open the ElevenReader app and paste this URL to listen.",
        );
        break;
      case "pocket":
        showListenToast("Opening Pocket...", "info");
        window.open(
          "https://getpocket.com/save?url=" + encodeURIComponent(readerUrl),
          "_blank",
        );
        break;
      case "instapaper":
        showListenToast("Opening Instapaper...", "info");
        window.open(
          "https://www.instapaper.com/hello2?url=" +
            encodeURIComponent(readerUrl),
          "_blank",
        );
        break;
      case "native":
      default:
        if (navigator.share) {
          navigator
            .share({ title: title || "Brief", url: readerUrl })
            .catch(function (e) {
              if (e.name !== "AbortError") copyAndNotify(readerUrl);
            });
        } else {
          copyAndNotify(readerUrl);
        }
        break;
    }
  }

  function copyAndNotify(url, message) {
    message = message || "Reader link copied to clipboard!";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard
        .writeText(url)
        .then(function () {
          showListenToast(message, "success");
        })
        .catch(function () {
          fallbackCopy(url);
          showListenToast(message, "success");
        });
    } else {
      fallbackCopy(url);
      showListenToast(message, "success");
    }
  }

  function fallbackCopy(url) {
    var input = document.createElement("input");
    input.value = url;
    document.body.appendChild(input);
    input.select();
    try {
      document.execCommand("copy");
    } catch (e) {}
    document.body.removeChild(input);
  }

  function showListenToast(message, type) {
    type = type || "info";
    if (typeof window.showToastNotification === "function") {
      window.showToastNotification(message, type);
    } else {
      alert(message);
    }
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    var container = target.closest && target.closest(".listen-with-container");
    if (container) {
      var toggleBtn = container.querySelector('button[aria-haspopup="true"]');
      if (target === toggleBtn || toggleBtn.contains(target)) {
        event.preventDefault();
        toggleListenMenu(toggleBtn);
        return;
      }
      var menuItem = target.closest && target.closest("[data-action]");
      if (menuItem && menuItem.getAttribute("data-action")) {
        var action = menuItem.getAttribute("data-action");
        var readerUrl = container.getAttribute("data-reader-url") || "";
        var title = container.getAttribute("data-brief-title") || "Brief";
        shareToReaderApp(action, readerUrl, title);
        var menu = container.querySelector(".listen-menu");
        if (menu) menu.classList.add("hidden");
        if (toggleBtn) {
          toggleBtn.setAttribute("aria-expanded", "false");
          var chev = toggleBtn.querySelector(".listen-chevron");
          if (chev) chev.style.transform = "";
        }
        return;
      }
    }
    document.querySelectorAll(".listen-menu").forEach(function (menu) {
      menu.classList.add("hidden");
      var btn = menu.previousElementSibling;
      if (btn) {
        btn.setAttribute("aria-expanded", "false");
        var chevron = btn.querySelector(".listen-chevron");
        if (chevron) chevron.style.transform = "";
      }
    });
  });

  // Handle ?listen=true URL parameter (from email CTAs)
  function handleListenParam() {
    var params = new URLSearchParams(window.location.search);
    if (params.get("listen") === "true") {
      var container = document.querySelector(".listen-with-container");
      if (!container) return;

      // Scroll to the reader app dropdown
      setTimeout(function () {
        container.scrollIntoView({ behavior: "smooth", block: "center" });

        // Add highlight effect
        container.style.transition = "box-shadow 0.3s ease, transform 0.3s ease";
        container.style.boxShadow = "0 0 0 4px rgba(124, 58, 237, 0.3)";
        container.style.transform = "scale(1.02)";
        container.style.borderRadius = "12px";

        // Open the dropdown
        var toggleBtn = container.querySelector('button[aria-haspopup="true"]');
        if (toggleBtn) {
          setTimeout(function () {
            toggleListenMenu(toggleBtn);
          }, 500);
        }

        // Remove highlight after a few seconds
        setTimeout(function () {
          container.style.boxShadow = "";
          container.style.transform = "";
        }, 3000);

        // Clean up URL (remove ?listen=true)
        if (window.history && window.history.replaceState) {
          var cleanUrl = window.location.pathname + window.location.hash;
          window.history.replaceState({}, document.title, cleanUrl);
        }
      }, 300);
    }
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", handleListenParam);
  } else {
    handleListenParam();
  }

  window.toggleListenMenu = toggleListenMenu;
})();
