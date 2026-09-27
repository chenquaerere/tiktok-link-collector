# 移植到 macOS 的可行性分析

> 分析日期：2026-09-26 ｜ 对应版本：v1.1.0（8921 行 Python，67 个文件）
> 结论：**代码层面可行性高（约 95% 代码零改动），真正的门槛在"打包 + 签名"环节，且必须有一台 Mac。**

---

## 一、结论速览

| 维度 | 评估 | 说明 |
|---|---|---|
| 代码可移植性 | ✅ **高** | 业务层/数据层/采集层全部跨平台，无需改动 |
| UI 可移植性 | ✅ **中高** | customtkinter 官方支持 macOS；需替换 3 处 Windows 专有字体名 |
| 平台细节适配 | ⚠️ **中** | 14 个具体改动点，集中在 6 个文件 |
| 打包能力 | ❌ **硬门槛** | PyInstaller **不能交叉编译**，必须在 macOS 上打包 |
| 分发给他人 | ❌ **硬门槛 + 花钱** | macOS Gatekeeper 会拦截未签名程序；要"双击即用"需 Apple 开发者账号（99 美元/年） |
| 工作量估算 | — | 代码改造约 1~2 天；打包+签名调试约 1~2 天（首次踩坑） |

**一句话**：把它变成"能在 Mac 上跑"**不贵**；把它变成"Mac 用户下载就能双击用"**需要额外投入**，主要卡在签名和 Mac 打包机。

---

## 二、逐层技术栈评估

### 2.1 零改动层（约 8500 行 / 95%）

| 模块 | 行数 | 为什么不用改 |
|---|---|---|
| `app/core/` 业务规则 | 540 | 纯逻辑，无平台 API |
| `app/db/` SQLite 数据层 | 512 | sqlite3 内置于 Python，WAL 跨平台 |
| `app/services/` 编排层 | 483 | 只调下层接口 |
| `app/export/` 导出 | 164 | openpyxl 跨平台 |
| `app/log/` 日志 | 184 | logging 模块跨平台 |
| `app/collector/` + `app/chat/` 采集引擎 | 2095 | Playwright 官方支持 macOS；采集逻辑是纯 DOM/API 操作 |
| `app/ui/pages/` 等界面逻辑 | 4446 | customtkinter 基于 tkinter，官方声明支持 Windows/macOS/Linux |

**关键优势**：这个项目没有用任何 Win32 API 做核心功能，也没有第三方 GUI 框架的闭源依赖（如 PyQt 的某些商业组件）。它不是"Windows 专用程序"，只是"恰好在 Windows 上开发的跨平台程序"。

### 2.2 已经做好跨平台兼容的部分（无需改动）

项目里已有两处主动的平台判断，说明当初就留了余地：

```python
# app/ui/notify.py —— 系统提示音已三平台适配
if sys.platform == "win32":      import winsound; winsound.MessageBeep(...)
elif sys.platform == "darwin":   subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
else:                            print("\a")

# app/ui/theme.py —— 高 DPI 适配已判断平台（非 Windows 直接跳过）
if sys.platform != "win32":
    return
ctypes.windll.shcore.SetProcessDpiAwareness(2)
```

---

## 三、必须改造清单（共 14 项）

### 🔴 P0 — 不改就跑不起来 / 数据会出错（4 项）

| # | 位置 | 现状 | macOS 下的问题 | 改法 |
|---|---|---|---|---|
| 1 | `app/app.py` `app_dir()` | frozen 时返回 `sys.executable` 的父目录 | macOS 里该路径是 `Xxx.app/Contents/MacOS/`，**数据会写进 app 包内部**；且 `/Applications` 下的包通常不可写 → 配置/数据库/登录态全部失败 | iPhone 化的标准做法：改到 `~/Library/Application Support/TikTokLinkCollector/` |
| 2 | `build.py` `_ms_playwright_dir()` | `os.environ["LOCALAPPDATA"] / "ms-playwright"` | macOS 的 Playwright 内核缓存在 `~/Library/Caches/ms-playwright`，此路径为空 → 内核打包永远跳过 → 采集全军覆没 | 按平台取缓存根目录 |
| 3 | `build.py` 全局 | 硬编码 `--icon icon.ico`、产物 `.exe`、`--add-data "assets;assets"`（分号） | macOS 需要 `.icns` 图标；`--add-data` 分隔符是 `:`（冒号）；产物是 `.app` bundle | 写平台分支 |
| 4 | 打包环境 | — | **PyInstaller 无法在 Windows 上生成 macOS 产物**（官方明确不支持交叉编译） | 必须用 Mac 机器，或 GitHub Actions 的 `macos-14` runner |

### 🟡 P1 — 影响功能/观感，必须处理（7 项）

| # | 位置 | 现状 | macOS 下的表现 | 改法 |
|---|---|---|---|---|
| 5 | `app/ui/theme.py:66` | `FONT_FAMILY = "Microsoft YaHei UI"` | Mac 无此字体 → Tk 回退默认字体，中文可能显示为方框或字形难看 | 平台映射：`PingFang SC` |
| 6 | `theme.py:67` | `FONT_MONO = "Consolas"` | 同上 | 映射为 `Menlo` 或 `SF Mono` |
| 7 | `app/ui/link_window.py:23` | `("Microsoft YaHei UI", 11)` 硬编码 | 同上，且是**写死的元组**，不走 theme | 改为引用 `theme.FONT` |
| 8 | `app/ui/emoji.py:34` | `_FONT_PATH` 指向 `C:/Windows/Fonts/seguiemj.ttf` | Mac 无该文件 → `_font()` 返回 None → **彩色 emoji 静默失效**（群名「🔥⚡️」显示不出） | 见 §4.1 专节分析 |
| 9 | `app/ui/pages/logs_page.py:132` | `os.startfile(d)` | macOS 无 `os.startfile` → 抛 AttributeError（已被 except 吃掉，退化为 Toast 提示，功能等于没有） | `subprocess.run(["open", d])` |
| 10 | `app/collector/browser.py:15` | UA 常量写死 `Windows NT 10.0; Win64; x64`，viewport `1366x900` | 可保留（伪装指纹），但与 Mac 实际屏幕/字体不一致，是潜在的被动检测特征 | 按平台生成 UA，viewport 用默认或按屏幕 |
| 11 | `app/update.py:59` | 更新包取 `assets[0]`（第一个附件） | 双平台发布后，**Windows 用户会下载到 macOS 包** | 按平台过滤附件名（含 `win`/`mac` 关键字） |

### 🟢 P2 — 需实测验证，可能要微调（3 项）

| # | 位置 | 风险点 |
|---|---|---|
| 12 | `app/ui/components/toast.py` | Toast 用「无边框置顶 Toplevel」（`overrideredirect` + `-topmost`）。macOS 上无边框窗口不接收键盘事件、层级控制与 Windows 不同，需实测是否真的浮在窗口之上 |
| 13 | 全项目 `CTkToplevel` / `grab_set()` | macOS 上 `grab_set` 的模态行为与 X11/Win32 有差异（本项目已把关键操作改成内联二次确认，影响面小） |
| 14 | `theme.py` DPI / `set_widget_scaling` | macOS Retina 是 2x，customtkinter 的缩放策略在 1x/2x 下观感差异较大，控件尺寸与字体需要实测微调 |

---

## 四、三个关键技术风险（深挖）

### 4.1 彩色 emoji：Mac 上不能直接照搬

**现状**：项目用 Pillow + `seguiemj.ttf`（Windows 的 Segoe UI Emoji，COLR 彩色矢量格式）+ `embedded_color=True` 渲染彩色 emoji，已实测出 375+ 色。

**Mac 的问题**：系统自带的是 `Apple Color Emoji.ttc`，它是 **sbix 格式（彩色位图）**，与 Windows 的 COLR 机制不同，存在两个实际坑：

1. **只接受固定字号**：sbix 是位图字体，只内嵌了若干固定像素尺寸。传任意字号会直接抛 `OSError: invalid pixel size`（社区大量同类报错），必须取它支持的尺寸（通常是 160px）再缩放。
2. **Pillow/FreeType 版本敏感**：sbix 支持需要 FreeType ≥ 2.5.1 且编译时链接了 libpng。不同 Pillow 版本表现不一致。

**两个可选方案**：

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 用系统字体 | 改用 `Apple Color Emoji.ttc` + 固定 160px 渲染 | 不增体积 | 要处理固定字号限制；依赖 Pillow 版本；Windows/Mac 两套分支 |
| B. **随包分发 Noto Color Emoji** | 打包一个 `NotoColorEmoji.ttf`（约 10MB，CBDT/CBLC 格式，Pillow 完美支持） | **两个平台用同一套代码、同一套渲染结果**，行为一致可测 | 包体积 +10MB |

**推荐 B**。项目现在有 Windows/Mac 两套字体逻辑的分支成本，远大于 10MB 体积；而且结论一致意味着"Windows 上验证通过 = Mac 上也通过"，可以直接复用现有测试。

### 4.2 Playwright 内核：体积与签名双重问题

- Mac 上的 Chromium 内核独立于 Windows 那份，必须单独下载（约 150~200MB），**不能复用**。
- 打包时要塞进 app bundle，包体积预计与 Windows 版接近（压缩后约 350~400MB）。
- **未签名的 Chromium 被拷贝到别人机器后会带上 `com.apple.quarantine` 属性**，可能直接被 Gatekeeper 拒绝执行 → 采集功能失效。这是移植后最容易被忽略的坑。

### 4.3 签名与公证：决定"能不能给别人用"

macOS 从 10.15 起对未公证程序极其严格。三种处理方式：

| 方式 | 用户拿到后 | 成本 |
|---|---|---|
| 不签名 | 提示「应用已损坏，无法打开」，需要用户手动执行 `xattr -dr com.apple.quarantine /Applications/Xxx.app` | 0 |
| ad-hoc 签名（`codesign -s -`） | 仍是「无法验证开发者」，需要**右键 → 打开**才能运行 | 0 |
| **Developer ID 签名 + 公证（notarization）** | **双击即用**，与正常 App 无异 | Apple Developer Program **99 美元/年** |

如果只是自己用 / 给少数人用，前两种可以接受；如果要公开分发且希望体验好，就需要第 3 种。

---

## 五、三条实现路线对比

### 路线 A：原生移植（PyInstaller → .app）

- **做法**：按 §三 改造 14 项 → 在 Mac 上 `pyinstaller` 打出 `.app` → 压成 `.dmg` 或 `.zip`
- **改动量**：约 14 处，涉及 6 个文件（`app.py` / `build.py` / `theme.py` / `emoji.py` / `link_window.py` / `logs_page.py` / `browser.py` / `update.py`）
- **优点**：UI 与 Windows 版 100% 一致（customtkinter 跨平台），用户拿到的是原生桌面程序，离线可用，无服务器成本
- **缺点**：必须有 Mac 打包；未签名要给用户写"右键打开"说明；以后每次改动都要打两个平台包
- **风险**：中。主要来自 Tk 在 macOS 的字体渲染、Treeview 样式、Retina 缩放这几处历史性差异

### 路线 B：Web 版（服务端跑 Playwright，浏览器访问）

- **做法**：后端服务化，前端用浏览器访问。类似你在 TikTok 去水印项目 v4.3+ 已经做过的 Web 版
- **优点**：任何系统（Mac / Linux / 手机）都能用，一次部署
- **缺点**：登录态（TikTok 账号登录）在远端服务器上处理很别扭；需要一台常开服务器；Playwright 常驻服务端资源开销大；等于重做一个产品形态
- **适用**：只有当你打算做成"多人使用的在线服务"时才划算

### 路线 C：GitHub Actions 云打包（路线 A 的省力变体）⭐ 推荐

- **做法**：写一个 workflow，用 GitHub 免费的 `macos-14`（Apple Silicon）runner 自动打包；打 tag 时自动产出 Windows + macOS 两套包
- **优点**：**不需要自己有 Mac 机器**；可复现、可自动发版；GitHub 对公开仓库的 macOS runner 免费额度充足
- **缺点**：调试要"推代码 → 等 CI"，比本地慢；签名/公证仍需 Apple 开发者账号（未签名也能出包，用户手动放行）
- **结论**：**这是性价比最高的路**——代码改造（路线 A）+ CI 打包（路线 C）组合

---

## 六、投入产出汇总

| 项目 | 数值 |
|---|---|
| 需要改的代码行数 | 估计 **150~250 行**（新增平台分支 + 路径/字体映射） |
| 无需改动的代码行数 | 约 **8700 行（97%）** |
| 代码改造工时 | 1~2 天 |
| 打包 + 签名调试（首次） | 1~2 天（大部分时间花在签名/隔离属性排查） |
| 一次性费用 | 0 元（自己用 / 用户手动放行）或 **99 美元/年**（Apple 开发者，双击即用） |
| 发布包体积 | 单平台约 **350~400MB**（Chromium 内核是硬开销） |
| 长期维护成本 | 每次发版多一条 CI 流水线；建议顺带把自动更新改成按平台分派附件 |

---

## 七、如果要动手，建议的顺序

1. **先做平台抽象层**（半天）：新建 `app/platform_utils.py`，集中收敛"数据目录 / 系统字体 / 打开文件 / 无边框窗口 / UA / Playwright 内核路径"这 6 项，全部按 `sys.platform` 分支。这一步做完，Mac 适配就只是在**一个文件里加分支**，而不是散落各处。
2. **改 4 个 P0 项**：数据目录（最关键，涉及数据安全）、build.py 平台分支。
3. **在 Mac 上跑通源码态**：`python main.py`，逐个验证 8 个页面 + 采集流程（此时不需要打包，最快暴露 Tk 的观感问题）。
4. **打 .app 并本地验证**：确认 Playwright 内核路径正确、Toast/对话框行为正常。
5. **补 CI**：GitHub Actions 双平台构建，让发版自动化。
6. **最后处理签名/公证**：这一步只有在"要给陌生人用"时才必要。

---

## 八、一句话回答

> **可以做，而且是这个项目里性价比很高的一次扩展**——95% 以上的代码（包括整个采集引擎、数据层、业务逻辑）不需要改动，customtkinter + Playwright 本身都是跨平台的。
>
> 真正的门槛不在"转码"，而在三件事：**① 必须有一台 Mac（或在 GitHub Actions 上用免费的 macOS 机器）；② 打包配置要写平台分支；③ 要让别人双击即用，得买 Apple 开发者账号做签名公证（99 美元/年），否则用户需要手动放行一次。**
>
> 如果只是你自己在 Mac 上用，或者给能接受"右键打开"的人用，**零费用、1~2 天代码改造即可完成**。

---

## 九、「改好代码 → 压缩成包 → Mac 解压就能用」吗？

**不能——这个顺序把最关键的一步漏掉了。正确的顺序是：**

```
在 Windows 上改代码  →  【在 Mac 上打包】  →  在 Mac 上用 ditto 压缩  →  Mac 解压即用
                            ↑
                    这一步无法在 Windows 上完成
```

### 9.1 关卡 1：打包机（硬性，无解）

- PyInstaller **不支持交叉编译**：在 Windows 上执行打包，产物只能是 Windows 可执行文件。
- 所以"在 Windows 上改好、压缩成 zip、拿到 Mac 解压"——**解压出来的东西在 Mac 上根本执行不了**，因为它就是 `.exe`。
- 这不是配置问题，是原理问题。必须在 macOS 上执行打包（本机 Mac 或云上的 Mac runner）。

### 9.2 关卡 2：压缩方式（最容易踩，且后果是"包坏了"）

macOS 的 `.app` 其实是一个**目录**，内部依赖两样 Windows 压缩工具会破坏的东西：

| 会被破坏的东西 | 后果 |
|---|---|
| **Unix 执行权限位**（`Contents/MacOS/xxx` 的 755） | 解压后变成普通文件 → 提示「应用程序不能打开」 |
| **符号链接**（Python/框架内部大量使用） | 被展开成文件副本 → 体积膨胀、部分依赖找不到 |

**正确做法**（必须在 Mac 上执行）：

```bash
# 推荐：ditto 是 macOS 官方为 app 打包设计的命令，完整保留权限、符号链接与扩展属性
ditto -c -k --sequesterRsrc --keepParent TikTokLinkCollector.app TikTokLinkCollector_mac.zip

# 或者用 zip 时务必带 -y（保留符号链接）
zip -r -y TikTokLinkCollector_mac.zip TikTokLinkCollector.app
```

> ⚠️ **不要用 Windows 的 WinRAR / 7-Zip / 资源管理器"发送到压缩文件夹"来打这个包** —— 就会命中上表两个问题。

### 9.3 关卡 3：传输方式（决定用户要不要多点一下）

macOS 会给"从互联网下载"的文件打上 `com.apple.quarantine` 隔离标记，Gatekeeper 看到它 + 程序未签名就会拦下。

| 传输方式 | 是否带隔离标记 | 用户拿到后 |
|---|---|---|
| U 盘 / 移动硬盘拷贝 | ❌ 不带 | **双击即用** |
| AirDrop（本机→本机） | ❌ 不带 | **双击即用** |
| 浏览器下载（**GitHub Release 也算**） | ✅ 带 | 需**右键 → 打开**一次，或执行 `xattr -rd com.apple.quarantine <路径>` |

右键打开只需做**一次**，之后 macOS 会把它加入允许列表，以后双击正常。

### 9.4 附加门槛：架构必须匹配

Mac 分两种芯片，产物不通用：

| 芯片 | 需要的产物 | 说明 |
|---|---|---|
| Apple Silicon（M 系列） | **arm64** | GitHub Actions 的 `macos-14` runner 就是 arm64 |
| Intel | **x86_64** | 用 `macos-13` runner |

如果给 M 系列 Mac 发 x86_64 包，会看到「应用程序已损坏」这类误导性报错（实际是架构不符）。

### 9.5 还要注意：源码包同样"解压不能直接用"

和 Windows 版现在的处境一样：从 GitHub 下载的源码 zip（约 1MB）在 Mac 上解压后**也没有用**，用户还需要：

1. 装 Python 3.11+，**且必须是带 tkinter 的版本**（Homebrew 的 `python` 默认不含 tkinter，需要额外装 `python-tk`，或改用 python.org 官方安装包）
2. `pip install -r requirements.txt`
3. `playwright install chromium`（下载约 150MB 内核）

这三步是"开发者流程"，不是"解压即用"。

### 9.6 所以，实际可行的只有两条路

| 路径 | 需要什么 | 用户拿到后 |
|---|---|---|
| **A. 你自己有 Mac** | 一台 Mac（改代码 + 打包都在上面做） | U 盘拷贝 → 双击即用；网盘/Release 下载 → 右键打开一次 |
| **B. 用 GitHub Actions 云打包** ⭐ | 不需要有 Mac；把代码推到 GitHub，加一个 workflow 文件 | 同上（走下载必然带隔离标记，需右键打开一次） |

**两条路的共同点**：最终都必须由一台 **macOS 机器**产出 `.app` 包；Windows 上只能完成"改代码"这一步，打包一定做不了。

### 9.7 想做到"陌生人下载双击即用"

那需要在上面基础上再加一步：**Developer ID 签名 + Apple 公证（notarization）**，需要 Apple Developer Program 账号（99 美元/年）。做完之后隔离标记虽然还在，但 Gatekeeper 校验能通过，用户双击直接打开。

**一句话总结**：改代码可以在这里做，但**打包必须在 Mac 上做**；在 Mac 上打好包之后，"解压即用"是成立的（U 盘传输连右键都不用点）。

---

## 十、有没有工具能在 Windows 上打包出 Mac 程序？

**没有。市面上不存在这样的工具，而且原因是原理性的，不是"工具还不成熟"。**

### 10.1 主流打包工具的实际跨平台能力

| 工具 | 能在 Windows 上跑 | 能产出 macOS 程序 | 说明 |
|---|---|---|---|
| **PyInstaller** | ✅ | ❌ | 官方 FAQ 明确：不是交叉编译器，只能在目标系统上构建 |
| **Nuitka** | ✅ | ❌ | 同上（它把 Python 编译成 C 再编译，仍需要目标平台的编译器和 SDK） |
| **cx_Freeze** | ✅ | ❌ | 同上 |
| **PyOxidizer** | ✅ | ❌ | 基于 Rust，同样需在 macOS 上构建 |
| **py2app** | ❌（仅 macOS） | ✅ | 本身就只能在 macOS 上运行 |
| **Briefcase (BeeWare)** | ✅ | ❌ | 支持多平台打包，但 macOS 产物仍需在 macOS 上构建 |
| **Wine** | ✅ | ❌ | ⚠️ 常见误解：Wine 的正向用途是"在 Linux/macOS 上产出 **Windows** 程序"，**不能反向产出 Mac 程序** |

### 10.2 为什么原理上做不到

打包一个 macOS 程序，需要凑齐四样 Windows 上**根本不存在**的东西：

1. **macOS 版 Python 运行时**（Mach-O 格式的可执行文件，不是 PE 格式）
2. **macOS 系统框架与动态库**（Cocoa、CoreFoundation 等，特别是 tkinter 需要 Tk 框架）
3. **macOS 版 Chromium 内核**（本项目必需；它是预编译的 Mach-O 二进制）
4. **macOS 的链接器与 SDK**（`ld`、`clang`、macOS SDK）—— 而且 **Apple 的许可协议不允许把 SDK 分发到非 Apple 硬件上**，所以业界也没有合法的现成交叉工具链

换句话说，所谓"跨平台打包"必须能在 Windows 上虚假地"变出"一整套 macOS 运行时环境。这是虚拟机才能做到的事。

### 10.3 能达到同样目的的五条路（按成本排序）

| # | 方案 | 成本 | 需要自己有 Mac？ | 说明 |
|---|---|---|---|---|
| 1 | **GitHub Actions 的 macOS runner** ⭐ | **0 元** | ❌ | **公开仓库完全免费**（含 macOS runner，无分钟数限制）。打 tag 即自动出 Windows + macOS 两套包 |
| 2 | **云 Mac 按小时租** | 约 **7~20 元/次** | ❌ | MacinCloud 约 $1/小时，打包一次租 1~2 小时足够；Scaleway 是按小时的 Apple Silicon |
| 3 | **借 / 买一台 Mac** | 0 ~ 数千元 | ✅ | 最直接，改代码 + 打包都在本机，调试最快 |
| 4 | **云 Mac 包月** | 约 $25~99/月 | ❌ | HostMyApple（支持支付宝）、MacStadium 等；仅当你要长期反复打包才划算 |
| 5 | Windows 上装 macOS 虚拟机 | 0 | ❌ | ⚠️ **违反 Apple 许可协议**（Apple 只允许在 Apple 硬件上虚拟化 macOS），且 x86 虚拟机性能差、现在很难装新版系统。**不推荐** |

> 参考价格（2026-09 检索）：MacinCloud 按小时约 $1.00；Scaleway Apple Silicon €0.22/小时（24 小时起）；AWS EC2 Mac $1.10/小时（24 小时最低）；HostMyApple 共享 Mac 约 $24.99/月起。
> GitHub Actions：公有仓库使用 GitHub 托管 runner **免费且不计分钟数**；私有仓库每月 2000 分钟额度（macOS runner 按 10 倍消耗计）。

### 10.4 如果暂时完全不碰 Mac：过渡方案

还有一个**零 Mac、零成本**的折中做法，适合"先让 Mac 用户能用起来"：

**做法**：发布一个源码包 + 一个 macOS 一键安装脚本（`.command` 文件）

```bash
#!/bin/bash
# 双击运行：自动装好环境并启动程序
cd "$(dirname "$0")"
# 1) 检查 Python（必须带 tkinter）
# 2) 建虚拟环境 + pip install -r requirements.txt
# 3) playwright install chromium
# 4) python main.py
```

- **优点**：完全不需要 Mac 打包机，Windows 上就能做出来
- **缺点**：首次运行要下载约 200MB（Python + 依赖 + Chromium），耗时几分钟；依赖用户网络能访问 PyPI 与 Playwright CDN；**且必须确认 Python 带 tkinter**（Homebrew 版默认不带，需提示用户装 `python-tk` 或改用 python.org 安装包）
- **定位**：这是"能跑起来"的最低成本方案，但体验不如 `.app`（不是双击即用，是双击后等几分钟）

### 10.5 结论

> **不存在"在 Windows 上打包出 Mac 程序"的软件** —— PyInstaller、Nuitka、cx_Freeze、PyOxidizer、Briefcase 全部需要目标平台。
>
> 但你不需要为此买 Mac：**这个仓库是公开仓库，用 GitHub Actions 的 macOS runner 打包完全免费**，打 tag 时自动出两套包。这是本项目的推荐路径。
>
> 如果连 CI 都不想折腾，**租一次云 Mac（约 10~20 元）打一个包**也能解决问题。
