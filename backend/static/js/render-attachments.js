// Render attachment grid for feed/admin/detail pages.
// Caller passes a parent element + array from API response.
//
//   bbAttachments.render(containerEl, attachmentsArray, { useFullSize: true });
//
// Returns the created <div class="bb-attachments"> or null when empty.

(function () {
  function imageEl(url) {
    var img = document.createElement('img');
    img.loading = 'lazy';
    img.decoding = 'async';
    img.src = url;
    return img;
  }

  function renderImage(att, useFull) {
    var wrap = document.createElement('div');
    wrap.className = 'bb-att';
    wrap.appendChild(imageEl(useFull ? att.urls.image : att.urls.thumb));
    return wrap;
  }

  function renderLivePhoto(att, useFull) {
    var wrap = document.createElement('div');
    wrap.className = 'bb-att bb-lp';
    wrap.setAttribute('data-still', useFull ? att.urls.image : att.urls.thumb);
    wrap.setAttribute('data-video', att.urls.video || '');
    wrap.appendChild(imageEl(useFull ? att.urls.image : att.urls.thumb));
    var badge = document.createElement('span');
    badge.className = 'bb-lp-badge';
    badge.textContent = 'LIVE';
    wrap.appendChild(badge);
    return wrap;
  }

  function render(parent, attachments, opts) {
    if (!attachments || !attachments.length) return null;
    var useFull = !!(opts && opts.useFullSize);
    var grid = document.createElement('div');
    grid.className = 'bb-attachments';
    grid.setAttribute('data-count', String(attachments.length));
    attachments.forEach(function (att, idx) {
      var node = att.kind === 'live_photo' ? renderLivePhoto(att, useFull) : renderImage(att, useFull);
      node.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (window.bbLightbox && typeof window.bbLightbox.open === 'function') {
          window.bbLightbox.open(attachments, idx);
        }
      });
      grid.appendChild(node);
    });
    parent.appendChild(grid);
    if (window.bbLivePhoto && typeof window.bbLivePhoto.scan === 'function') {
      window.bbLivePhoto.scan(grid);
    }
    return grid;
  }

  window.bbAttachments = { render: render };
})();
