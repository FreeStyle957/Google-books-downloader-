# Google Books Downloader (Web UI)

把 Google Books 上**可预览**的书一页页抓成高清图片，并合并成 PDF。带本地网页界面，双击即用。

Fork 自 [aprikyan/google-books-downloader](https://github.com/aprikyan/google-books-downloader)，
因原版已无法运行而重写（详见下方「技术说明」）。

> 请只下载你有权使用的内容（公有领域作品、你自己购买/授权的书、或 Google 开放试阅的部分）。

---

## 两种方式

### A. 直接用打包好的 exe（推荐）

1. 到本仓库的 **Releases** 页面下载 `GoogleBooksDownloader.exe`
2. 双击它 —— 浏览器会自动打开 `http://127.0.0.1:8733`
3. 关闭浏览器标签页约 30 秒后，程序自动完全退出，不留后台进程

**环境要求**：Windows 10/11，且装有 Microsoft Edge 或 Google Chrome（Brave 也可以）。
首次运行时 Selenium 会联网自动下载与你浏览器版本匹配的驱动。

### B. 从源码运行

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw.exe app.py
```

想重新打包成 exe：

```bat
.venv\Scripts\pip install pyinstaller
build.bat
```

---

## 使用步骤

1. 在 Google Books 打开一本书，复制地址栏网址
   （旧式 `books.google.com/books?id=...` 和新式 `google.com/books/edition/标题/ID...` 都支持）
2. 粘贴到界面里，点 **扫描**（整本约 3–5 分钟，滚到底自动停）
3. 选择页码：`all` / `1,10-50,odd`
4. 点 **下载**

- 图片为 Google 提供的最高分辨率（`w=69420`），保存为 JPEG
- 默认输出到 exe 所在目录下的 `downloads\<书名>\`，可勾选合并为 PDF
- 书名过长时自动截断，避免超过 Windows 260 字符路径上限

**只有带预览（完整视图 / 摘要视图）的书才能下载**，这是 Google 的版权限制，工具无法绕过。

---

## 技术说明

原版（2020）依赖的 `chromedriver v83` + `selenium-wire` 在今天已全部失效：老驱动带不动现代浏览器，
selenium-wire 的请求拦截在 Chromium 上不可用，且 Chromium 已移除 `performance` 日志类型。

本版改为：

- 自行以 `--remote-debugging-port` 启动浏览器，Selenium 负责交互，同时用一条 **CDP WebSocket**
  监听 `Network.requestWillBeSent`，从中提取 `books.google.com/books/...content?...&sig=...` 图片地址
- 图片**在浏览器内**下载（复用已通过验证的会话），不受本机代理设置影响；`requests` 仅作备用
- 扫描通过 JS 驱动 `.overflow-scrolling` 容器逐屏滚动触发懒加载，滚到底自动停止
- 图片 URL 里的 `sig` 签名已足够，下载不需要 cookie

相比原版新增：网页界面、新式 URL 解析、`/books/publisher/content` 路径兼容（出版商提供的书）、
Edge/Chrome/Brave 自动发现、长路径防护、关页自停。

---

## 环境变量（可选）

| 变量 | 作用 |
|---|---|
| `GBD_PORT` | 服务端口，默认 `8733` |
| `GBD_BROWSER_PATH` | 指定浏览器 exe 路径（绿色版/便携版浏览器用） |
| `GBD_IDLE_TIMEOUT` | 关页后多久退出（秒），默认 `30` |
| `GBD_SCAN_ROUNDS` | 扫描最大轮数，默认 `260` |
| `GBD_NO_BROWSER=1` | 只起服务、不自动打开标签页 |
| `GBD_DEBUG=1` | 把服务内部事件追加写入 `gbd.log` |

启动异常时可查看 exe 同目录下的 `gbd.log`（设 `GBD_DEBUG=1` 会有更详细记录）。

## 已知限制

- 打包产物为 Windows 版；源码在 macOS/Linux 上也能运行（自动查找 Chrome/Chromium）
- 需要能访问 `books.google.com`
- 整本扫描受 Google 懒加载节奏限制，无法加速
- 部分地区的 Google 域名不提供预览，程序固定从 `books.google.com` 起跳以获得最佳兼容性

## 其他文件

| 文件 | 用途 |
|---|---|
| `app.py` | 入口：起服务 + 开浏览器 + 自停 |
| `server.py` | FastAPI 服务与 API |
| `core.py` | 抓取引擎 |
| `static/index.html` | 网页界面 |
| `build.spec` / `build.bat` | 打包配置 |
| `tests/` | 排查用的诊断脚本（不是单元测试） |
| `gbd.py` | 原版脚本，仅作对照，已不可用 |

## License

MIT（见 LICENSE，继承自原项目）。
