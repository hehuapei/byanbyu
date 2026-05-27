import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

DB_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DB_DIR, 'posts.db')

DEFAULT_SETTINGS = {
    'site_title': 'b言b语',
    'site_desc': '这里没有点赞评论、阅读量以及随之而来的社交压力，我也不关心你多久会点开与忘记这个站点，因为它的全部意义就在于迎合我自己。',
}

SEED_POSTS = [
    '这是我的第一条碎碎念 🦞\n\n这里没有点赞评论、阅读量以及随之而来的社交压力。\n它的全部意义就在于迎合我自己。',
    '也许未来 code plan 可以用运营商套餐来类比，每台电脑启动后自带 server ，前端软件通过标准化接口访问',
    '自媒体就是帮读者提前向 AI 提问和排版的人',
    '"让 AI 自动化工作"能包含多少 startup 的叙事？这句话的天花板是多少？',
    '希望做超出人类意图，导向更好结果的产品',
    '从资产角度看，每个抛出去的项目本身都是负债。至少要支付注意力。',
    '过度抽象是虚无的开始',
    '这是个奖励疯子的时代',
    '小红书上那么多垂类经验分享帖是不是都能转 skill ？以后大家别发帖了，直接发 skill',
    '引擎、改善贫穷还有最近在做的自迭代 agent 都指向了一个足够基础的事实：利用外部能量达到自持的临界值是唯一重要的事',
    'Claude 降智有感：未来全球经济会因为模型公司的一个小动作波动几个百分点',
]


@contextmanager
def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

        row = db.execute("SELECT COUNT(*) FROM posts").fetchone()
        if row[0] == 0 and html_renderer is not None:
            _seed(db, html_renderer)


def _seed(db, html_renderer):
    now = datetime.now()
    rows = []
    for i, text in enumerate(SEED_POSTS):
        dt = datetime.fromtimestamp(now.timestamp() - (len(SEED_POSTS) - i) * 86400 * 3)
        rows.append((
            str(uuid.uuid4()),
            text,
            html_renderer(text),
            dt.isoformat(),
        ))
    db.executemany(
        "INSERT INTO posts (id, text, htmlContent, created_at) VALUES (?, ?, ?, ?)",
        rows
    )


def get_settings():
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {r['key']: r['value'] for r in rows}


def set_setting(key, value):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )


def serialize_post(row, include_text=True):
    dt = datetime.fromisoformat(row['created_at'])
    post = {
        'id': row['id'],
        'htmlContent': row['htmlContent'],
        'created_at': row['created_at'],
        'timeFormatted': dt.strftime('%Y-%m-%d %H:%M:%S'),
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


def create_post(text, html_renderer):
    now = datetime.now()
    post = {
        'id': str(uuid.uuid4()),
        'text': text,
        'htmlContent': html_renderer(text),
        'created_at': now.isoformat(),
        'timeFormatted': now.strftime('%Y-%m-%d %H:%M:%S'),
    }
    with get_db() as db:
        db.execute(
            "INSERT INTO posts (id, text, htmlContent, created_at) VALUES (?, ?, ?, ?)",
            (post['id'], post['text'], post['htmlContent'], post['created_at'])
        )
    return post


def delete_post(post_id):
    with get_db() as db:
        cur = db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    return cur.rowcount > 0


def delete_posts(post_ids):
    if not post_ids:
        return 0
    placeholders = ','.join('?' for _ in post_ids)
    with get_db() as db:
        cur = db.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", tuple(post_ids))
    return cur.rowcount


def list_recent_posts(limit=10):
    with get_db() as db:
        return db.execute(
            "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()


def render_rss_item(row, post_url):
    pub = datetime.fromisoformat(row['created_at']).strftime('%a, %d %b %Y %H:%M:%S GMT')
    title = row['text'].replace('<', '&lt;').replace('>', '&gt;')[:100]
    return f'''    <item>
      <title>{title}</title>
      <link>{post_url}</link>
      <guid>{post_url}</guid>
      <description><![CDATA[{row['htmlContent']}]]></description>
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
