# TikTok 页面结构探针报告（P4-P8 验证）

> 探针日期：2026-09-24 21:10~21:40
> 结论性质：基于真实 Playwright 访问 + 原始证据落盘，非 Mock、非推测
> 隐私说明：报告中账号已脱敏（demo_alpha / demo_beta / demo_gamma）；
> `diagnostics/` 下的原始证据含真实账号数据，**不入 Git 仓库**（见 .gitignore）。

---

## 一、测试账号与结果总览

| 账号 | 作品总数 | 今日(09-24) | 昨日(09-23) | 最新作品时间 | 绝对时间可确认 |
| ---- | -------- | ----------- | ----------- | ------------ | -------------- |
| @demo_alpha | 16 | **4 条** | 2 条 | 09-24 18:46:38 | ✅ 全部 |
| @demo_beta | 16 | **4 条** | 3 条 | 09-24 18:48:27 | ✅ 全部 |
| @demo_gamma | 15 | **0 条** | 0 条 | 09-10 20:43:06 | ✅ 全部 |

三个账号恰好覆盖验收三大场景：今日 4 条（demo_alpha/demo_beta）、今日 0 条（demo_gamma，该账号最近发布是 09-10）。

---

## 二、核心结论（最重要）

**真实 TikTok 页面可以可靠拿到作品的绝对发布时间。**

绝对发布时间字段：**`item.createTime`**，位于作品列表 API `/api/post/item_list/` 的 `itemList[]` 数组内，是 **Unix 秒级时间戳**，可直接转换为 `YYYY-MM-DD HH:mm:ss`。

示例（@demo_alpha，北京时间 +08:00；video_id 已做泛化处理）：
```
id=7689051423832575001  createTime=1790246798  →  2026-09-24 18:46:38
id=7689037154575568002  createTime=1790243475  →  2026-09-24 17:51:15
id=7689003105328975003  createTime=1790235552  →  2026-09-24 15:39:12
id=7688960000504368004  createTime=1790225513  →  2026-09-24 12:51:53
id=7688685565037890005  createTime=1790161614  →  2026-09-23 19:06:54   ← 昨日，不得补入
```

---

## 三、页面结构（实际发现，非预设）

### 3.1 初始 SSR（`__UNIVERSAL_DATA_FOR_REHYDRATION__`）
- 位于 `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">`
- 顶层键：`{"__DEFAULT_SCOPE__": {...}}`
- 内含账号信息 `webapp.user-detail.userInfo.user`：
  - `user.createTime` = **账号注册时间**（不是作品发布时间！）
  - `user.uniqueId` = 用户名
  - `user.nickName`、`user.signature` 等
- **关键坑**：`userInfo.itemList` 是**空数组** `[]`，SSR 阶段**不含作品列表数据**。

### 3.2 作品列表（XHR 异步）
- 接口：`GET https://www.tiktok.com/api/post/item_list/?aid=1988&...&secUid=...&cursor=...`
- 响应顶层键：`cursor / hasMore / itemList / statusCode / status_msg`
- `itemList[]` 每个元素 = 一个作品对象，含：
  - `id`（19 位数字 = video_id，全局唯一）
  - `createTime`（Unix 秒 = **绝对发布时间**）
  - `desc`（文案）、`author.uniqueId`（作者）、`video`、`stats` 等

### 3.3 作品 DOM 链接
- 主页作品卡片链接：`a[href*="/video/"]` → `https://www.tiktok.com/@user/video/{id}`
- 与 `itemList[].id` 完全对应。

### 3.4 详情页（回退源）
- 详情页 `__UNIVERSAL_DATA_FOR_REHYDRATION__` 里同样包含作品对象，**也有 `createTime`**，值与主页一致（验证：主页 1790246798 == 详情页 1790246798）。
- 因此详情页可作为主页相对时间缺失时的**二级回退源**。

---

## 四、时间解析策略（推荐）

| 级别 | 来源 | 字段 | 判定 |
| ---- | ---- | ---- | ---- |
| **一级（首选）** | `/api/post/item_list/` XHR 响应 | `itemList[].createTime`（Unix 秒） | CONFIRMED |
| **二级（回退）** | 详情页 `__UNIVERSAL_DATA_FOR_REHYDRATION__` | 作品对象 `createTime` | CONFIRMED |
| 三级（不推荐） | DOM 相对时间文本 "2h ago"/"Yesterday" | — | RELATIVE_ONLY，禁用 |

**规则落地**：
- `createTime` 存在 → CONFIRMED，转目标时区后比较日期。
- 只有相对时间文本 → RELATIVE_ONLY，**禁止默认今天**。
- 两者皆无 → UNCONFIRMED，标记异常待人工确认。

---

## 五、已知风险

1. **无头模式限流**：连续无头（headless）访问会触发 TikTok 风控，`post/item_list` 返回空（`statusCode` 非 0）。→ **正式采集器必须用有头模式 + 合理账号间隔**。
2. **相对时间不可靠**：主页 DOM 有 "2h ago" 类文本，跨日时易误判，禁止作为日期依据。
3. **`createTime` 语义陷阱**：SSR 里的 `user.createTime` 是账号注册时间，切不可误当作品时间；作品时间只在 `itemList[].createTime`。
4. **地区/风控**：本次走用户真实代理 11304 成功，若换环境可能触发地区限制或 CAPTCHA（本次无头连续访问曾短暂触发，有头+冷却后恢复）。

---

## 六、对正式实现的影响

- `VideoParser` 实现 = 监听 `post/item_list` 响应 + 解析 `itemList[].createTime/id/desc`。
- `PublishTimeResolver` = `createTime` Unix 秒 → 目标时区 → 日期比对（复用已实现的 `DateResolver`）。
- `ProfileCollector` = 有头 Playwright + 持久化 Session + 滚动触发 item_list + 捕获响应。
- **无需依赖 DOM 相对时间、无需详情页（除非 item_list 拿不到才回退）。**

## 七、证据文件（本地留档，不入仓库）

> ⚠️ 原始证据（API 完整响应、页面快照）含真实账号的用户名、secUid 等数据，
> 整个 `diagnostics/` 目录已加入 `.gitignore`，**不上传 GitHub**。
> 本地文件名保留真实账号名以便溯源，此处以脱敏名指代：

- `diagnostics/raw/<账号>_api_post_item_list.json`（约 364KB 完整响应，每个账号一份）
- `diagnostics/item_list_evidence.json`（结构化汇总）
- `diagnostics/html/*.html`（页面快照，含详情页）
- `diagnostics/probe.py`（探针脚本；账号通过命令行参数显式传入，脚本不内置任何账号）
