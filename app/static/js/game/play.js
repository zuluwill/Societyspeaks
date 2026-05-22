(function () {
  'use strict';

  var app = document.getElementById('game-app');
  if (!app) return;

  var runUuid = app.dataset.runUuid;
  var csrf = app.dataset.csrf;

  var overlay = document.getElementById('consequence-overlay');
  var headlineEl = document.getElementById('consequence-headline');
  var deltasEl = document.getElementById('consequence-deltas');
  var continueBtn = document.getElementById('consequence-continue');
  var choicesEl = document.getElementById('choices');
  var ticker = document.getElementById('headline-ticker');
  var turnPanel = document.getElementById('turn-panel');
  var promptEl = document.getElementById('turn-prompt');
  var beatLabelEl = document.getElementById('beat-label');
  var toast = document.getElementById('toast');
  var statBars = document.getElementById('stat-bars');

  var statLabels = (function () {
    try {
      return JSON.parse((statBars && statBars.dataset.statLabels) || '{}');
    } catch (e) {
      return {};
    }
  })();

  var beatLabels = (function () {
    try {
      return JSON.parse(app.dataset.beatLabels || '{}');
    } catch (e) {
      return {};
    }
  })();

  var progressTemplate = app.dataset.progressTemplate || 'Turn {n} of {total}';

  function formatProgress(n, total) {
    return progressTemplate
      .replace('{n}', String(n))
      .replace('{total}', String(total));
  }

  var lastFocusedBeforeDialog = null;
  var toastTimer = null;
  var closeDialogTimer = null;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.remove('hidden');
    toast.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toast.classList.remove('is-visible');
      setTimeout(function () { toast.classList.add('hidden'); }, 220);
    }, 3200);
  }

  function setButtonsDisabled(disabled) {
    var buttons = choicesEl.querySelectorAll('.game-choice');
    buttons.forEach(function (btn) {
      btn.disabled = disabled;
      btn.setAttribute('aria-disabled', disabled ? 'true' : 'false');
    });
  }

  function animateStatBars(visibleStats) {
    if (!visibleStats) return;
    Object.keys(visibleStats).forEach(function (key) {
      var row = document.querySelector('.game-stat-row[data-stat="' + key + '"]');
      if (!row) return;
      var val = visibleStats[key];
      var valueEl = row.querySelector('.stat-value');
      var fill = row.querySelector('.game-stat-fill');
      if (valueEl) valueEl.textContent = val;
      if (fill) {
        fill.style.width = val + '%';
        fill.classList.add('is-pulsing');
        setTimeout(function () { fill.classList.remove('is-pulsing'); }, 600);
      }
      var track = row.querySelector('.game-stat-track');
      if (track) track.setAttribute('aria-valuenow', String(val));
    });
  }

  function appendTickerLine(text) {
    if (!ticker || !text) return;
    var line = document.createElement('p');
    line.className = 'ticker-line';
    line.textContent = text;
    ticker.appendChild(line);
    var lines = ticker.querySelectorAll('.ticker-line');
    while (lines.length > 3) {
      lines[0].remove();
      lines = ticker.querySelectorAll('.ticker-line');
    }
  }

  // ----- Accessible consequence dialog -----

  function openDialog() {
    if (closeDialogTimer) { clearTimeout(closeDialogTimer); closeDialogTimer = null; }
    lastFocusedBeforeDialog = document.activeElement;
    overlay.classList.remove('hidden');
    requestAnimationFrame(function () {
      overlay.classList.add('is-visible');
      continueBtn.focus();
    });
    document.addEventListener('keydown', dialogKeyHandler);
  }

  function closeDialog() {
    overlay.classList.remove('is-visible');
    document.removeEventListener('keydown', dialogKeyHandler);
    closeDialogTimer = setTimeout(function () {
      closeDialogTimer = null;
      overlay.classList.add('hidden');
      if (lastFocusedBeforeDialog && lastFocusedBeforeDialog.focus) {
        lastFocusedBeforeDialog.focus();
      }
    }, 200);
  }

  function dialogKeyHandler(e) {
    if (e.key === 'Escape' || e.key === 'Enter') {
      e.preventDefault();
      var handler = continueBtn.onclick;
      if (handler) handler();
    }
    if (e.key === 'Tab') {
      // Single focusable element — trap focus on Continue.
      e.preventDefault();
      continueBtn.focus();
    }
  }

  function showConsequence(consequence, onDone) {
    if (!consequence || (!consequence.headline && (!consequence.stat_deltas || !Object.keys(consequence.stat_deltas).length))) {
      onDone();
      return;
    }
    headlineEl.textContent = consequence.headline || 'Your society shifts.';
    deltasEl.innerHTML = '';
    var deltas = consequence.stat_deltas || {};
    Object.keys(deltas).forEach(function (key) {
      var label = statLabels[key];
      if (!label) return;
      var delta = deltas[key];
      if (!delta) return;
      var p = document.createElement('p');
      var sign = delta > 0 ? '+' : '';
      var arrow = delta > 0 ? '↑' : '↓';
      var arrowSpan = document.createElement('span');
      arrowSpan.className = delta > 0 ? 'text-game-trust' : 'text-game-warn';
      arrowSpan.textContent = arrow + ' ';
      p.appendChild(arrowSpan);
      p.appendChild(document.createTextNode(label + ' ' + sign + delta));
      deltasEl.appendChild(p);
    });
    openDialog();
    continueBtn.onclick = function () {
      closeDialog();
      onDone();
    };
  }

  // ----- In-place turn render -----

  function renderNextTurn(next) {
    if (!next) return;
    turnPanel.classList.add('is-swapping');

    setTimeout(function () {
      var beatLabel = beatLabels[next.beat];
      beatLabelEl.innerHTML = '';
      var progressSpan = document.createElement('span');
      progressSpan.className = beatLabel ? 'text-game-muted' : '';
      progressSpan.textContent = (beatLabel ? '· ' : '') + formatProgress(next.turn_index + 1, next.total_turns);
      if (beatLabel) {
        beatLabelEl.appendChild(document.createTextNode(beatLabel + ' '));
      }
      beatLabelEl.appendChild(progressSpan);

      promptEl.textContent = next.prompt;

      choicesEl.innerHTML = '';
      next.choices.forEach(function (choice) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'game-choice w-full text-left';
        btn.dataset.choiceId = choice.id;

        var labelEl = document.createElement('span');
        labelEl.className = 'game-choice-label';
        labelEl.textContent = choice.label;
        btn.appendChild(labelEl);

        if (choice.flavour) {
          var flavourEl = document.createElement('span');
          flavourEl.className = 'game-choice-flavour';
          flavourEl.textContent = choice.flavour;
          btn.appendChild(flavourEl);
        }

        if (choice.preview && Object.keys(choice.preview).length) {
          var arrows = document.createElement('span');
          arrows.className = 'game-choice-arrows mt-2 flex flex-wrap gap-x-3 gap-y-1';
          arrows.setAttribute('aria-label', 'Likely effects');
          Object.keys(choice.preview).forEach(function (stat) {
            var dir = choice.preview[stat];
            var item = document.createElement('span');
            item.className = 'text-xs text-game-muted';
            var glyph = document.createElement('span');
            glyph.className = dir === 'up' ? 'text-game-trust' : dir === 'down' ? 'text-game-warn' : '';
            glyph.textContent = dir === 'up' ? '↑ ' : dir === 'down' ? '↓ ' : '→ ';
            item.appendChild(glyph);
            item.appendChild(document.createTextNode(statLabels[stat] || stat));
            arrows.appendChild(item);
          });
          btn.appendChild(arrows);
        }

        choicesEl.appendChild(btn);
      });

      turnPanel.classList.remove('is-swapping');
    }, 220);
  }

  // ----- Main flow -----

  function choose(choiceId) {
    setButtonsDisabled(true);

    if (window.gameAnalytics) {
      window.gameAnalytics.capture('game_turn_started', { run_uuid: runUuid, choice_id: choiceId });
    }

    fetch('/play/api/run/' + runUuid + '/choose', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf,
      },
      body: JSON.stringify({ choice_id: choiceId }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          if (result.status === 409 && result.data.outcome_url) {
            window.location.href = result.data.outcome_url;
            return;
          }
          showToast(result.data.error || 'Something went wrong. Please try again.');
          setButtonsDisabled(false);
          return;
        }
        var data = result.data;
        animateStatBars(data.visible_stats);

        if (data.consequence && data.consequence.headline) {
          appendTickerLine(data.consequence.headline);
        }

        showConsequence(data.consequence, function () {
          var afterImmediate = function () {
            if (data.game_complete && data.outcome_url) {
              if (window.gameAnalytics) {
                window.gameAnalytics.capture('game_run_completed', {
                  run_uuid: runUuid,
                  turn_index: data.turn_index,
                });
              }
              document.body.classList.add('is-leaving');
              window.location.href = data.outcome_url;
              return;
            }
            renderNextTurn(data.next_turn);
            setButtonsDisabled(false);
          };

          if (data.next_consequence) {
            var headlines = (data.next_consequence.headlines || []).filter(Boolean);
            headlines.forEach(appendTickerLine);
            showConsequence(
              {
                headline: headlines.length ? headlines.join(' ') : 'A delayed cost arrives.',
                stat_deltas: data.next_consequence.stat_deltas,
              },
              afterImmediate
            );
          } else {
            afterImmediate();
          }
        });
      })
      .catch(function () {
        showToast('Network error. Please try again.');
        setButtonsDisabled(false);
      });
  }

  choicesEl.addEventListener('click', function (e) {
    var btn = e.target.closest('.game-choice');
    if (!btn || btn.disabled) return;
    var choiceId = btn.dataset.choiceId;
    if (choiceId) choose(choiceId);
  });
})();
