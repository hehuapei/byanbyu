# b言b语 Clone

一个用 **Flask + SQLite** 做的极简碎碎念站点。

它有两个核心界面：
- 一个保持干净的公开首页，用来浏览内容
- 一个安装后可直接打开的 **`/quick` 极简发帖页**，只保留输入框和发送按钮

这个项目的目标不是做大而全的博客系统，而是做一个 **轻、快、没有社交压力、适合随手发一段话** 的个人站点。

## 来源说明

本项目是对少数派这篇文章中所展示作品形态的一次个人复刻与技术重做：

- https://sspai.com/post/60024

这里使用 **Flask + SQLite** 重新实现一个可自部署版本，主要用于学习、研究和个人使用。这个项目不是在宣称原创概念或原创交互设计。

## Demo 体验

当前的使用路径是这样的：

- 公开访问 `/`：浏览 feed
- 第一次访问 `/quick`：登录并勾选 **记住这台设备**
- 之后再打开 `/quick`：直接进入极简发帖页，无需重复输入密码

如果把站点安装成桌面/主屏幕应用，体感会更像一个专门的“发帖器”。

## 特性

- 公开首页 feed
- 单帖详情页
- 极简快速发帖页 `/quick`
- 可信设备免登录（第一次登录后可长期直达 `/quick`）
- 管理后台（发帖 / 单条删除 / 批量删除 / 修改站点信息 / 修改密码）
- RSS 输出
- 可安装为 Windows / Android 网页应用，启动默认进入 `/quick`

## 技术栈

- Python 3
- Flask
- SQLite
- 纯模板渲染 + 原生 JS

没有前端框架，没有额外数据库，没有复杂依赖。

## 项目结构

```text
bb-clone-py/
├── backend/
│   ├── app.py
│   ├── db.py
│   ├── web_helpers.py
│   ├── data/
│   │   └── posts.db
│   ├── static/
│   │   ├── manifest.webmanifest
│   │   └── icons/
│   │       ├── icon-192.png
│   │       └── icon-512.png
│   ├── requirements.txt
│   └── templates/
│       ├── index.html
│       ├── post.html
│       ├── login.html
│       ├── quick.html
│       ├── admin.html
│       ├── admin_settings.html
│       └── admin_password.html
└── README.md
```

## 本地启动

```bash
cd bb-clone-py/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

建议先配置环境变量：

```bash
export SECRET_KEY="replace-with-a-long-random-string"
export ADMIN_PASSWORD="replace-with-a-strong-password"
python3 app.py
```

默认运行在：

- `http://localhost:5000`

### 本地第一次使用

1. 打开 `http://localhost:5000/`
2. 如果要体验快速发帖，访问 `http://localhost:5000/quick`
3. 第一次登录时勾选 **记住这台设备**
4. 以后直接打开 `/quick` 即可发帖

## 安装成“发帖器”

这个项目已经带了最小 manifest，安装后的默认启动地址是：

- `/quick`

### Windows

使用 **Edge** 或 **Chrome** 打开：

- `https://your-domain.com/quick`

然后：

- **Edge**：右上角 `...` → **应用** → **将此站点安装为应用**
- **Chrome**：右上角 `...` → **安装应用**

安装后：
- 可以固定到开始菜单 / 任务栏
- 打开默认进入 `/quick`

### Android

使用 **Chrome** 打开：

- `https://your-domain.com/quick`

然后：

- 右上角 `...` → **安装应用**
- 如果没有该入口，就使用 **添加到主屏幕**

安装后点击图标，会优先进入 `/quick`。

### 使用建议

如果你是正式使用，推荐：

- 使用 **HTTPS**
- 把站点部署到一个固定域名
- 在自己的设备上第一次登录后勾选 **记住这台设备**

这样才最接近真正的“打开就发”。

## 页面

- `GET /`：公开首页
- `GET /post/<id>`：单帖详情页
- `GET /quick`：极简快速发帖页（受可信设备/session 保护）
- `GET /admin/login`：后台登录页
- `GET /admin`：后台管理页
- `GET /admin/settings`：站点设置页
- `GET /admin/password`：修改密码页
- `GET /rss.xml`：RSS

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/feed?offset=0&count=10&q=xxx` | 帖子列表 |
| GET | `/api/post/<id>` | 单条帖子 |
| POST | `/api/post` | 发帖，需要登录或先进入受保护页面恢复 session |
| DELETE | `/api/post/<id>` | 单条删帖，需要登录 |
| POST | `/api/posts/batch-delete` | 批量删帖，需要登录 |
| GET | `/api/settings` | 获取站点设置 |
| PUT | `/api/settings` | 更新站点设置，需要登录 |
| PUT | `/api/settings/password` | 修改管理密码，需要登录 |

## 环境变量

- `SECRET_KEY`：Flask session key。生产环境必须配置。
- `ADMIN_PASSWORD`：首次初始化管理密码；写入数据库后，后续可在后台修改。
- `SITE_URL`：生成 RSS 绝对链接时优先使用的站点地址，例如 `https://example.com`。
- `API_BASE`：可选。用于把首页里的 `/api/*` 请求前缀指向别的路径前缀。
- `CORS_ORIGINS`：可选。逗号分隔的允许跨域来源列表，例如 `https://site-a.com,https://site-b.com`。
- `SESSION_COOKIE_SECURE`：可选。设为 `true` / `1` / `yes` 时，仅通过 HTTPS 发送 session cookie。
- `PORT`：可选。默认 `5000`。

## 安全说明

这个项目默认面向 **个人使用 / 自部署** 场景。

当前的快速发帖体验依赖“可信设备”机制：
- 第一次在某台设备上登录时，可以选择记住该设备
- 之后访问 `/quick` 时无需重复输入密码
- 登出会撤销当前设备的 trusted token

因此：
- 请只在你自己的设备上勾选 **记住这台设备**
- 建议生产环境启用 HTTPS
- 不建议把这个项目直接当成多用户公共发帖系统使用

## 部署建议

最简单的部署方式是：

- Flask 同源部署
- 站点域名下同时提供公开首页和 `/quick`
- 使用 SQLite 持久化数据

如果你希望安装体验更稳定：
- 保持域名固定
- 保持 HTTPS 可用
- 不要频繁更换 `SECRET_KEY`

## 适合谁

如果你想要的是：
- 一个没有评论、点赞、阅读量压力的轻博客
- 一个像便签一样的“随手发一句”入口
- 一个可以装到桌面或手机主屏幕上的个人发帖器

那这个项目大概率适合你。

## 开源说明

如果你把这个项目继续 fork、修改或公开发布，建议保留上面的来源说明，并在你自己的 README 里明确写出哪些部分是你新增或改造的。

## License

如果你准备开源社区分享，建议在仓库里补一个明确的 License 文件（例如 MIT）。当前 README 不替代正式许可证。