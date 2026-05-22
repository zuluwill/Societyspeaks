(function () {
  'use strict';

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
})();
