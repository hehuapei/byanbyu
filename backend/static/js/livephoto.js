// Lightweight Live Photo viewer. Pairs a still image with a .mov; on
// hover (desktop) or long-press (touch), fades to the video and plays.
// Reusable across feed/post/admin pages — call window.bbLivePhoto.scan()
// after rendering new DOM, or rely on the auto-init for static pages.

(function () {
  var LONG_PRESS_MS = 200;
  var initialized = new WeakSet();

  function setup(el) {
    if (initialized.has(el)) return;
    initialized.add(el);

    var stillUrl = el.getAttribute('data-still');
    var videoUrl = el.getAttribute('data-video');
    if (!videoUrl) return;

    var video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.setAttribute('playsinline', '');
    video.setAttribute('webkit-playsinline', '');
    video.preload = 'none';
    video.loop = false;
    video.src = videoUrl;
    el.appendChild(video);

    var pressTimer = null;
    var isActive = false;

    function start() {
      if (isActive) return;
      isActive = true;
      el.classList.add('playing');
      try {
        video.currentTime = 0;
      } catch (_) {}
      var p = video.play();
      if (p && typeof p.catch === 'function') p.catch(function () {});
    }

    function stop() {
      if (!isActive) return;
      isActive = false;
      el.classList.remove('playing');
      video.pause();
      try {
        video.currentTime = 0;
      } catch (_) {}
    }

    el.addEventListener('mouseenter', start);
    el.addEventListener('mouseleave', stop);

    el.addEventListener('pointerdown', function (e) {
      if (e.pointerType === 'mouse') return;
      pressTimer = setTimeout(start, LONG_PRESS_MS);
    });
    var cancelPress = function () {
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
      }
      stop();
    };
    el.addEventListener('pointerup', cancelPress);
    el.addEventListener('pointercancel', cancelPress);
    el.addEventListener('pointerleave', function (e) {
      if (e.pointerType === 'mouse') return;
      cancelPress();
    });
    video.addEventListener('ended', stop);
  }

  function scan(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll('.bb-lp');
    for (var i = 0; i < nodes.length; i++) setup(nodes[i]);
  }

  window.bbLivePhoto = { scan: scan };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { scan(); });
  } else {
    scan();
  }
})();
