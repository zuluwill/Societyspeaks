(function () {
  'use strict';

  var btn = document.getElementById('share-native');
  if (!btn) return;

  var defaultLabel = btn.dataset.defaultLabel || btn.textContent.trim() || 'Share';
  var copiedLabel = btn.dataset.copiedLabel || 'Link copied';

  function flashLabel(text) {
    var original = btn.textContent;
    btn.textContent = text;
    setTimeout(function () {
      btn.textContent = original === text ? defaultLabel : original;
    }, 1800);
  }

  btn.addEventListener('click', function () {
    var url = btn.dataset.shareUrl || window.location.href;
    var title = btn.dataset.shareTitle || 'Tradeoffs on Society Speaks';
    var runUuid = btn.dataset.runUuid;

    if (window.gameAnalytics) {
      window.gameAnalytics.capture('game_share_initiated', {
        run_uuid: runUuid,
        share_url: url,
      });
    }

    if (navigator.share) {
      navigator.share({ title: title, url: url }).catch(function () {});
      return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () {
        flashLabel(copiedLabel);
      }).catch(function () {
        flashLabel('Copy failed');
      });
      return;
    }

    window.prompt('Copy this link:', url);
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
