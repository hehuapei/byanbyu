import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_cors import CORS

from db import (
    DB_PATH,
    cleanup_expired_trusted_devices,
    create_post,
    create_trusted_device,
    delete_post,
    delete_posts,
    get_post,
    get_settings,
    init_db,
    list_posts,
    list_recent_posts,
    render_rss_item,
    revoke_trusted_device,
    serialize_post,
    set_setting,
)
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
        **get_settings(),
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

    return jsonify({
        'data': [serialize_post(r, include_text=False) for r in rows],
        'total': total,
        'offset': offset,
        'count': len(rows),
    })


@app.route('/api/post', methods=['POST'])
@login_required
def api_create_post():
    body = request.get_json(force=True)
    text = (body.get('text') or '').strip()
    if not text:
        return jsonify({'error': '内容不能为空'}), 400

    post = create_post(text, text_to_html)
    return jsonify({'success': True, 'post': post}), 201


@app.route('/api/post/<post_id>', methods=['DELETE'])
@login_required
def api_delete_post(post_id):
    if not delete_post(post_id):
        abort(404)
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

    deleted_count = delete_posts(normalized_ids)
    return jsonify({'success': True, 'deletedCount': deleted_count})


@app.route('/api/post/<post_id>')
def api_get_post(post_id):
    row = get_post(post_id)
    if not row:
        abort(404)
    return jsonify(serialize_post(row))


@app.route('/rss.xml')
def rss_feed():
    rows = list_recent_posts()

    site_url = get_site_base_url(SITE_URL)
    settings = get_settings()
    items = [
        render_rss_item(r, external_url(f"/post/{r['id']}", SITE_URL))
        for r in rows
    ]

    rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{settings.get('site_title', 'b言b语')}</title>
    <link>{site_url}</link>
    <description>{settings.get('site_desc', '碎碎念')}</description>
    <language>zh-CN</language>
    <atom:link href="{external_url('/rss.xml', SITE_URL)}" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>'''
    return app.response_class(rss, mimetype='application/rss+xml')


@app.route('/api/settings')
def api_get_settings():
    return jsonify(get_settings())


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
    return render_template('index.html', api_base=api_base_path(API_BASE), **get_settings())


@app.route('/quick')
@quick_auth_required(app.secret_key, cookie_name=TRUST_COOKIE_NAME)
def quick_page():
    return render_template('quick.html', **get_settings())


@app.route('/admin')
@login_required
def admin_page():
    return render_template('admin.html', **get_settings())


@app.route('/admin/settings')
@login_required
def admin_settings():
    return render_template('admin_settings.html', **get_settings())


@app.route('/admin/password')
@login_required
def admin_password():
    return render_template('admin_password.html', **get_settings())


@app.route('/post/<post_id>')
def post_detail(post_id):
    row = get_post(post_id)
    if not row:
        abort(404)
    return render_template('post.html', post=serialize_post(row), **get_settings())


# ── Main ────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'🦞 b言b语 running at http://localhost:{port}')
    print(f'   DB: {DB_PATH}')
    app.run(host='0.0.0.0', port=port, debug=True)
