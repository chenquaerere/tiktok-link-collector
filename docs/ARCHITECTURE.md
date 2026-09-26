# TikTok Link Collector —— 架构设计文档

> TikTok作品链接采集器 | 全栈架构分析 v1.1.0

---

## 1. 项目定位

批量管理**本人 TikTok 账号**的作品链接采集工具。核心诉求：多账号 → 批量访问主页 → **抓取每个账号最新 N 条作品** → 获取作品链接 → 按账号数量限制采集 → 自动去重 → 历史记录 → 一键复制 → 导出 TXT/CSV/XLSX。

**关键边界：这是"链接采集工具"，不是"视频下载工具"。** 只获取作品页面 URL，不下载视频文件。

---

## 2. 技术栈选型（决策 + 理由 + 备选）

| 维度 | 选择 | 理由 | 备选（不采用原因） |
| ---- | ---- | ---- | ---- |
| 语言 | Python 3.13 | 生态成熟、开发快 | — |
| 浏览器自动化 | **Playwright**（Python） | 支持持久化 context（`user_data_dir`），可保存登录 Session/Cookie，符合 §8 要求；对 TikTok 动态页面稳定 | Selenium（Session 持久化弱、维护差） |
| 桌面 UI | **customtkinter** | 深色主题、卡片/导航/Badge 均可实现；轻量；PyInstaller 打包体积小；与用户既有工具（去水印）技术栈一致 | PySide6（更精美但打包体积 100MB+、学习成本高） |
| 数据库 | **SQLite**（stdlib `sqlite3`） | 零依赖、单文件、WAL 模式、符合 §26 | SQLAlchemy（过度设计，本项目无需 ORM） |
| 时区 | **zoneinfo + tzdata** | 标准库，IANA 时区，正确处理夏令时/跨日；Windows 需显式依赖 `tzdata` | pytz（官方已建议迁移到 zoneinfo） |
| 导出 | openpyxl（XLSX）+ stdlib csv/txt | XLSX 是硬需求 | — |
| 测试 | unittest（stdlib）+ 可选 pytest | 核心零依赖即可运行 | — |
| 打包 | PyInstaller | 单文件 EXE / 目录版，符合 §30 | — |

**核心依赖只有 4 个：** `playwright`、`customtkinter`、`openpyxl`、`tzdata`（+ 构建期 `pyinstaller`）。

---

## 3. 项目结构（按功能组织 + 分层）

```
TikTokLinkCollector/
├── main.py                     # 入口
├── requirements.txt
├── .env.example
├── app/
│   ├── constants.py            # 常量
│   ├── config.py               # 配置（JSON + settings 表双向同步）
│   ├── core/                   # 纯逻辑核心（不依赖 UI/浏览器/网络）
│   │   ├── models.py           # dataclass 模型 + 状态枚举
│   │   ├── date_resolver.py    # ★ DateResolver/DateValidator 日期解析
│   │   ├── url_normalizer.py   # ★ URL 标准化（video_id 唯一键）
│   │   ├── dedup.py            # ★ 去重
│   │   └── collect_logic.py    # ★ 采集规则（宁可少采不可错采）
│   ├── db/
│   │   └── database.py         # SQLite：8 表 + 索引 + settings
│   ├── collector/              # 采集引擎
│   │   ├── browser.py          # Playwright 生命周期（headless=new + 线程守卫）
│   │   ├── session.py          # 持久化登录态
│   │   ├── provider.py         # TikTok 主页访问（item_list XHR）
│   │   ├── video_parser.py     # 作品解析（itemList[].createTime/id）
│   │   ├── publish_time_resolver.py # 发布时间解析
│   │   ├── profile_collector.py     # 主页采集（实现 Fetcher 协议）
│   │   ├── task_runner.py      # 任务调度：重试/停止/单账号隔离
│   │   └── engine.py           # 完整采集引擎编排（最新 N 条 + 替换式记录）
│   ├── chat/                   # ★ 聊天链接采集（v1.1.0 新增，与作品采集完全隔离）
│   │   ├── models.py           # 目标/候选/链接/结果 数据模型
│   │   ├── provider.py         # 消息页访问（会话列表/好友API/面板卡片/itemDetail）
│   │   ├── resolver.py         # 目标校验（聊天头部比对）
│   │   ├── collector.py        # 采集编排（进对话框→校验→取卡片→解析→滚动）
│   │   ├── search.py           # 本地候选检索
│   │   └── store.py            # 聊天目标/链接 持久化
│   ├── services/               # 账号/结果服务 + chat_service（聊天采集编排）
│   └── ui/                     # customtkinter 界面（8 页面 + 链接窗口）
├── mocks/
│   └── mock_provider.py        # ★ Mock 数据源（A/B/C/D/E 场景）
├── diagnostics/                # 站点探针 + 真实采集验证 + UI 体检脚本
├── tests/                      # ★ 自动化测试（189 用例）
└── docs/ARCHITECTURE.md
```

**分层原则**（对齐全栈专家规范）：`core` 层为纯函数、无副作用、可独立测试；`collector` 层负责编排与浏览器 I/O；`db` 层负责持久化；`ui` 层只做展示与交互。**采集源通过 fetcher 依赖注入**，真实 Playwright 与 Mock 可无缝切换。

---

## 4. 最核心业务规则（已实现 + 已测试）

> ⚠️ **2026-09-25 规则变更**：采集语义已从「按日期严格过滤」改为「**抓取账号最新 N 条作品，不过滤日期**」。原「宁可少采不可错采」的日期过滤规则已废弃，下方为**当前生效**规则。

### 规则 1：最新 N 条（不过滤日期）
- 直接按主页时间倒序取账号最新的 `target_count` 条作品，**不管是今天、昨天还是更早**。
- 发布时间（`itemList[].createTime`）**尽力解析并记录**，无法确认的照常采集（`publish_date` 记空）。
- 「记录日期」仅作为本次任务/链接日志的归档标签，**不再用于过滤**。

### 规则 2：数量限制
- 达到每账号目标数量立即停止该账号；作品不足时状态 `partial`，无作品状态 `empty`。

### 规则 3：去重
- 唯一键 `video_id`（非完整 URL）。内存去重 + 数据库 `UNIQUE(video_id)` 双保险。

### 规则 4：替换式记录（2026-09-25 新增）
- 新任务开始时删除本次账号的历史作品记录；每日链接日志同日文件按「最后一次运行」整体替换。
- 多次采集（含同日多次测试）一律以最后一次结果为准。

---

## 5. 数据模型（SQLite，8 表）

| 表 | 用途 | 关键索引 |
| ---- | ---- | ---- |
| accounts | 账号（username/profile_url/enabled/login_status/collect_count…） | account_id 唯一 |
| videos | 作品（video_id/account_id/publish_date/publish_time/task_id…） | **video_id 唯一**、account_id、publish_date、task_id |
| collect_tasks | 任务（task_id/target_date/数量统计/状态…） | task_id 唯一 |
| task_accounts | 任务×账号明细（target/actual/status/error_reason） | task_id+account_id 唯一 |
| collect_logs | 采集日志（task_id/account_id/level/message） | task_id |
| settings | 键值设置 | key 主键 |
| chat_targets | 聊天采集「最近使用」目标（stable_key/类型/名称/handle/uid/conversation_id/last_used_at） | stable_key 主键 |
| chat_links | 聊天采集到的链接（stable_key/video_id/video_url/order_num/collected_at） | stable_key |

---

## 6. 高风险点与应对（§37 明确要求优先保障）

| 风险 | 应对策略 |
| ---- | ---- |
| TikTok 页面结构变化 | video_parser 独立封装，选择器集中定义；解析失败走重试+标记失败，不猜测 |
| 作品发布时间 | 优先结构化数据/详情页绝对时间；相对时间一律降级为"无法确认"，需人工确认 |
| 登录/Session 失效 | Playwright 持久化 context 保存登录态；检测到 CAPTCHA/重登 → 暂停该账号提示人工处理，**不阻断整体任务** |
| 跨日误判 | 所有时间统一转换到任务指定时区再做日期比较；`tzdata` 保证夏令时正确 |
| 多账号批量稳定性 | 单账号失败隔离 + 自动重试（默认 3 次）+ 停止不丢已采数据 |
| 网络环境 | **不写死任何代理**；用户自备网络；预留可选 HTTP/HTTPS/SOCKS5 代理配置（默认关闭） |

---

## 7. 开发路线图（P0–P35）与当前状态

> 状态图例：✅ 已完成（代码+测试）｜🔵 部分完成｜⬜ 计划中/待做
> 更新日期：2026-09-25（以实际代码与测试为准，勿以本表为唯一依据）

| 阶段 | 内容 | 状态 |
| ---- | ---- | ---- |
| P0 | 项目架构设计 | ✅ 本文档 |
| P1 | 基础桌面 UI | ✅ customtkinter 深色主题 + 左侧导航 + 7 页面 |
| P2 | SQLite 数据库 | ✅ 6 表 + WAL + 外键 + 事务 |
| P3 | 账号管理 | ✅ accounts_page + account_service（导入/启停/删除/批量数量） |
| P4 | 浏览器 Session 管理 | ✅ BrowserManager（headless=new 后台采集 + 线程守卫）+ SessionManager |
| P5 | TikTok 主页访问 | ✅ TikTokProvider（item_list XHR） |
| P6 | 作品列表读取 | ✅ VideoParser（itemList[].createTime/id） |
| P7 | 作品 URL 解析 | ✅ url_normalizer |
| P8 | 发布时间解析 | ✅ PublishTimeResolver + DateResolver |
| P9 | 日期验证系统 | ✅（⚠️ 2026-09-25 规则变更：改为「最新N条不过滤日期」，日期仅尽力记录） |
| P10 | 单账号采集 | ✅ collect_logic + ProfileCollector |
| P11 | 数量限制 | ✅ 每账号独立数量 |
| P12 | 多账号任务 | ✅ TaskRunner + CollectEngine（严格串行） |
| P13 | 去重系统 | ✅ video_id 唯一 + 内存去重 + DB UNIQUE |
| P14 | 任务进度 | ✅ 进度条 + on_progress 实时回调 |
| P15 | 暂停/继续/停止 | ✅ 全部实现 + 断点续传 |
| P16 | 失败重试 | ✅ 默认 3 次 + 单账号隔离 |
| P17 | 结果页面 | ✅ results_page + 内嵌链接文本区 |
| P18 | 复制系统 | ✅ to_url_text/to_grouped_text + 链接窗口（框选复制） |
| P19 | TXT/CSV/XLSX 导出 | ✅ ExportService |
| P20 | 历史任务 | ✅ history_page（任务列表 + 明细 + 导出） |
| P21 | 诊断系统 | ✅ 诊断字段 + collect_logs |
| P22 | 日志系统 | ✅ logger + logs_page + 每日链接日志（替换式） |
| P23 | Mock 测试 | ✅ mock_provider（A/B/C/D/E 场景） |
| P24 | 自动化测试 | ✅ 135 用例全通过 |
| P25 | UI 美化 | ✅ 深色主题 + 产品化升级（P30–P35 已落地） |
| P26 | 完整回归测试 | ✅ 135 全过（2026-09-25） |
| P27 | Windows 打包 | ✅ PyInstaller onedir + Chromium 内核随包 |
| P28 | 便携版 | ✅ 843MB 零依赖便携包 |
| P29 | 最终验收 | ✅ 三账号真实采集跑通 + UI/UX 产品化验收完成 |
| P30 | UI/UX 全面审计与改造方案 | ✅ 审计+方案产出 |
| P31 | Design System 建立 | ✅ tokens/字体/间距圆角/components 包 |
| P32 | 页面产品化重构 | ✅ 导航图标/仪表盘去重卡片/账号搜索/结果筛选/URL缩略 |
| P33 | 交互系统 | ✅ Toast/Dialog/EmptyState/LoadingState/错误统一 |
| P34 | 高DPI/响应式/性能 | ✅ 900×600 + 高DPI + 导出/日志后台线程 |
| P35 | 最终视觉验收 + 回归 + 发布 | ✅ 135 回归 + 重打包 + 增量部署 |
| P36 | **聊天链接采集模块**（独立板块） | ✅ 探针（docs/CHAT_PROBE_REPORT.md）+ `app/chat/` 七件套 + UI 页 + 21 用例；全量 166 测试通过 |
| P37 | 聊天取链根因修复（作用域 + React props + itemDetail） | ✅ 作用域限定 `DivChatBox`；从 `__reactProps$*` 取作品 ID；详情接口取作者；顺序改垂直位置（下=最新）；详见 docs/CHAT_MODULE.md |
| P38 | 聊天页交互修复（整行可点 / 去模态确认 / 真实停止） | ✅ 整行点选 + 双击直采 + 选中高亮；清空改内联二次确认；Stop 用 `threading.Event` 真停；进度条实时推进 |
| P39 | 跨线程 UI 更新统一收口 | ✅ `AppWindow.ui_call()` + 主线程泵；迁移 collect/logs/results/app_window 共 9 处；聊天页独立事件队列 |
| P40 | 性能优化与细节打磨 | ✅ 批量并发解析 + 去掉探测页 + 条件等待（采集 23.9s→20.2s）；记住数量 / 导出 / 复制一行一条 / 头部间距统一 / 空容器体检 |

---

## 8. 下一步（已全部完成 → v1.0.0）

1. ✅ ~~核心采集~~（P4–P24 已全部完成并真实验证）。
2. ✅ ~~UI/UX 全面产品化升级~~（P30–P35 已全部落地：Design System → 页面重构 → 交互系统 → 高DPI/性能 → 最终验收）。
3. ✅ ~~最终回归 + 打包发布~~（135 测试 + 真实采集 smoke test + 重新打包便携版 + 增量部署）。

**当前版本：v1.1.0**（2026-09-26）。

- v1.0.0：首个正式版（P0–P35，135 测试）。
- v1.1.0：新增聊天链接采集（P36–P40）+ 界面假死类缺陷修复 + 性能优化，189 测试全绿；已发布 GitHub `v1.1.0`。

后续可选：账号分组/排序、聊天多会话批量采集、结果合并导出。

---

## 9. UI/UX 产品化改造计划（P30–P35，2026-09-25 审计产出）

> 详见 `docs/PROJECT_STATUS.md`（权威状态快照）与当轮交付的《UI/UX 审计报告》。

**阶段拆分（每阶段单独测试）：**
1. **P31 Design System**：补全 Design Tokens（Background/Text/Brand/Status/Border + 间距 4/8/12/16/20/24/32 + 圆角）；统一字体层级（App Title/Page Title/Section/Body/Secondary/Caption/Button/Table/Number）；抽取 Button/Card/PageHeader/StatCard/StatusBadge/Toast/Dialog/EmptyState/LoadingState/DataTable 到 `app/ui/components/`。
2. **P32 页面重构**：左侧导航（图标+高亮态）→ 仪表盘（当前任务实时区 + 修复重复统计卡片）→ 账号管理（搜索/筛选/全选列/分组/排序）→ 采集任务（任务执行态强反馈 + 账号间隔快捷设置）→ 采集结果（状态筛选 + URL 缩略/hover/点击复制）→ 历史/设置/日志。
3. **P33 交互系统**：全局 Toast 替代阻塞式 MessageBox；EmptyState / LoadingState / ErrorState；统一错误呈现（标题/账号/原因/建议 + 详情进日志）。
4. **P34 高DPI/响应式/性能**：调整 `minsize` 至 900×600 可用；Windows DPI 缩放适配；导出/日志读文件走后台线程。
5. **P35 最终验收**：新用户视角 10 秒走查 + 135 测试回归 + 真实三账号 smoke test + 重新打包便携版。
