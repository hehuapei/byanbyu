import io
import logging
import os
import tempfile

import filetype
from PIL import Image, ImageOps
import pillow_heif


pillow_heif.register_heif_opener()
logger = logging.getLogger(__name__)


MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file

IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
VIDEO_MIMES = {'video/quicktime', 'video/mp4'}
HEIF_MIMES = {'image/heic', 'image/heif'}

THUMB_MAX_SIDE = 800
THUMB_QUALITY = 80
JPEG_QUALITY = 88


class MediaError(ValueError):
    """Raised when media processing fails for a user-supplied file."""


def detect_mime(file_storage) -> str:
    head = file_storage.stream.read(261)
    file_storage.stream.seek(0)
    kind = filetype.guess(head)
    if kind is None:
        raise MediaError('无法识别的文件类型')
    return kind.mime


def _save_to_temp(file_storage, suffix: str) -> str:
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as f:
            chunk = file_storage.stream.read(1 << 20)
            while chunk:
                f.write(chunk)
                chunk = file_storage.stream.read(1 << 20)
        size = os.path.getsize(tmp)
        if size > MAX_FILE_BYTES:
            raise MediaError('单文件不能超过 50MB')
        return tmp
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _temp_path(suffix: str) -> str:
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return tmp


def process_image(file_storage, mime: str):
    """Returns (image_tmp_path, image_ext, image_mime, thumb_tmp_path,
               thumb_ext, thumb_mime, width, height, bytes)."""
    raw_path = _save_to_temp(file_storage, '.bin')
    try:
        with Image.open(raw_path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ('RGBA', 'LA', 'P'):
                im = im.convert('RGBA') if mime in {'image/png', 'image/webp'} else im.convert('RGB')
            else:
                im = im.convert('RGB')

            if mime in HEIF_MIMES or mime == 'image/jpeg':
                ext, out_mime, save_kwargs = '.jpg', 'image/jpeg', {
                    'format': 'JPEG', 'quality': JPEG_QUALITY, 'optimize': True, 'exif': b''
                }
                if im.mode != 'RGB':
                    im = im.convert('RGB')
            elif mime == 'image/png':
                ext, out_mime, save_kwargs = '.png', 'image/png', {'format': 'PNG', 'optimize': True}
            elif mime == 'image/webp':
                ext, out_mime, save_kwargs = '.webp', 'image/webp', {
                    'format': 'WEBP', 'quality': JPEG_QUALITY, 'method': 4
                }
            else:
                raise MediaError(f'不支持的图片类型 {mime}')

            image_tmp = _temp_path(ext)
            im.save(image_tmp, **save_kwargs)
            width, height = im.size

            thumb_im = im.copy()
            thumb_im.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE))
            if thumb_im.mode == 'RGBA':
                bg = Image.new('RGB', thumb_im.size, (255, 255, 255))
                bg.paste(thumb_im, mask=thumb_im.split()[3])
                thumb_im = bg
            thumb_tmp = _temp_path('.webp')
            thumb_im.save(thumb_tmp, format='WEBP', quality=THUMB_QUALITY, method=4)
    finally:
        try:
            os.remove(raw_path)
        except OSError:
            pass

    image_bytes = os.path.getsize(image_tmp)
    return {
        'image_tmp': image_tmp,
        'image_ext': ext,
        'image_mime': out_mime,
        'thumb_tmp': thumb_tmp,
        'thumb_ext': '.webp',
        'thumb_mime': 'image/webp',
        'width': width,
        'height': height,
        'bytes': image_bytes,
    }


def process_video(file_storage, mime: str):
    """Returns (tmp_path, ext, mime, bytes). No transcoding."""
    if mime == 'video/quicktime':
        ext = '.mov'
    elif mime == 'video/mp4':
        ext = '.mp4'
    else:
        raise MediaError(f'不支持的视频类型 {mime}')
    tmp = _save_to_temp(file_storage, ext)
    return {
        'tmp': tmp,
        'ext': ext,
        'mime': mime,
        'bytes': os.path.getsize(tmp),
    }


def try_extract_motion_photo(file_storage) -> bytes | None:
    """If the upload is a JPEG/HEIC with an embedded MP4 trailer
    (Google MotionPhoto / Samsung Motion Photo / vivo 动态照片), return
    the raw MP4 bytes. Otherwise return None.

    Detection: scan the file for the 'ftyp' MP4 box marker. JPEG has no
    native ftyp; any occurrence is the trailing video. HEIC has its own
    ftyp at the start; the trailing video shows up as a later ftyp.

    Stream position is restored before return.
    """
    stream = file_storage.stream
    pos = stream.tell()
    stream.seek(0)
    data = stream.read()
    stream.seek(pos)

    if not data:
        return None

    head = data[:12]
    is_jpeg = head[:2] == b'\xff\xd8'
    is_heif = len(head) >= 12 and head[4:8] == b'ftyp' and head[8:12] in (
        b'heic', b'heix', b'hevc', b'mif1', b'msf1', b'heim', b'heis'
    )

    # Diagnostic dump for failures we want to investigate.
    def _diag(reason):
        logger.debug('motion_photo: skip (%s) size=%d head=%s', reason, len(data), head[:12].hex())

    if not (is_jpeg or is_heif):
        _diag('not jpeg/heic')
        return None

    # Last 'ftyp' is the trailer (HEIC also has one at offset 4).
    last_ftyp = data.rfind(b'ftyp')
    if last_ftyp < 4:
        _diag('no ftyp')
        return None
    if is_heif and last_ftyp == 4:
        _diag('heif single ftyp')
        return None

    mp4_start = last_ftyp - 4
    box_size = int.from_bytes(data[mp4_start:mp4_start + 4], 'big')
    if not (8 < box_size < 128):
        _diag(f'bad box size {box_size}')
        return None

    mp4_bytes = data[mp4_start:]
    if len(mp4_bytes) < 1024:
        _diag(f'mp4 too small {len(mp4_bytes)}')
        return None

    if len(mp4_bytes) > box_size + 8:
        next_size = int.from_bytes(mp4_bytes[box_size:box_size + 4], 'big')
        if next_size != 0 and (next_size < 8 or next_size > len(mp4_bytes) - box_size + 8):
            _diag(f'bad next box size {next_size} after first box {box_size}')
            return None

    logger.info(
        'motion_photo: extracted %d bytes from %d total (first ftyp=%d, last ftyp=%d)',
        len(mp4_bytes), len(data), data.find(b'ftyp'), last_ftyp,
    )
    return mp4_bytes


def save_video_bytes(mp4_bytes: bytes):
    """Persist already-extracted MP4 bytes to a temp file. Returns the
    same shape as process_video so callers can treat it uniformly."""
    if len(mp4_bytes) > MAX_FILE_BYTES:
        raise MediaError('Live Photo 内嵌视频超过 50MB')
    tmp = _temp_path('.mp4')
    with open(tmp, 'wb') as f:
        f.write(mp4_bytes)
    return {
        'tmp': tmp,
        'ext': '.mp4',
        'mime': 'video/mp4',
        'bytes': len(mp4_bytes),
    }
