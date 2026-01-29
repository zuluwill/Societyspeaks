/**
 * Listen With dropdown: native audio, browser TTS, reader apps, share.
 * Reads URLs/title from container data attributes (no inline user content in handlers).
 */
(function () {
  "use strict";

  var ttsActive = false;

  function getContainer(buttonOrElement) {
    var el = buttonOrElement;
    while (el && !el.classList.contains("listen-with-container")) {
      el = el.parentElement;
    }
    return el;
  }

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

  function toggleBrowserTTS(button) {
    var synth = window.speechSynthesis;
    if (!synth) {
      showListenToast("Your browser doesn't support text-to-speech", "error");
      return;
    }

    var icon = button.querySelector(".tts-icon");
    var label = button.querySelector(".tts-label");

    if (synth.speaking || ttsActive) {
      synth.cancel();
      ttsActive = false;
      button.classList.remove("bg-green-50", "text-green-700");
      if (icon) {
        icon.classList.remove("bg-green-100", "text-green-600");
        icon.classList.add("bg-gray-100", "text-gray-600");
      }
      if (label) label.textContent = "Browser Read Aloud";
      showListenToast("Stopped reading", "info");
      return;
    }

    var articles = document.querySelectorAll("article");
    var text = "";
    if (articles.length > 0) {
      articles.forEach(function (article) {
        text += article.innerText + "\n\n";
      });
    } else {
      var prose = document.querySelector(".prose");
      var main = document.querySelector("main");
      text = prose ? prose.innerText : (main ? main.innerText : document.body.innerText);
    }
    if (!text.trim()) {
      showListenToast("No content found to read", "error");
      return;
    }

    // Show starting feedback immediately
    showListenToast("Starting read aloud...", "info");

    ttsActive = true;
    button.classList.add("bg-green-50", "text-green-700");
    if (icon) {
      icon.classList.remove("bg-gray-100", "text-gray-600");
      icon.classList.add("bg-green-100", "text-green-600");
    }
    if (label) label.textContent = "Stop Reading";

    var utterance = new SpeechSynthesisUtterance(text.substring(0, 10000));
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    // Wait for voices to load if needed
    var voices = synth.getVoices();
    if (voices.length === 0) {
      // Voices not loaded yet, wait a moment
      setTimeout(function() {
        voices = synth.getVoices();
        setVoiceAndSpeak(utterance, voices, synth, button, icon, label);
      }, 100);
    } else {
      setVoiceAndSpeak(utterance, voices, synth, button, icon, label);
    }
  }

  function setVoiceAndSpeak(utterance, voices, synth, button, icon, label) {
    var preferredVoice =
      voices.find(function (v) {
        return v.lang.indexOf("en") === 0 && v.name.indexOf("Google") !== -1;
      }) ||
      voices.find(function (v) {
        return v.lang.indexOf("en") === 0;
      });
    if (preferredVoice) utterance.voice = preferredVoice;

    utterance.onstart = function () {
      showListenToast("Reading aloud. Click again to stop.", "success");
    };

    utterance.onerror = function (e) {
      ttsActive = false;
      button.classList.remove("bg-green-50", "text-green-700");
      if (icon) {
        icon.classList.remove("bg-green-100", "text-green-600");
        icon.classList.add("bg-gray-100", "text-gray-600");
      }
      if (label) label.textContent = "Browser Read Aloud";
      if (e.error !== 'interrupted') {
        showListenToast("Speech failed: " + e.error, "error");
      }
    };

    utterance.onend = function () {
      ttsActive = false;
      button.classList.remove("bg-green-50", "text-green-700");
      if (icon) {
        icon.classList.remove("bg-green-100", "text-green-600");
        icon.classList.add("bg-gray-100", "text-gray-600");
      }
      if (label) label.textContent = "Browser Read Aloud";
    };
    synth.speak(utterance);
  }

  function playNativeAudio(url) {
    if (!url) return;
    var audio = new Audio(url);
    audio.play().catch(function (err) {
      console.error("Audio playback failed:", err);
      showListenToast("Failed to play audio", "error");
    });
  }

  function shareToReaderApp(app, url, title) {
    var readerUrl =
      url && url.indexOf("/reader") !== -1 ? url : (url || "") + "/reader";

    switch (app) {
      case "elevenreader":
        // ElevenReader doesn't have a registered URL scheme, so copy the link
        // and provide clear instructions
        copyAndNotify(
          readerUrl,
          "Link copied! Open the ElevenReader app and paste this URL to listen.",
        );
        break;
      case "pocket":
        // Open Pocket save page - note: may fail on dev domains
        showListenToast("Opening Pocket... (may not work with dev URLs)", "info");
        window.open(
          "https://getpocket.com/save?url=" + encodeURIComponent(readerUrl),
          "_blank",
        );
        break;
      case "instapaper":
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
        if (action === "native-audio") {
          playNativeAudio(container.getAttribute("data-audio-url"));
        } else if (action === "browser-tts") {
          toggleBrowserTTS(menuItem);
          return;
        } else {
          shareToReaderApp(action, readerUrl, title);
        }
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

  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = function () {
      window.speechSynthesis.getVoices();
    };
  }

  // Handle ?listen=true URL parameter (from email CTAs)
  function handleListenParam() {
    var params = new URLSearchParams(window.location.search);
    if (params.get("listen") === "true") {
      var container = document.querySelector(".listen-with-container");
      if (!container) return;

      // Scroll to the listen dropdown
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
