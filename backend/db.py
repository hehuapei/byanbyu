import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

DB_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DB_DIR, 'posts.db')

DEFAULT_SETTINGS = {
    'site_title': 'b言b语',
    'site_desc': '这里没有点赞评论、阅读量以及随之而来的社交压力，我也不关心你多久会点开与忘记这个站点，因为它的全部意义就在于迎合我自己。',
}

SENSITIVE_SETTING_KEYS = frozenset({'admin_password'})

@contextmanager
def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(admin_password=None, html_renderer=None):
    with get_db() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS posts (
                id          TEXT PRIMARY KEY,
                text        TEXT NOT NULL,
                htmlContent TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trusted_devices (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash   TEXT UNIQUE NOT NULL,
                created_at   TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                revoked_at   TEXT,
                ua_hash      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trusted_devices_token ON trusted_devices(token_hash);

            CREATE TABLE IF NOT EXISTS attachments (
                id          TEXT PRIMARY KEY,
                post_id     TEXT NOT NULL,
                kind        TEXT NOT NULL,
                image_path  TEXT NOT NULL,
                thumb_path  TEXT NOT NULL,
                video_path  TEXT,
                mime_image  TEXT NOT NULL,
                mime_video  TEXT,
                width       INTEGER NOT NULL,
                height      INTEGER NOT NULL,
                bytes       INTEGER NOT NULL,
                position    INTEGER NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_attachments_post ON attachments(post_id, position);
        ''')

        for k, v in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (k, v)
            )

        current_password = db.execute(
            "SELECT value FROM settings WHERE key = ?",
            ('admin_password',)
        ).fetchone()
        if not current_password and admin_password:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ('admin_password', admin_password)
            )

def get_settings():
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {r['key']: r['value'] for r in rows}


def get_public_settings():
    return {k: v for k, v in get_settings().items() if k not in SENSITIVE_SETTING_KEYS}


def set_setting(key, value):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )


def serialize_post(row, include_text=True, attachments=None):
    dt = datetime.fromisoformat(row['created_at'])
    post = {
        'id': row['id'],
        'htmlContent': row['htmlContent'],
        'created_at': row['created_at'],
        'timeFormatted': dt.strftime('%Y-%m-%d %H:%M:%S'),
        'attachments': attachments or [],
    }
    if include_text:
        post['text'] = row['text']
    return post


def list_posts(offset=0, count=10, q=''):
    query = (q or '').strip().lower()
    with get_db() as db:
        if query:
            total = db.execute(
                "SELECT COUNT(*) FROM posts WHERE LOWER(text) LIKE ?",
                (f'%{query}%',)
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM posts WHERE LOWER(text) LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f'%{query}%', count, offset)
            ).fetchall()
        else:
            total = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            rows = db.execute(
                "SELECT * FROM posts ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (count, offset)
            ).fetchall()
    return rows, total


def get_post(post_id):
    with get_db() as db:
        return db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()


def create_post(text, html_renderer, attachments=None):
    now = datetime.now()
    post_id = str(uuid.uuid4())
    created_at = now.isoformat()
    html_content = html_renderer(text)
    with get_db() as db:
        db.execute(
            "INSERT INTO posts (id, text, htmlContent, created_at) VALUES (?, ?, ?, ?)",
            (post_id, text, html_content, created_at)
        )
        attachment_rows = []
        for position, att in enumerate(attachments or []):
            att_id = str(uuid.uuid4())
            db.execute(
                '''
                INSERT INTO attachments (
                    id, post_id, kind, image_path, thumb_path, video_path,
                    mime_image, mime_video, width, height, bytes, position, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    att_id, post_id, att['kind'], att['image_path'], att['thumb_path'],
                    att.get('video_path'), att['mime_image'], att.get('mime_video'),
                    att['width'], att['height'], att['bytes'], position, created_at,
                )
            )
            attachment_rows.append({**att, 'id': att_id, 'position': position})
    return {
        'id': post_id,
        'text': text,
        'htmlContent': html_content,
        'created_at': created_at,
        'timeFormatted': now.strftime('%Y-%m-%d %H:%M:%S'),
        'attachment_rows': attachment_rows,
    }


def delete_post(post_id):
    with get_db() as db:
        rows = db.execute(
            "SELECT image_path, thumb_path, video_path FROM attachments WHERE post_id = ?",
            (post_id,)
        ).fetchall()
        cur = db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    if cur.rowcount == 0:
        return False, []
    paths = [p for r in rows for p in (r['image_path'], r['thumb_path'], r['video_path']) if p]
    return True, paths


def delete_posts(post_ids):
    if not post_ids:
        return 0, []
    placeholders = ','.join('?' for _ in post_ids)
    with get_db() as db:
        rows = db.execute(
            f"SELECT image_path, thumb_path, video_path FROM attachments WHERE post_id IN ({placeholders})",
            tuple(post_ids)
        ).fetchall()
        cur = db.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", tuple(post_ids))
    paths = [p for r in rows for p in (r['image_path'], r['thumb_path'], r['video_path']) if p]
    return cur.rowcount, paths


def list_recent_posts(limit=10):
    with get_db() as db:
        return db.execute(
            "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()


def get_attachments_for_posts(post_ids, storage):
    if not post_ids:
        return {}
    placeholders = ','.join('?' for _ in post_ids)
    with get_db() as db:
        rows = db.execute(
            f'''SELECT id, post_id, kind, image_path, thumb_path, video_path,
                       mime_image, mime_video, width, height, position
                FROM attachments
                WHERE post_id IN ({placeholders})
                ORDER BY post_id, position''',
            tuple(post_ids)
        ).fetchall()
    grouped = {pid: [] for pid in post_ids}
    for r in rows:
        urls = {
            'image': storage.url_for(r['image_path']),
            'thumb': storage.url_for(r['thumb_path']),
        }
        if r['video_path']:
            urls['video'] = storage.url_for(r['video_path'])
        grouped.setdefault(r['post_id'], []).append({
            'id': r['id'],
            'kind': r['kind'],
            'urls': urls,
            'mime_image': r['mime_image'],
            'mime_video': r['mime_video'],
            'width': r['width'],
            'height': r['height'],
        })
    return grouped


def render_rss_item(row, post_url, attachments=None, attachment_url_resolver=None):
    pub = datetime.fromisoformat(row['created_at']).strftime('%a, %d %b %Y %H:%M:%S GMT')
    title = xml_escape(row['text'][:100])
    link = xml_escape(post_url)
    description = row['htmlContent']
    if attachments and attachment_url_resolver:
        media_html = []
        for att in attachments:
            img_url = attachment_url_resolver(att['urls']['thumb'])
            media_html.append(f'<p><img src="{xml_escape(img_url)}" alt=""></p>')
        if media_html:
            description = description + '\n' + '\n'.join(media_html)
    return f'''    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid>{link}</guid>
      <description><![CDATA[{description}]]></description>
      <pubDate>{pub}</pubDate>
    </item>'''


def cleanup_expired_trusted_devices(now_iso):
    with get_db() as db:
        db.execute(
            "DELETE FROM trusted_devices WHERE revoked_at IS NOT NULL OR expires_at <= ?",
            (now_iso,)
        )


def create_trusted_device(token_hash, expires_at, ua_hash=None):
    now_iso = datetime.now().isoformat()
    with get_db() as db:
        db.execute(
            '''
            INSERT INTO trusted_devices (token_hash, created_at, expires_at, last_used_at, ua_hash)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (token_hash, now_iso, expires_at, now_iso, ua_hash)
        )


def get_trusted_device(token_hash):
    now_iso = datetime.now().isoformat()
    cleanup_expired_trusted_devices(now_iso)
    with get_db() as db:
        return db.execute(
            '''
            SELECT * FROM trusted_devices
            WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?
            ''',
            (token_hash, now_iso)
        ).fetchone()


def touch_trusted_device(device_id):
    now_iso = datetime.now().isoformat()
    with get_db() as db:
        db.execute(
            "UPDATE trusted_devices SET last_used_at = ? WHERE id = ?",
            (now_iso, device_id)
        )


def revoke_trusted_device(token_hash):
    with get_db() as db:
        db.execute(
            "UPDATE trusted_devices SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (datetime.now().isoformat(), token_hash)
        )
