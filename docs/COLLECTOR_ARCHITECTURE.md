# 真实采集引擎架构设计（P4–P8 前置设计）

> 本文件定义 Playwright 真实采集阶段的职责边界、数据流与接口骨架。
> **原则：先定职责，后写实现；页面结构变化时可局部替换，不重写整体。**

---

## 1. 组件职责划分

| 组件 | 文件 | 单一职责 | 依赖 |
| ---- | ---- | ---- | ---- |
| `BrowserManager` | `collector/browser.py` | Playwright 浏览器/进程生命周期（启动、关闭、context 管理） | playwright |
| `SessionManager` | `collector/session.py` | 持久化登录态（user_data_dir / cookie）、登录状态检测 | BrowserManager |
| `TikTokProvider` | `collector/provider.py` | TikTok 站点访问（加载主页、等待稳定、返回可解析的 page） | BrowserManager |
| `ProfileCollector` | `collector/profile_collector.py` | 账号主页作品采集，**实现 TaskRunner 的 Fetcher 协议** | TikTokProvider / SessionManager / VideoParser / PublishTimeResolver |
| `VideoParser` | `collector/video_parser.py` | 从页面 DOM / 结构化数据解析作品 URL + video_id + 原始时间 | — |
| `PublishTimeResolver` | `collector/publish_time_resolver.py` | 页面发布时间解析；相对时间时**回退到作品详情页**取绝对时间 | core.DateResolver |

**与现有层的衔接**：
- `core.date_resolver.DateResolver` 是**纯解析**（原始时间字符串/epoch → DateResolution），不碰页面。
- `collector.PublishTimeResolver` 是**页面采集**（从 DOM/详情页取原始时间），最终委托给 core.DateResolver 做可信度分级。
- `core.collect_logic.collect_for_account` 是**纯业务规则**（日期匹配/去重/数量限制），不碰网络。
- `collector.TaskRunner` 是**编排**（多账号串行、重试、停止），采集源通过 `Fetcher` 注入。

---

## 2. 数据流

```
UI / 任务触发
  └─> CollectEngine（编排，P10–P16 接入）
        └─> 对每个 Account：
              ├─> SessionManager.ensure_login(account)
              │     └─ 失效/CAPTCHA → 抛 LoginRequired → TaskRunner 标记失败，不阻断整体
              ├─> ProfileCollector.fetch(account)        # 实现 Fetcher(Account)->List[ParsedVideoItem]
              │     ├─> BrowserManager.new_context(user_data_dir)
              │     ├─> TikTokProvider.load_profile(username)   # 加载主页 + 等待稳定
              │     ├─> VideoParser.parse_videos(page)          # 解析 URL/video_id/原始时间
              │     └─> 对只有相对时间的作品：
              │           └─> PublishTimeResolver.resolve_absolute(item)  # 详情页取绝对时间
              └─> TaskRunner.run(...) → collect_for_account(...)  # core 纯逻辑：日期/去重/数量
                    └─> 结果入库（事务）+ collect_logs（重复发现记录）
```

---

## 3. 关键契约

### 3.1 ProfileCollector 必须满足 Fetcher 协议
```python
Fetcher = Callable[[Account], List[ParsedVideoItem]]
```
因此真实采集与 Mock 采集**零成本切换**：TaskRunner 只依赖这个函数签名。

### 3.2 登录失效契约
- 检测到 CAPTCHA / 重新登录 / 访问限制时，`SessionManager.ensure_login` 抛 `LoginRequired`。
- TaskRunner 捕获后标记该账号 `failed`，**继续下一账号**。
- 用户人工完成验证后，任务可恢复（`task_accounts` 记录未完成账号）。

### 3.3 发布时间契约（§17 最高优先级：日期准确）
1. 主页列表能拿到**绝对时间**（结构化数据/meta）→ 直接用。
2. 主页只能拿到**相对时间** → `PublishTimeResolver` 打开作品详情页取绝对时间。
3. 详情页仍取不到 → `UNCONFIRMED`，**绝不猜测**，进入"无法确认"待处理态。

---

## 4. 反爬与安全边界（§18）

**不实现**：CAPTCHA 绕过、安全验证绕过、账号安全机制绕过。
**行为**：遇到人工验证 → 暂停当前账号 → 用户处理完 → 继续任务。

---

## 5. 后续实现要点（P4–P8 逐项落地时再展开）

- P4：BrowserManager 用 Playwright `launch_persistent_context(user_data_dir=...)` 持久化登录态；headless/headed 可配；页面加载超时走 settings。
- P5：TikTokProvider 封装主页 URL 构造（`https://www.tiktok.com/@username`）+ 等待作品列表 DOM 稳定。
- P6：VideoParser 优先解析页面内 `__UNIVERSAL_DATA_FOR_REHYDRATION__` / `SIGI_STATE` 等结构化数据；选择器集中定义，结构变化只改这里。
- P8：PublishTimeResolver 主页相对时间 → 详情页 `createTime` 字段；所有时间统一到任务时区。
