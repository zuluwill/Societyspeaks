/*
 * Product films (templates/components/film.html).
 *
 * The page ships a poster and a play button. Pressing it swaps in a <video> that plays with sound,
 * picking the rendition for the space it fills: the square cut where the frame is square (phones),
 * otherwise 720p, or 1080p on large, high-density screens unless the visitor has asked to save data.
 * When the film ends it offers one next step and a replay.
 *
 * PostHog events: film_played, film_progress (25/50/75), film_completed, film_cta_clicked.
 * Every event carries { film, format, page }.
 */
(function () {
  'use strict';
  if (window.__ssFilmPlayer) return;
  window.__ssFilmPlayer = true;

  function track(event, props) {
    try {
      if (window.posthog && typeof window.posthog.capture === 'function') window.posthog.capture(event, props);
    } catch (e) { /* analytics must never break playback */ }
  }

  function pickSource(fig, frame) {
    var box = frame.getBoundingClientRect();
    if (box.width / Math.max(1, box.height) < 1.2) return { src: fig.dataset.srcSquare, format: 'square-720' };
    var conn = navigator.connection || {};
    var lean = conn.saveData || /2g$/.test(conn.effectiveType || '');
    var px = box.width * (window.devicePixelRatio || 1);
    if (px > 1300 && !lean) return { src: fig.dataset.srcHd, format: 'wide-1080' };
    return { src: fig.dataset.srcSd, format: 'wide-720' };
  }

  function pauseOthers(current) {
    document.querySelectorAll('.ss-film video').forEach(function (v) {
      if (v !== current && !v.paused) v.pause();
    });
  }

  function showEnd(fig, frame, video, props) {
    if (!fig.dataset.ctaUrl || frame.querySelector('.ss-film__end')) return;
    var end = document.createElement('div');
    end.className = 'ss-film__end absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-slate-950/80 p-6 text-center backdrop-blur-sm';

    var cta = document.createElement('a');
    cta.href = fig.dataset.ctaUrl;
    cta.textContent = fig.dataset.ctaLabel;
    cta.className = 'inline-flex min-h-11 items-center justify-center rounded-lg bg-primary-600 px-6 py-3 text-base font-semibold text-white shadow-sm hover:bg-primary-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900';
    cta.setAttribute('data-ph-capture-attribute-cta', 'film-end-' + (fig.dataset.ctaId || fig.dataset.film));
    cta.addEventListener('click', function () { track('film_cta_clicked', props); });

    var replay = document.createElement('button');
    replay.type = 'button';
    replay.textContent = fig.dataset.replayLabel;
    replay.className = 'min-h-11 rounded-lg px-4 py-2 text-sm font-semibold text-white/90 underline-offset-4 hover:text-white hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-white';
    replay.addEventListener('click', function () {
      end.remove();
      video.currentTime = 0;
      video.play();
      video.focus();
    });

    end.appendChild(cta);
    end.appendChild(replay);
    frame.appendChild(end);
    cta.focus({ preventScroll: true });
  }

  function play(fig) {
    if (fig.dataset.state) return;
    fig.dataset.state = 'playing';
    var frame = fig.querySelector('.ss-film__frame');
    var button = frame.querySelector('.ss-film__play');
    var poster = frame.querySelector('img');
    var pick = pickSource(fig, frame);
    var props = { film: fig.dataset.film, format: pick.format, page: window.location.pathname };

    var video = document.createElement('video');
    video.className = 'absolute inset-0 h-full w-full bg-slate-900 object-contain';
    video.controls = true;
    video.playsInline = true;
    video.setAttribute('playsinline', '');
    video.preload = 'auto';
    video.setAttribute('aria-label', fig.dataset.title);
    if (poster && poster.currentSrc) video.poster = poster.currentSrc;
    if (fig.dataset.crossorigin) video.crossOrigin = 'anonymous';

    var source = document.createElement('source');
    source.src = pick.src;
    source.type = 'video/mp4';
    video.appendChild(source);

    if (fig.dataset.captions) {
      var track_ = document.createElement('track');
      track_.kind = 'captions';
      track_.src = fig.dataset.captions;
      track_.srclang = 'en';
      track_.label = fig.dataset.captionsLabel || 'English';
      track_.default = true;
      video.appendChild(track_);
    }

    frame.appendChild(video);
    button.remove();
    video.focus({ preventScroll: true });
    var started = video.play();
    // If the browser still refuses (rare after a click), the controls are showing and one more press plays it.
    if (started && typeof started.catch === 'function') started.catch(function () {});

    track('film_played', props);
    var sent = {};
    video.addEventListener('play', function () { pauseOthers(video); });
    video.addEventListener('timeupdate', function () {
      if (!video.duration) return;
      var pct = (video.currentTime / video.duration) * 100;
      [25, 50, 75].forEach(function (mark) {
        if (pct >= mark && !sent[mark]) {
          sent[mark] = true;
          track('film_progress', Object.assign({ percent: mark }, props));
        }
      });
    });
    video.addEventListener('ended', function () {
      track('film_completed', props);
      showEnd(fig, frame, video, props);
    });
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('.ss-film__play');
    if (!button) return;
    event.preventDefault();
    play(button.closest('.ss-film'));
  });
})();
