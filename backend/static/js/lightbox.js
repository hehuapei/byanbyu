// Lightbox for viewing attachment full-size images and Live Photos.
// Open via: window.bbLightbox.open(attachments, startIndex)

(function () {
  var overlay = null;
  var state = { items: [], index: 0 };

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
      swipeStartX = e.clientX;
      swipeStartY = e.clientY;
      swipeStartTime = Date.now();
    });
    overlay.addEventListener('pointerup', function (e) {
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
    });
    overlay.addEventListener('pointercancel', function () { swipeStartX = null; });
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
  }

  function open(items, index) {
    if (!items || !items.length) return;
    ensureOverlay();
    state.items = items;
    state.index = Math.max(0, Math.min(index || 0, items.length - 1));
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    render();
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    overlay.querySelector('.bb-lightbox-content').innerHTML = '';
  }

  function step(delta) {
    if (!state.items.length) return;
    var n = state.items.length;
    state.index = (state.index + delta + n) % n;
    render();
  }

  window.bbLightbox = { open: open, close: close };

  // Block native long-press / right-click menu on all attachment media.
  document.addEventListener('contextmenu', function (e) {
    if (e.target && e.target.closest && e.target.closest('.bb-att, .bb-att-tile, .bb-lightbox')) {
      e.preventDefault();
    }
  });
})();
