# TikTok 聊天/私信页结构探针报告（聊天链接采集模块前置验证）

> ⚠️ **修订说明（2026-09-26 晚，重要）**：本报告 §一 表格与 §七 中关于
> 「共享视频是 `<a href="/@user/video/ID">`，可直接抽取」的结论**已被后续探针推翻**。
> 实测结论：**聊天面板 `DivChatBox` 内不存在任何 `a[href*="/video/"]`**；
> 其内部 16 个 `/video/` 链接全部位于左侧会话列表预览与页头区域且为隐藏元素
> （`vis=false, rect=[0,0,0,0]`）。分享视频实为缩略图卡片，作品 ID 只能从
> React props（`__reactProps$* → children.props.itemId`）读取，作者需再调
> `/api/im/item_detail/?itemId=` 获取。
> **以 `docs/CHAT_MODULE.md` 为准**，本报告其余结构结论（登录态、会话列表、
> `data-conversation-id`、好友 API、群号不可搜）仍然有效。

> 探针日期：2026-09-26 11:21~11:37
> 结论性质：基于真实 Playwright 访问（有窗口人工登录 + 无头复用登录态）+ 证据落盘，非 Mock、非推测
> 隐私说明：探针使用的登录账号由用户当场登录提供；`diagnostics/chat_evidence/` 原始证据含真实聊天数据，**不入 Git**（.gitignore 已覆盖 `diagnostics/`）。

---

## 一、总体结论

**TikTok Web 存在完整的聊天/私信功能，好友与群聊都能在网页端访问，且会话列表在 DOM 里暴露了稳定唯一标识 `data-conversation-id`。** 聊天模块可基于「HTTP 好友列表 API + DOM 会话列表 + DOM 视频链接抽取」实现，**无需解析二进制 WebSocket 协议**。

关键结论速览：

| 能力 | 结论 | 证据 |
| ---- | ---- | ---- |
| 消息页入口 | `https://www.tiktok.com/messages`，**未登录立即跳转登录页** | messages.html / final_url |
| 会话列表 | DOM 渲染，元素 `[data-e2e="dm-new-conversation-item"]`，含 **`data-conversation-id`** 稳定唯一标识 | v4_conversations.json（31 条） |
| 好友列表 | HTTP `GET /api/im/spotlight/relation/` → `followings[]`（uid/sec_uid/unique_id/nickname/can_share_message） | 90 条好友 |
| 群聊 | 会话列表内联出现（如「<群名> / 9 members」），会话 ID 为**纯数字** | v5 group 视图 |
| 视频链接 | 会话内共享视频是 `<a href="/@user/video/ID">`，可直接抽取（实测一次 16 条） | v3/v5 video_links |
| 目标验证锚点 | 打开会话后聊天头部 `[class*="DivChatHeader"]` 显示「名称 + @用户名」（好友）或「名称 + N members」（群聊） | v5 headers |
| 会话数据通道 | 会话列表/消息实时数据走 `wss://im-ws-sg.tiktok.com/ws/v2`（二进制 protobuf/bsync），**但无需解析**——渲染结果就在 DOM | v2 ws_log |

---

## 二、登录态

- 消息页强制登录；未登录访问 `/messages` 302 → `/login?lang=en&redirect_url=.../messages`。
- 登录后 Cookie 含 `sessionid / sid_tt / sid_ucp_v1 / uid_tt` 等，持久化到 Playwright user_data_dir。
- 复用项目现有 `BrowserManager`（headless=new）+ `SessionManager` 即可；未登录时沿用项目「有窗口手动登录一次」流程。

## 三、会话列表结构（最重要）

`DivConversationListContainer` 内每个会话项：

```html
<div data-index="0"
     data-conversation-id="0:1:<peerUid>:<selfUid>"
     data-conv-id="0:1:<peerUid>:<selfUid>"
     data-e2e="dm-new-conversation-item"
     aria-selected="false" tabindex="0">
  ...（名称 + 最后一条消息摘要 + 时间）
</div>
```

**会话唯一标识 `data-conversation-id` 有两种格式**（关键分类依据）：

| 格式 | 含义 | 示例 |
| ---- | ---- | ---- |
| `0:1:<peerUid>:<selfUid>` | **好友单聊（DM）**，内嵌双方数字 user_id | `0:1:<peerUid>:<selfUid>`（某好友） |
| 纯数字 ID | **群聊**（群 ID 即 conversation_id） | `<群ID>`（群「某群聊」） |

实测 31 个会话：26 个 DM（`0:1:` 格式）+ 4 个群聊（纯数字）+ 1 个「消息请求」入口。

## 四、好友列表 API

`GET https://www.tiktok.com/api/im/spotlight/relation/`（参数含 aid=1988、scene 等，登录态自携带）→ 响应 `followings[]`，每项字段：

- `uid`（数字用户 ID）、`sec_uid`（稳定加密 ID）、`unique_id`（@用户名）、`nickname`（昵称）
- `can_share_message`（是否可发私信）、`follow_status`、`follower_status`、`remark_name`
- 顶层另有 `has_more / max_time / min_time / next_req_count`（分页）

**用途**：好友目标选择的权威数据源，天然支持「按名称/用户名精确或模糊匹配 + 同名展示多个让用户选」，且每个好友都有 `uid/sec_uid` 唯一标识。

## 五、聊天视图（点开会话后）

- 打开方式：点击 `[data-conversation-id="X"]`（SPA，**URL 不变**，仍是 `/messages`，无法通过 URL 深链，必须点击元素）。
- 聊天头部 `[class*="DivChatHeader"]`：
  - 好友：`<昵称> / @<用户名>`（昵称 + @用户名）
  - 群聊：`<群名> / 9 members`（群名 + 成员数）
- 消息里的共享视频：`<a href="/@user/video/{id}">`，`/api/im/item_detail/` 会补充视频详情（可选，非必需）。
- **目标验证**：打开会话后读取 `DivChatHeader` 文本，与用户选择的目标名称比对，不一致即停止（满足「采集时再次验证目标」）。

## 六、群号 / 搜索能力（如实结论，不夸大）

- **好友搜索框**：消息页内 `input[data-e2e="search-user-input"]` 存在但默认隐藏（需点「新建聊天」按钮才展开），直接驱动 UI 搜索不可靠。
- **群号搜索**：**TikTok Web 不提供「按群号搜索」**。群聊只能通过在会话列表里**按群名称匹配**定位；群 ID（= 纯数字 conversation_id）在找到群聊后即可拿到，但不能反向由群号检索。
- **落地策略**：
  - 好友：用 `/api/im/spotlight/relation` 拉好友列表，本地按名称/用户名匹配（支持 @handle 精确优先）。
  - 群聊：扫描会话列表 DOM，按群名称匹配；群号仅作为找到后的展示/校验字段，**不在 UI 里伪称「支持群号搜索」**。

## 七、实现方案（据此确定）

```
聊天链接采集
 ├─ 目标选择：好友（spotlight/relation 列表匹配） / 群聊（会话列表匹配）
 ├─ 唯一标识：好友=sec_uid + conversation_id(0:1:peer:self)；群聊=conversation_id(纯数字)
 ├─ 打开会话：click [data-conversation-id=目标]
 ├─ 验证目标：DivChatHeader 文本 比对目标名称，不一致即停止
 └─ 采集链接：滚动向上加载历史 → 抽取 a[href*="/video/"] → 去重 → 取最新 N 条
```

新模块（完全隔离，不改 ProfileCollector/CollectEngine/PublishTimeResolver/VideoParser）：
`app/chat/` 下 `models / provider / resolver / search / selector / collector / store` + `app/services/chat_service.py` + `app/ui/pages/chat_page.py`。

## 八、风险与限制

1. **二进制 WS 协议未解析**：会话列表/消息由 `im-ws-sg` 二进制推送，但渲染结果在 DOM，本方案只读 DOM，**规避了协议逆向**；代价是依赖 DOM 选择器（`data-e2e`/`data-conversation-id` 变化需重探）。
2. **群号不可搜索**：已如实降级为「按群名称选择」。
3. **无头限流**：与主页采集一致，聊天采集建议沿用「账号间隔 + 登录态复用」，必要时有窗口模式。
4. **部分消息类型 Web 不支持**：`This message type isn't supported. Download TikTok app`（如部分贴纸/消息），不影响共享视频链接抽取。
5. **`data-conversation-id` 的 `0:1:` 格式为 DM、纯数字为群聊**：本结论基于 31 个会话样本 + 群名/头部成员数交叉验证，属高置信但非绝对；代码中对「群聊」判定会再以聊天头部 `members` 文案做二次校验。

## 九、证据文件（本地留档，不入仓库）

`diagnostics/chat_evidence/` 下：`messages.html`、`messages_logged.html`、`v2_ws_log.json`、`v4_conversations.json`、`v5_chat_views.json`、`api_*_*.json` 等；探针脚本 `diagnostics/chat_probe.py / chat_probe_headed.py / chat_probe_v2~v5.py`。
