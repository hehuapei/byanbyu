import io
import logging
import os
import tempfile

import filetype
from PIL import Image, ImageOps
import pillow_heif


pillow_heif.register_heif_opener()
logger = logging.getLogger(__name__)


MAX_FILE_BYTES = 30 * 1024 * 1024  # 30 MB per file

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
            raise MediaError('单文件不能超过 30MB')
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
