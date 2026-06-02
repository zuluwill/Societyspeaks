(function () {
  'use strict';

  // ----- Reminder opt-in (independent of the share card) -----
  (function setupReminderOptIn() {
    var form = document.querySelector('[data-reminder-form]');
    if (!form) return;

    var tzInput = form.querySelector('[data-reminder-tz]');
    if (tzInput) {
      try {
        var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (tz) tzInput.value = tz;
      } catch (e) { /* keep UTC default */ }
    }

    if (!window.fetch) return; // no-JS / old browsers fall back to normal POST

    var statusEl = form.querySelector('[data-reminder-status]');
    var submitBtn = form.querySelector('[data-reminder-submit]');
    var doneLabel = form.dataset.doneLabel || "You're set.";
    var errorLabel = form.dataset.errorLabel || 'Please try again.';

    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (submitBtn) submitBtn.disabled = true;
      if (statusEl) statusEl.textContent = '';

      var csrf = form.dataset.csrf || '';
      fetch(form.action, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
          'X-CSRFToken': csrf,
        },
        body: new FormData(form),
        credentials: 'same-origin',
      }).then(function (resp) {
        return resp.ok ? resp.json().catch(function () { return { ok: true }; })
                       : { ok: false };
      }).then(function (data) {
        if (data && data.ok) {
          if (statusEl) statusEl.textContent = doneLabel;
          var optin = document.querySelector('[data-reminder-optin]');
          if (optin) {
            optin.innerHTML = '<p class="text-sm text-game-text">' + doneLabel + '</p>';
          }
          if (window.gameAnalytics) {
            window.gameAnalytics.capture('game_reminder_subscribed', {});
          }
        } else {
          if (submitBtn) submitBtn.disabled = false;
          if (statusEl) statusEl.textContent = errorLabel;
        }
      }).catch(function () {
        if (submitBtn) submitBtn.disabled = false;
        if (statusEl) statusEl.textContent = errorLabel;
      });
    });
  })();

  var payloadEl = document.getElementById('game-share-payload');
  var btn = document.getElementById('share-results');
  var statusEl = document.getElementById('share-status');
  if (!btn || !payloadEl) return;

  var payload;
  try {
    payload = JSON.parse(payloadEl.textContent || '{}');
  } catch (e) {
    return;
  }

  var shareText = (payload.text || '').trim();
  var shareUrl = (payload.url || '').trim();
  var shareTitle = (payload.title || 'Tradeoffs on Society Speaks').trim();
  if (!shareText && shareUrl) {
    shareText = shareUrl;
  }
  if (!shareText) return;

  var defaultLabel = btn.dataset.defaultLabel || btn.textContent.trim() || 'Share results';
  var copiedLabel = btn.dataset.copiedLabel || 'Copied!';
  var failedLabel = btn.dataset.failedLabel || 'Could not copy';
  var runUuid = btn.dataset.runUuid;
  var resetTimer = null;

  function setStatus(message) {
    if (!statusEl) return;
    statusEl.textContent = message || '';
  }

  function flashButton(label) {
    if (resetTimer) clearTimeout(resetTimer);
    btn.textContent = label;
    resetTimer = setTimeout(function () {
      btn.textContent = defaultLabel;
      resetTimer = null;
    }, 2200);
  }

  function trackShare(method) {
    if (!window.gameAnalytics) return;
    window.gameAnalytics.capture('game_share_initiated', {
      run_uuid: runUuid,
      share_url: shareUrl,
      share_format: 'results',
      share_method: method,
    });
  }

  function copyToClipboard() {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(shareText).then(function () {
        trackShare('clipboard');
        flashButton(copiedLabel);
        setStatus(copiedLabel);
        return true;
      });
    }
    return Promise.resolve(false);
  }

  function legacyCopy() {
    var preview = document.getElementById('share-preview');
    if (!preview) return false;
    var range = document.createRange();
    range.selectNodeContents(preview);
    var selection = window.getSelection();
    if (!selection) return false;
    selection.removeAllRanges();
    selection.addRange(range);
    var ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (err) {
      ok = false;
    }
    selection.removeAllRanges();
    if (ok) {
      trackShare('selection');
      flashButton(copiedLabel);
      setStatus(copiedLabel);
    }
    return ok;
  }

  btn.addEventListener('click', function () {
    setStatus('');

    if (navigator.share) {
      navigator.share({
        title: shareTitle,
        text: shareText,
      }).then(function () {
        trackShare('native');
        setStatus(defaultLabel);
      }).catch(function (err) {
        if (err && err.name === 'AbortError') return;
        copyToClipboard().then(function (ok) {
          if (!ok && !legacyCopy()) {
            flashButton(failedLabel);
            setStatus(failedLabel);
          }
        });
      });
      return;
    }

    copyToClipboard().then(function (ok) {
      if (!ok && !legacyCopy()) {
        flashButton(failedLabel);
        setStatus(failedLabel);
      }
    }).catch(function () {
      if (!legacyCopy()) {
        flashButton(failedLabel);
        setStatus(failedLabel);
      }
    });
  });

  var bridge = document.getElementById('ss-bridge-link');
  if (bridge && window.gameAnalytics) {
    bridge.addEventListener('click', function () {
      window.gameAnalytics.capture('game_ss_bridge_clicked', {
        run_uuid: bridge.dataset.runUuid,
        bridge_type: bridge.dataset.bridgeType,
        bridge_target_id: bridge.dataset.bridgeTargetId,
      });
    });
  }

  // ----- Challenge a friend -----
  var challengeBtn = document.getElementById('challenge-share');
  if (challengeBtn) {
    var challengeUrl = (challengeBtn.dataset.challengeUrl || '').trim();
    var challengeStatus = document.getElementById('challenge-status');
    var cDefault = challengeBtn.dataset.defaultLabel || challengeBtn.textContent.trim();
    var cCopied = challengeBtn.dataset.copiedLabel || 'Link copied!';
    var cFailed = challengeBtn.dataset.failedLabel || 'Could not copy';
    var cTitle = challengeBtn.dataset.shareTitle || cDefault;
    var cTimer = null;

    function setChallengeStatus(msg) {
      if (challengeStatus) challengeStatus.textContent = msg || '';
    }

    function flashChallenge(label) {
      if (cTimer) clearTimeout(cTimer);
      challengeBtn.textContent = label;
      cTimer = setTimeout(function () { challengeBtn.textContent = cDefault; cTimer = null; }, 2200);
    }

    function trackChallenge(method) {
      if (!window.gameAnalytics) return;
      window.gameAnalytics.capture('game_challenge_link_created', {
        run_uuid: challengeBtn.dataset.runUuid,
        share_method: method,
      });
    }

    function challengeCopy() {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(challengeUrl).then(function () {
          trackChallenge('clipboard');
          flashChallenge(cCopied);
          setChallengeStatus(cCopied);
          return true;
        }).catch(function () { return false; });
      }
      return Promise.resolve(false);
    }

    challengeBtn.addEventListener('click', function () {
      if (!challengeUrl) return;
      setChallengeStatus('');
      if (navigator.share) {
        navigator.share({ title: cTitle, text: cTitle, url: challengeUrl })
          .then(function () { trackChallenge('native'); })
          .catch(function (err) {
            if (err && err.name === 'AbortError') return;
            challengeCopy().then(function (ok) { if (!ok) { flashChallenge(cFailed); setChallengeStatus(cFailed); } });
          });
        return;
      }
      challengeCopy().then(function (ok) { if (!ok) { flashChallenge(cFailed); setChallengeStatus(cFailed); } });
    });
  }
})();
