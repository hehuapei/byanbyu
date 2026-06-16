// Compose-side attachment manager. Tracks selected files and renders a
// preview tile strip. Live Photos are auto-detected on ingest by matching
// filename stem (e.g. IMG_1234.HEIC + IMG_1234.MOV → one Live Photo).
// Used by /quick and /admin compose forms.

(function () {
  var IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'];
  var VIDEO_TYPES = ['video/quicktime', 'video/mp4'];
  var MAX_FILE_BYTES = 30 * 1024 * 1024;

  function classifyFile(file) {
    var t = (file.type || '').toLowerCase();
    var name = (file.name || '').toLowerCase();
    if (IMAGE_TYPES.indexOf(t) >= 0) return 'image';
    if (VIDEO_TYPES.indexOf(t) >= 0) return 'video';
    if (name.endsWith('.heic') || name.endsWith('.heif')) return 'image';
    if (name.endsWith('.mov')) return 'video';
    if (name.endsWith('.mp4')) return 'video';
    if (t.indexOf('image/') === 0) return 'image';
    if (t.indexOf('video/') === 0) return 'video';
    return null;
  }

  function basenameStem(file) {
    var name = (file && file.name) || '';
    var idx = name.lastIndexOf('.');
    return (idx > 0 ? name.slice(0, idx) : name).toLowerCase();
  }

  function uniqueId() {
    return 'a' + Math.random().toString(36).slice(2, 9) + Date.now().toString(36);
  }

  function makePreviewUrl(file) {
    try { return URL.createObjectURL(file); } catch (_) { return ''; }
  }

  function create(opts) {
    var fileInput = opts.fileInput;
    var tilesEl = opts.tilesEl;
    var onChange = opts.onChange || function () {};
    var showError = opts.showError || function () {};

    var items = []; // { id, kind, image: File, video?: File, imageUrl, videoUrl? }

    function rerender() {
      tilesEl.innerHTML = '';
      items.forEach(function (item) {
        var tile = document.createElement('div');
        var paired = item.kind === 'live_photo';
        var stray = item.kind === 'video';
        tile.className = 'bb-att-tile' + (paired ? ' is-paired' : '') + (stray ? ' is-stray' : '');
        tile.dataset.id = item.id;

        if (paired) {
          var img = document.createElement('img');
          img.src = item.imageUrl;
          tile.appendChild(img);
          var badge = document.createElement('span');
          badge.className = 'tile-badge';
          badge.textContent = 'LIVE';
          tile.appendChild(badge);
        } else if (item.kind === 'image') {
          var img2 = document.createElement('img');
          img2.src = item.imageUrl;
          tile.appendChild(img2);
        } else if (stray) {
          var v = document.createElement('video');
          v.src = item.imageUrl;
          v.muted = true;
          v.playsInline = true;
          v.preload = 'metadata';
          tile.appendChild(v);
          var badge2 = document.createElement('span');
          badge2.className = 'tile-badge';
          badge2.textContent = '需配同名图';
          tile.appendChild(badge2);
        }

        var rm = document.createElement('button');
        rm.type = 'button';
        rm.className = 'tile-remove';
        rm.textContent = '×';
        rm.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          remove(item.id);
        });
        tile.appendChild(rm);
        tilesEl.appendChild(tile);
      });
      onChange();
    }

    function remove(id) {
      var idx = items.findIndex(function (it) { return it.id === id; });
      if (idx < 0) return;
      var it = items[idx];
      if (it.imageUrl) URL.revokeObjectURL(it.imageUrl);
      if (it.videoUrl) URL.revokeObjectURL(it.videoUrl);
      items.splice(idx, 1);
      rerender();
    }

    function autoPair() {
      // Pair each unpaired image with a video of the same basename stem
      var images = items.filter(function (it) { return it.kind === 'image'; });
      var videos = items.filter(function (it) { return it.kind === 'video'; });
      images.forEach(function (imgItem) {
        var stem = basenameStem(imgItem.image);
        if (!stem) return;
        for (var j = 0; j < videos.length; j++) {
          var vidItem = videos[j];
          if (basenameStem(vidItem.image) === stem) {
            imgItem.kind = 'live_photo';
            imgItem.video = vidItem.image;
            imgItem.videoUrl = vidItem.imageUrl;
            var vidIdx = items.indexOf(vidItem);
            if (vidIdx >= 0) items.splice(vidIdx, 1);
            videos.splice(j, 1);
            break;
          }
        }
      });
    }

    function unpair(id) {
      var item = items.find(function (it) { return it.id === id; });
      if (!item || item.kind !== 'live_photo') return;
      item.kind = 'image';
      var v = item.video;
      var vu = item.videoUrl;
      delete item.video;
      delete item.videoUrl;
      if (v) {
        items.push({
          id: uniqueId(), kind: 'video', image: v, imageUrl: vu || makePreviewUrl(v),
        });
      }
      rerender();
    }

    function ingestFiles(fileList) {
      var added = false;
      for (var i = 0; i < fileList.length; i++) {
        var file = fileList[i];
        var kind = classifyFile(file);
        if (!kind) {
          showError('不支持的文件类型: ' + (file.name || ''));
          continue;
        }
        if (file.size > MAX_FILE_BYTES) {
          showError((file.name || '文件') + ' 超过 30MB');
          continue;
        }
        items.push({
          id: uniqueId(),
          kind: kind, // 'image' or 'video' here; autoPair() may turn into live_photo
          image: file,
          imageUrl: makePreviewUrl(file),
        });
        added = true;
      }
      if (added) {
        autoPair();
        rerender();
      }
    }

    fileInput.addEventListener('change', function () {
      if (!fileInput.files || !fileInput.files.length) return;
      ingestFiles(fileInput.files);
      fileInput.value = '';
    });
    tilesEl.addEventListener('dblclick', function (e) {
      var tile = e.target.closest && e.target.closest('.bb-att-tile.is-paired');
      if (!tile) return;
      unpair(tile.dataset.id);
    });

    function buildFormData(extra) {
      var stray = items.filter(function (it) { return it.kind === 'video'; });
      if (stray.length) {
        showError('有视频没找到同名静态图，无法作为 Live Photo 发送，请补一张同名图或移除');
        return null;
      }
      var fd = new FormData();
      Object.keys(extra || {}).forEach(function (k) { fd.append(k, extra[k]); });
      var meta = items.map(function (it) {
        return { kind: it.kind === 'live_photo' ? 'live_photo' : 'image' };
      });
      fd.append('attachments_meta', JSON.stringify(meta));
      items.forEach(function (it, idx) {
        fd.append('file_' + idx + '_image', it.image, it.image.name || ('image-' + idx));
        if (it.video) fd.append('file_' + idx + '_video', it.video, it.video.name || ('video-' + idx));
      });
      return fd;
    }

    function clear() {
      items.forEach(function (it) {
        if (it.imageUrl) URL.revokeObjectURL(it.imageUrl);
        if (it.videoUrl) URL.revokeObjectURL(it.videoUrl);
      });
      items = [];
      rerender();
    }

    return {
      buildFormData: buildFormData,
      clear: clear,
      count: function () { return items.length; },
      hasItems: function () { return items.length > 0; },
    };
  }

  window.bbCompose = { create: create };
})();
