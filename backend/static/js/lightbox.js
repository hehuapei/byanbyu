// Lightbox for viewing attachment full-size images and Live Photos.
// Open via: window.bbLightbox.open(attachments, startIndex)

(function () {
  var overlay = null;
  var state = { items: [], index: 0 };
  var animating = false;
  var zoom = { scale: 1, x: 0, y: 0 };
  var activePointers = new Map();
  var pinchStart = null;
  var MIN_SCALE = 1;
  var MAX_SCALE = 5;

  function ensureOverlay() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'bb-lightbox';
    overlay.innerHTML =
      '<div class="bb-lightbox-counter"></div>' +
      '<button type="button" class="bb-lightbox-btn bb-lightbox-close" aria-label="关闭">×</button>' +
      '<button type="button" class="bb-lightbox-btn bb-lightbox-prev" aria-label="上一张">‹</button>' +
      '<div class="bb-lightbox-stage"><div class="bb-lightbox-content"></div></div>' +
      '<button type="button" class="bb-lightbox-btn bb-lightbox-next" aria-label="下一张">›</button>';
    document.body.appendChild(overlay);

    overlay.querySelector('.bb-lightbox-close').addEventListener('click', function (e) {
      e.stopPropagation();
      close();
    });
    overlay.querySelector('.bb-lightbox-prev').addEventListener('click', function (e) {
      e.stopPropagation();
      step(-1);
    });
    overlay.querySelector('.bb-lightbox-next').addEventListener('click', function (e) {
      e.stopPropagation();
      step(1);
    });
    document.addEventListener('keydown', function (e) {
      if (!overlay.classList.contains('open')) return;
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') step(-1);
      else if (e.key === 'ArrowRight') step(1);
    });

    // Swipe gestures (touch + mouse drag)
    var swipeStartX = null;
    var swipeStartY = null;
    var swipeStartTime = 0;
    var panStartX = null;
    var panStartY = null;
    var panBaseX = 0;
    var panBaseY = 0;
    var suppressNextClick = false;
    overlay.addEventListener('click', function (e) {
      if (suppressNextClick) {
        suppressNextClick = false;
        return;
      }
      if (e.target === overlay || e.target.classList.contains('bb-lightbox-stage')) close();
    });
    overlay.addEventListener('pointerdown', function (e) {
      if (e.target.closest('.bb-lightbox-btn')) return;
      activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      overlay.setPointerCapture && overlay.setPointerCapture(e.pointerId);

      if (activePointers.size === 2) {
        pinchStart = getPinchState();
        pinchStart.baseScale = zoom.scale;
        pinchStart.baseX = zoom.x;
        pinchStart.baseY = zoom.y;
        panStartX = null;
        swipeStartX = null;
        suppressNextClick = true;
        return;
      }

      if (zoom.scale > 1.01) {
        panStartX = e.clientX;
        panStartY = e.clientY;
        panBaseX = zoom.x;
        panBaseY = zoom.y;
        swipeStartX = null;
        return;
      }

      swipeStartX = e.clientX;
      swipeStartY = e.clientY;
      swipeStartTime = Date.now();
    });
    overlay.addEventListener('pointermove', function (e) {
      if (!activePointers.has(e.pointerId)) return;
      activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (pinchStart && activePointers.size >= 2) {
        var now = getPinchState();
        if (!now || !pinchStart.distance) return;
        var nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, pinchStart.baseScale * (now.distance / pinchStart.distance)));
        var ratio = nextScale / pinchStart.baseScale;
        zoom.x = now.cx - window.innerWidth / 2 - ((pinchStart.cx - window.innerWidth / 2) - pinchStart.baseX) * ratio;
        zoom.y = now.cy - window.innerHeight / 2 - ((pinchStart.cy - window.innerHeight / 2) - pinchStart.baseY) * ratio;
        zoom.scale = nextScale;
        if (zoom.scale <= 1.01) {
          zoom.scale = 1;
          zoom.x = 0;
          zoom.y = 0;
        }
        var content = overlay.querySelector('.bb-lightbox-content');
        content.style.transition = 'transform 0.04s linear, opacity 0.18s linear';
        applyContentTransform();
        return;
      }

      if (panStartX == null) return;
      zoom.x = panBaseX + (e.clientX - panStartX);
      zoom.y = panBaseY + (e.clientY - panStartY);
      applyContentTransform();
    });
    function endPointer(e) {
      activePointers.delete(e.pointerId);
      if (pinchStart) {
        pinchStart = null;
        panStartX = null;
        swipeStartX = null;
        suppressNextClick = true;
        return;
      }
      if (panStartX != null) {
        var pdx = e.clientX - panStartX;
        var pdy = e.clientY - panStartY;
        panStartX = null;
        if (Math.abs(pdx) > 4 || Math.abs(pdy) > 4) suppressNextClick = true;
        return;
      }
      if (swipeStartX == null) return;
      var dx = e.clientX - swipeStartX;
      var dy = e.clientY - swipeStartY;
      var dt = Date.now() - swipeStartTime;
      swipeStartX = null;
      if (Math.abs(dx) > 10 || Math.abs(dy) > 10) suppressNextClick = true;
      if (state.items.length <= 1) return;
      if (dt < 600 && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        step(dx < 0 ? 1 : -1);
      }
    }
    overlay.addEventListener('pointerup', endPointer);
    overlay.addEventListener('pointercancel', endPointer);
    overlay.addEventListener('wheel', function (e) {
      if (!overlay.classList.contains('open') || animating) return;
      if (e.target.closest('.bb-lightbox-btn')) return;
      e.preventDefault();
      applyWheelZoom(e);
    }, { passive: false });
  }

  function resetZoom() {
    zoom.scale = 1;
    zoom.x = 0;
    zoom.y = 0;
    var content = overlay && overlay.querySelector('.bb-lightbox-content');
    if (content) content.style.transition = '';
    applyContentTransform();
  }

  function applyContentTransform() {
    var content = overlay && overlay.querySelector('.bb-lightbox-content');
    if (!content) return;
    content.style.transform = 'translate(' + zoom.x + 'px, ' + zoom.y + 'px) scale(' + zoom.scale + ')';
    content.classList.toggle('is-zoomed', zoom.scale > 1.01);
  }

  function applyWheelZoom(e) {
    var content = overlay.querySelector('.bb-lightbox-content');
    var oldScale = zoom.scale;
    var factor = Math.exp(-e.deltaY * 0.002);
    var nextScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, oldScale * factor));
    if (Math.abs(nextScale - oldScale) < 0.001) return;

    var centerX = window.innerWidth / 2;
    var centerY = window.innerHeight / 2;
    var pointerX = e.clientX - centerX;
    var pointerY = e.clientY - centerY;
    var ratio = nextScale / oldScale;

    zoom.x = pointerX - (pointerX - zoom.x) * ratio;
    zoom.y = pointerY - (pointerY - zoom.y) * ratio;
    zoom.scale = nextScale;
    if (zoom.scale <= 1.01) {
      zoom.scale = 1;
      zoom.x = 0;
      zoom.y = 0;
    }
    content.style.transition = 'transform 0.08s ease-out, opacity 0.18s linear';
    applyContentTransform();
  }

  function getPinchState() {
    var points = Array.from(activePointers.values());
    if (points.length < 2) return null;
    var a = points[0];
    var b = points[1];
    var dx = b.x - a.x;
    var dy = b.y - a.y;
    return {
      cx: (a.x + b.x) / 2,
      cy: (a.y + b.y) / 2,
      distance: Math.sqrt(dx * dx + dy * dy),
    };
  }

  function render() {
    var content = overlay.querySelector('.bb-lightbox-content');
    content.innerHTML = '';
    var item = state.items[state.index];
    if (!item) return;
    if (item.kind === 'live_photo') {
      var lp = document.createElement('div');
      lp.className = 'bb-lp';
      lp.setAttribute('data-still', item.urls.image);
      lp.setAttribute('data-video', item.urls.video || '');
      var img = document.createElement('img');
      img.src = item.urls.image;
      lp.appendChild(img);
      var badge = document.createElement('span');
      badge.className = 'bb-lp-badge';
      badge.textContent = 'LIVE';
      lp.appendChild(badge);
      content.appendChild(lp);
      if (window.bbLivePhoto && typeof window.bbLivePhoto.scan === 'function') {
        window.bbLivePhoto.scan(content);
      }
    } else if (item.kind === 'video') {
      var v = document.createElement('video');
      v.src = item.urls.video || item.urls.image;
      v.controls = true;
      v.playsInline = true;
      v.setAttribute('playsinline', '');
      v.autoplay = true;
      content.appendChild(v);
    } else {
      var img2 = document.createElement('img');
      img2.src = item.urls.image;
      content.appendChild(img2);
    }
    content.addEventListener('click', function (e) { e.stopPropagation(); }, { once: true });

    var multi = state.items.length > 1;
    overlay.querySelector('.bb-lightbox-counter').textContent = multi ? (state.index + 1) + ' / ' + state.items.length : '';
    overlay.querySelector('.bb-lightbox-prev').style.display = multi ? '' : 'none';
    overlay.querySelector('.bb-lightbox-next').style.display = multi ? '' : 'none';
    if (!animating) applyContentTransform();
  }

  function open(items, index) {
    if (!items || !items.length) return;
    ensureOverlay();
    state.items = items;
    state.index = Math.max(0, Math.min(index || 0, items.length - 1));
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    var content = overlay.querySelector('.bb-lightbox-content');
    content.style.transition = '';
    content.style.opacity = '';
    animating = false;
    activePointers.clear();
    pinchStart = null;
    resetZoom();
    render();
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    var content = overlay.querySelector('.bb-lightbox-content');
    content.innerHTML = '';
    content.style.transition = '';
    content.style.opacity = '';
    animating = false;
    activePointers.clear();
    pinchStart = null;
    resetZoom();
  }

  function step(delta) {
    if (!state.items.length || state.items.length <= 1) return;
    if (animating) return;
    resetZoom();
    animating = true;
    var content = overlay.querySelector('.bb-lightbox-content');
    var dir = delta > 0 ? 1 : -1;
    var dur = 220;
    // Phase 1: slide current out in the direction of motion
    content.style.transform = 'translateX(' + (-dir * 30) + 'vw)';
    content.style.opacity = '0';
    setTimeout(function () {
      // Phase 2: jump to opposite side, no transition, swap content
      var n = state.items.length;
      state.index = (state.index + delta + n) % n;
      content.style.transition = 'none';
      content.style.transform = 'translateX(' + (dir * 30) + 'vw)';
      content.style.opacity = '0';
      render();
      // Force layout so the next style change animates
      void content.offsetWidth;
      // Phase 3: slide in to home
      content.style.transition = '';
      content.style.transform = 'translateX(0)';
      content.style.opacity = '1';
      setTimeout(function () { animating = false; }, dur);
    }, dur);
  }

  window.bbLightbox = { open: open, close: close };

  // Block native long-press / right-click menu on all attachment media.
  document.addEventListener('contextmenu', function (e) {
    if (e.target && e.target.closest && e.target.closest('.bb-att, .bb-att-tile, .bb-lightbox')) {
      e.preventDefault();
    }
  });
})();
