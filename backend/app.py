import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from xml.sax.saxutils import escape as xml_escape

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, send_from_directory, session, url_for
from flask_cors import CORS

from db import (
    DB_PATH,
    cleanup_expired_trusted_devices,
    create_post,
    create_trusted_device,
    delete_post,
    delete_posts,
    get_attachments_for_posts,
    get_post,
    get_public_settings,
    init_db,
    list_posts,
    list_recent_posts,
    render_rss_item,
    revoke_trusted_device,
    serialize_post,
    set_setting,
)
from media import IMAGE_MIMES, VIDEO_MIMES, MediaError, detect_mime, process_image, process_video
from storage import get_storage
from web_helpers import (
    api_base_path,
    external_url,
    get_admin_password,
    get_site_base_url,
    login_required,
    quick_auth_required,
    require_admin_password,
    text_to_html,
    trusted_device_token_hash,
)


def safe_redirect_target(target):
    if not target or not target.startswith('/') or target.startswith('//'):
        return '/admin'
    return target


TRUST_COOKIE_NAME = 'quick_trust'
TRUST_DEVICE_DAYS = 30

app = Flask(__name__)

logger = logging.getLogger(__name__)

app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

SECRET_KEY = os.environ.get('SECRET_KEY')
if SECRET_KEY:
    app.secret_key = SECRET_KEY
else:
    app.secret_key = os.urandom(24).hex()
    print('WARNING: SECRET_KEY is not set. Using a temporary key for local development.')

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '').lower() in {'1', 'true', 'yes'}

ADMIN_PASSWORD = (os.environ.get('ADMIN_PASSWORD') or '').strip()
SITE_URL = (os.environ.get('SITE_URL') or '').rstrip('/')
API_BASE = (os.environ.get('API_BASE') or '').rstrip('/')
CORS_ORIGINS = [origin.strip() for origin in os.environ.get('CORS_ORIGINS', '').split(',') if origin.strip()]
if CORS_ORIGINS:
    CORS(app, resources={r'/api/*': {'origins': CORS_ORIGINS}})

init_db(admin_password=ADMIN_PASSWORD or None, html_renderer=text_to_html)
cleanup_expired_trusted_devices(datetime.now().isoformat())
storage = get_storage()


# ── Auth ───────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    try:
        pwd = require_admin_password()
    except RuntimeError as exc:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': str(exc)}), 500
        abort(500, description=str(exc))

    if request.method == 'POST':
        body = request.get_json(force=True)
        redirect_target = safe_redirect_target(body.get('next'))
        if body.get('password') == pwd:
            session['admin_logged_in'] = True
            session.permanent = True

            response = make_response(jsonify({'success': True, 'redirect': redirect_target}))
            if body.get('trust_device'):
                token = secrets.token_urlsafe(32)
                token_hash = trusted_device_token_hash(app.secret_key, token)
                expires_at = (datetime.now() + timedelta(days=TRUST_DEVICE_DAYS)).isoformat()
                create_trusted_device(token_hash, expires_at)
                response.set_cookie(
                    TRUST_COOKIE_NAME,
                    token,
                    max_age=TRUST_DEVICE_DAYS * 24 * 60 * 60,
                    httponly=True,
                    samesite='Lax',
                    secure=app.config['SESSION_COOKIE_SECURE'],
                    path='/',
                )
            return response
        return jsonify({'success': False, 'error': '密码错误'}), 403
    return render_template(
        'login.html',
        next_path=safe_redirect_target(request.args.get('next')),
        **get_public_settings(),
    )


@app.route('/admin/logout')
def admin_logout():
    token = request.cookies.get(TRUST_COOKIE_NAME)
    if token:
        revoke_trusted_device(trusted_device_token_hash(app.secret_key, token))
    session.pop('admin_logged_in', None)
    response = make_response(redirect(url_for('admin_login')))
    response.delete_cookie(TRUST_COOKIE_NAME, path='/')
    return response


# ── API Routes ──────────────────────────────────────────────

@app.route('/api/feed')
def api_feed():
    offset = request.args.get('offset', 0, type=int)
    count = request.args.get('count', 10, type=int)
    q = request.args.get('q', '') or ''

    rows, total = list_posts(offset=offset, count=count, q=q)
    post_ids = [r['id'] for r in rows]
    attachments_by_post = get_attachments_for_posts(post_ids, storage)

    return jsonify({
        'data': [serialize_post(r, include_text=False, attachments=attachments_by_post.get(r['id'])) for r in rows],
        'total': total,
        'offset': offset,
        'count': len(rows),
    })


def _process_attachments_from_request():
    """Parse the multipart form, validate, transcode images, save to storage.

    Returns (attachment_records, saved_rel_paths). Caller is responsible for
    deleting saved_rel_paths if the post insert fails.
    Raises MediaError on validation issues.
    """
    raw_meta = request.form.get('attachments_meta') or '[]'
    try:
        meta_list = json.loads(raw_meta)
    except json.JSONDecodeError:
        raise MediaError('附件元信息格式错误')
    if not isinstance(meta_list, list):
        raise MediaError('附件元信息格式错误')

    tmp_paths_to_cleanup = []
    saved_rel_paths = []
    records = []

    try:
        for index, meta in enumerate(meta_list):
            if not isinstance(meta, dict):
                raise MediaError('附件元信息格式错误')
            kind = meta.get('kind')
            if kind not in ('image', 'live_photo'):
                raise MediaError(f'未知附件类型 {kind}')

            image_file = request.files.get(f'file_{index}_image')
            if image_file is None or not image_file.filename:
                raise MediaError(f'第 {index + 1} 个附件缺少图片')
            image_mime = detect_mime(image_file)
            if image_mime not in IMAGE_MIMES:
                raise MediaError(f'第 {index + 1} 个附件图片类型不支持: {image_mime}')

            image_info = process_image(image_file, image_mime)
            tmp_paths_to_cleanup.extend([image_info['image_tmp'], image_info['thumb_tmp']])

            video_info = None
            if kind == 'live_photo':
                video_file = request.files.get(f'file_{index}_video')
                if video_file is None or not video_file.filename:
                    raise MediaError(f'第 {index + 1} 个 Live Photo 缺少视频')
                video_mime = detect_mime(video_file)
                if video_mime not in VIDEO_MIMES:
                    raise MediaError(f'第 {index + 1} 个 Live Photo 视频类型不支持: {video_mime}')
                video_info = process_video(video_file, video_mime)
                tmp_paths_to_cleanup.append(video_info['tmp'])

            image_rel = storage.save(image_info['image_tmp'], image_info['image_ext'])
            saved_rel_paths.append(image_rel)
            thumb_rel = storage.save(image_info['thumb_tmp'], image_info['thumb_ext'])
            saved_rel_paths.append(thumb_rel)
            video_rel = None
            if video_info is not None:
                video_rel = storage.save(video_info['tmp'], video_info['ext'])
                saved_rel_paths.append(video_rel)

            total_bytes = image_info['bytes'] + (video_info['bytes'] if video_info else 0)
            records.append({
                'kind': kind,
                'image_path': image_rel,
                'thumb_path': thumb_rel,
                'video_path': video_rel,
                'mime_image': image_info['image_mime'],
                'mime_video': video_info['mime'] if video_info else None,
                'width': image_info['width'],
                'height': image_info['height'],
                'bytes': total_bytes,
            })
    except Exception:
        for tmp in tmp_paths_to_cleanup:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        for rel in saved_rel_paths:
            try:
                storage.delete(rel)
            except Exception:
                pass
        raise

    return records, saved_rel_paths


@app.route('/api/post', methods=['POST'])
@login_required
def api_create_post():
    is_multipart = request.content_type and request.content_type.startswith('multipart/form-data')
    if is_multipart:
        text = (request.form.get('text') or '').strip()
    else:
        body = request.get_json(force=True, silent=True) or {}
        text = (body.get('text') or '').strip()

    has_attachments = is_multipart and (request.form.get('attachments_meta') or '[]') != '[]'
    if not text and not has_attachments:
        return jsonify({'error': '内容不能为空'}), 400

    attachment_records = []
    saved_rel_paths = []
    if is_multipart:
        try:
            attachment_records, saved_rel_paths = _process_attachments_from_request()
        except MediaError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

    try:
        post = create_post(text, text_to_html, attachments=attachment_records)
    except Exception as exc:
        for rel in saved_rel_paths:
            try:
                storage.delete(rel)
            except Exception:
                pass
        logger.exception('create_post failed: %s', exc)
        return jsonify({'success': False, 'error': '保存失败'}), 500

    attachments_by_post = get_attachments_for_posts([post['id']], storage)
    serialized = serialize_post(
        {
            'id': post['id'], 'text': post['text'], 'htmlContent': post['htmlContent'],
            'created_at': post['created_at'],
        },
        attachments=attachments_by_post.get(post['id'], []),
    )
    return jsonify({'success': True, 'post': serialized}), 201


@app.route('/api/post/<post_id>', methods=['DELETE'])
@login_required
def api_delete_post(post_id):
    deleted, paths = delete_post(post_id)
    if not deleted:
        abort(404)
    for rel in paths:
        try:
            storage.delete(rel)
        except Exception as exc:
            logger.warning('failed to remove attachment %s: %s', rel, exc)
    return jsonify({'success': True})


@app.route('/api/posts/batch-delete', methods=['POST'])
@login_required
def api_batch_delete_posts():
    body = request.get_json(force=True)
    ids = body.get('ids') or []
    if not isinstance(ids, list):
        return jsonify({'success': False, 'error': '参数错误'}), 400

    normalized_ids = []
    seen_ids = set()
    for post_id in ids:
        if not isinstance(post_id, str):
            return jsonify({'success': False, 'error': '参数错误'}), 400
        if post_id and post_id not in seen_ids:
            normalized_ids.append(post_id)
            seen_ids.add(post_id)

    if not normalized_ids:
        return jsonify({'success': False, 'error': '请选择要删除的内容'}), 400

    deleted_count, paths = delete_posts(normalized_ids)
    for rel in paths:
        try:
            storage.delete(rel)
        except Exception as exc:
            logger.warning('failed to remove attachment %s: %s', rel, exc)
    return jsonify({'success': True, 'deletedCount': deleted_count})


@app.route('/api/post/<post_id>')
def api_get_post(post_id):
    row = get_post(post_id)
    if not row:
        abort(404)
    attachments_by_post = get_attachments_for_posts([post_id], storage)
    return jsonify(serialize_post(row, attachments=attachments_by_post.get(post_id, [])))


@app.route('/uploads/<path:rel>')
def serve_upload(rel):
    response = send_from_directory(storage.root_dir, rel)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.route('/rss.xml')
def rss_feed():
    rows = list_recent_posts()

    site_url = get_site_base_url(SITE_URL)
    settings = get_public_settings()
    attachments_by_post = get_attachments_for_posts([r['id'] for r in rows], storage)
    resolver = lambda rel_url: external_url(rel_url, SITE_URL)
    items = [
        render_rss_item(
            r,
            external_url(f"/post/{r['id']}", SITE_URL),
            attachments=attachments_by_post.get(r['id']),
            attachment_url_resolver=resolver,
        )
        for r in rows
    ]

    rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{xml_escape(settings.get('site_title', 'b言b语'))}</title>
    <link>{xml_escape(site_url)}</link>
    <description>{xml_escape(settings.get('site_desc', '碎碎念'))}</description>
    <language>zh-CN</language>
    <atom:link href="{xml_escape(external_url('/rss.xml', SITE_URL))}" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>'''
    return app.response_class(rss, mimetype='application/rss+xml')


@app.route('/api/settings')
def api_get_settings():
    return jsonify(get_public_settings())


@app.route('/api/settings/password', methods=['PUT'])
@login_required
def api_change_password():
    body = request.get_json(force=True)
    old_pwd = body.get('oldPassword', '')
    new_pwd = (body.get('newPassword') or '').strip()

    if not new_pwd or len(new_pwd) < 4:
        return jsonify({'success': False, 'error': '新密码至少4个字符'}), 400

    if old_pwd != get_admin_password():
        return jsonify({'success': False, 'error': '旧密码错误'}), 403

    set_setting('admin_password', new_pwd)
    return jsonify({'success': True})


@app.route('/api/settings', methods=['PUT'])
@login_required
def api_update_settings():
    body = request.get_json(force=True)
    for k, v in body.items():
        if k in ('site_title', 'site_desc'):
            set_setting(k, v.strip())
    return jsonify({'success': True})


# ── Page Routes ─────────────────────────────────────────────

@app.route('/')
def serve_index():
    return render_template('index.html', api_base=api_base_path(API_BASE), **get_public_settings())


@app.route('/quick')
@quick_auth_required(app.secret_key, cookie_name=TRUST_COOKIE_NAME)
def quick_page():
    return render_template('quick.html', **get_public_settings())


@app.route('/admin')
@login_required
def admin_page():
    return render_template('admin.html', **get_public_settings())


@app.route('/admin/settings')
@login_required
def admin_settings():
    return render_template('admin_settings.html', **get_public_settings())


@app.route('/admin/password')
@login_required
def admin_password():
    return render_template('admin_password.html', **get_public_settings())


@app.route('/post/<post_id>')
def post_detail(post_id):
    row = get_post(post_id)
    if not row:
        abort(404)
    attachments_by_post = get_attachments_for_posts([post_id], storage)
    return render_template(
        'post.html',
        post=serialize_post(row, attachments=attachments_by_post.get(post_id, [])),
        **get_public_settings(),
    )


# ── Main ────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    print(f'🦞 b言b语 running at http://localhost:{port}')
    print(f'   DB: {DB_PATH}')
    app.run(host='0.0.0.0', port=port, debug=debug)
