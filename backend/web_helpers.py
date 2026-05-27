import hashlib
from functools import wraps
from urllib.parse import quote, urlsplit

from flask import jsonify, redirect, request, session, url_for

from db import get_settings, get_trusted_device, touch_trusted_device


def text_to_html(text):
    escaped = (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;'))

    html = []
    lines = escaped.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()

        if trimmed.startswith('```'):
            lang = trimmed[3:].strip()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code.append(lines[i])
                i += 1
            tag = f' class="language-{lang}"' if lang else ''
            html.append(f'<pre><code{tag}>{"\\n".join(code)}</code></pre>')
            i += 1
            continue

        if trimmed.startswith('> '):
            html.append(f'<blockquote><p>{trimmed[2:]}</p></blockquote>')
            i += 1
            continue

        if not trimmed:
            i += 1
            continue

        html.append(f'<p>{line}</p>')
        i += 1

    return '\n'.join(html)


def _login_redirect_response():
    next_path = request.full_path if request.query_string else request.path
    if next_path.endswith('?'):
        next_path = next_path[:-1]
    return redirect(f"{url_for('admin_login')}?next={quote(next_path, safe='/?=&')}")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': '请先登录'}), 401
            return _login_redirect_response()
        return f(*args, **kwargs)
    return decorated


def get_admin_password():
    return (get_settings().get('admin_password') or '').strip()


def require_admin_password():
    password = get_admin_password()
    if password:
        return password
    raise RuntimeError('ADMIN_PASSWORD is not configured. Set ADMIN_PASSWORD before starting the app.')


def get_site_base_url(site_url):
    if site_url:
        return site_url
    return request.url_root.rstrip('/')


def external_url(path, site_url):
    if path.startswith('http://') or path.startswith('https://'):
        return path
    base = get_site_base_url(site_url)
    return f"{base}/{path.lstrip('/')}"


def api_base_path(api_base):
    if not api_base:
        return ''
    parsed = urlsplit(api_base)
    return parsed.path.rstrip('/') if parsed.scheme and parsed.netloc else api_base


def trusted_device_token_hash(secret_key, token):
    return hashlib.sha256(f'{secret_key}:{token}'.encode()).hexdigest()


def restore_trusted_device_session(secret_key, cookie_name='quick_trust'):
    if session.get('admin_logged_in'):
        return True

    token = request.cookies.get(cookie_name)
    if not token:
        return False

    token_hash = trusted_device_token_hash(secret_key, token)
    device = get_trusted_device(token_hash)
    if not device:
        return False

    session['admin_logged_in'] = True
    session.permanent = True
    touch_trusted_device(device['id'])
    return True


def quick_auth_required(secret_key, cookie_name='quick_trust'):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if restore_trusted_device_session(secret_key, cookie_name=cookie_name):
                return f(*args, **kwargs)
            return _login_redirect_response()
        return decorated
    return decorator
