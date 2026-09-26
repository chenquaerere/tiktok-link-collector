# 聊天链接采集模块 —— 原理与实现说明

> 适用版本：**v1.1.0+** ｜ 最后更新：2026-09-26
> 相关代码：`app/chat/`、`app/services/chat_service.py`、`app/ui/pages/chat_page.py`

本文记录「聊天链接采集」模块的**真实站点结构结论**与实现要点。这些结论全部来自对 TikTok 消息页的实际探针验证（脚本见 `diagnostics/chat_*_probe.py`），**不是推测**，修改本模块前请先读本文。

---

## 1. 模块定位

与原「作品链接采集」模块**完全独立**：

| 维度 | 作品采集 | 聊天采集 |
| ---- | ---- | ---- |
| 数据来源 | 账号主页 `item_list` 接口 | 消息页会话对话框内的分享卡片 |
| 采集单元 | 一个账号主页 | 一个群聊 / 好友会话 |
| 排序依据 | 主页时间倒序 | **聊天窗口内的垂直位置**（最下面最新） |
| 引擎 | `ProfileCollector` + `CollectEngine` | `ChatLinkCollector`（独立） |
| 数据表 | `videos` / `collect_tasks` | `chat_targets` / `chat_links` |

两者仅共用基础设施：`BrowserManager`（Playwright 启动）、`SessionManager`（登录态目录）。

---

## 2. 站点结构结论（关键，务必遵守）

### 2.1 会话列表

- 会话项 DOM：`[data-e2e="dm-new-conversation-item"]`
- **唯一标识 `data-conversation-id` 挂在宿主元素上，不在上面那个 e2e 元素上** → 取归属必须用 `el.closest('[data-conversation-id]')`。
- 两种格式：
  - 好友单聊：`0:1:<对端uid>:<本机uid>`
  - 群聊：纯数字（群 ID）
- 昵称：`p[class*="PInfoNickname"]`；摘要：`p[class*="PInfoExtract"]`。
  ⚠️ **不能用 `innerText` 首行当昵称**——有未读消息时首行是角标数字，会导致采集时目标校验失败。
- 好友 API：`/api/im/spotlight/relation` → `followings[]`（`uid` / `sec_uid` / `unique_id` / `nickname`），可用来补齐 @用户名。
  该接口在首屏**不一定触发**：正确做法是进页前先挂 `response` 监听，再轮询约 6 秒，仍无才 reload 一次。

### 2.2 聊天面板内的分享视频（核心）

- 聊天面板选择器：`[class*="DivChatBox"]`；消息气泡：`[class*="DivChatItemWrapper"]`。
- **聊天面板内不存在 `a[href*="/video/"]`**。分享视频以「缩略图卡片」（`div[style*="background-image"]`，CDN 路径含 `tos-alisg-p-0037`）形式渲染。
- 气泡里那个 19 位数字是**消息 ID**（`more-action-icon-msg-<消息ID>`），**不是作品 ID**。
- **作品 ID 的唯一来源是 React props**：
  ```js
  el['__reactProps$xxxx'].children.props.itemId   // 15 位以上纯数字 = 作品 ID
  ```
  从卡片元素向上最多找 6 层祖先即可命中。
- 拿到作品 ID 后调站点接口取作者：
  ```
  GET /api/im/item_detail/?itemId=<作品ID>      // 必须在页面内 fetch（带 credentials）
  → itemInfo.itemStruct.{ id, author.uniqueId, imagePost, desc }
  ```
  ⚠️ `itemId` 参数必须是**作品 ID**；传消息 ID 会返回 `statusCode: 10204`。
- 最终链接：`https://www.tiktok.com/@{author.uniqueId}/{video|photo}/{id}`（`imagePost=true` 时用 `photo`）。

### 2.3 顺序

聊天记录自上而下按时间排列，**最下面那条最新**。因此：

- 抽取后按 `getBoundingClientRect().top` **降序**排序（top 越大越靠下越新）；
- 取前 N 条 = 最新 N 条；
- 数量不够时向上滚动（`mouse.wheel(0, -3000)`）加载更早的历史。

⚠️ **不要用 DOM 顺序**：实测 DOM 顺序与视觉顺序并不总是一致。
⚠️ 滚动前必须先把鼠标移到聊天面板上（`mouse.move(vw*0.72, vh*0.5)`），否则滚轮滚的是左侧会话列表。

### 2.4 不要碰的路径

- `im-api-sg.tiktok.com/v1/message/get_by_conversation`、`get_by_user_combo`：**protobuf 二进制**，不可直接解析，不要走这条路。
- 不要整页 `querySelectorAll('a[href*="/video/"]')`：会话列表预览与页头里存在大量**隐藏的**同构链接（`vis=false`），会全部被误采。

---

## 3. 采集流程

```
ChatService.collect(account, target, count, on_progress, stop_event, on_ratio)
  └─ BrowserManager + 账号 Session 目录 → 持久化 context
       ├─ ChatProvider.load_messages()          打开消息页（等待会话项出现）
       ├─ login_check(page)                     进页后立刻校验登录态（快速失败）
       ├─ open_conversation(page, cid)          点开会话，等聊天头部出现
       ├─ ChatTargetResolver.verify_target()    二次校验头部 = 目标（不一致立即停止）
       └─ 循环（最多 15 轮）
            ├─ extract_chat_items(page)         面板内取卡片 → itemId + 垂直位置（下→上）
            ├─ resolve_items(page, 新卡片)      分片并发调 item_detail（chunk=6，带缓存）
            ├─ build_item_url()                 拼真实链接
            ├─ 数量够了 → 结束
            └─ 否则向上滚动一轮，加载更早历史
```

**停止机制**：`stop_event`（`threading.Event`）在每轮开头检查，置位即返回 `status="stopped"`，已采到的链接保留。

**进度**：`on_progress(stage)` 输出阶段文案；`on_ratio(0~1)` 驱动进度条。

**失败语义**：

| status | 含义 |
| ---- | ---- |
| `completed` | 采满 N 条 |
| `partial` | 小于 N 条但 > 0 |
| `empty` | 一条都没有（会话内无分享卡片 / 详情全解析失败） |
| `stopped` | 用户手动停止 |
| `failed` | 会话打不开、目标校验失败、登录失效等 |

---

## 4. 数据表

```sql
chat_targets(stable_key PK, chat_type, name, handle, uid, sec_uid, conversation_id, last_used_at)
chat_links(stable_key, video_id, video_url, order_num, collected_at)   -- 替换式写入
```

- `stable_key` 取值优先级：`conv:<conversation_id>` > `secuid:<sec_uid>` > `uid:<类型>:<uid>`。
- 同一目标重新采集时**按最后一次替换**（先删后插），不会越采越堆。
- 两张表通过 `IF NOT EXISTS` 幂等追加，**不影响**旧库升级（`SCHEMA_VERSION` 未变）。

---

## 5. 线程与 UI 约束（踩坑记录）

1. **禁止在 worker 线程直接调用 `self.after()`** —— tkinter 的 `after` 非线程安全，会抛
   `RuntimeError: main thread is not in main loop`，表现为界面永不更新且无任何报错。
   本模块使用独立事件队列（`queue.Queue` + 主线程 120ms 泵）；其它页面统一用 `BasePage.ui_call()`。
2. **关键动作不要用模态确认框** —— `CTkToplevel` + `grab_set` 一旦被主窗口遮挡，主界面会被卡住，
   用户看到的是「点了没反应」且日志无记录。改用按钮内联二次确认。
3. **会话行必须整行可点** —— CTk 控件的 `bind()` 实际绑在内部 `_canvas` 上，
   且 `CTkRadioButton` 只有小圆圈响应点击；只绑小圆圈会导致「点了没反应」。
4. **任何空的 `CTkFrame` 必须显式给 `width/height`** —— 默认请求 200×200，会把父容器撑大
   （曾导致页面头部占 200px、右下角残留黑块）。

---

## 6. 验证方式

```bash
# 真实端到端（复用已登录会话，打印阶段耗时与链接）
python diagnostics/e2e_chat_check.py 8

# 链接顺序校验（对比 DOM 顺序 vs 垂直位置顺序）
python diagnostics/chat_order_check.py

# UI 链路检查（不启动浏览器，用桩服务）
python tests/chat_ui_click_check.py
```

实测参考耗时（含浏览器启动）：会话列表 ≈16s，单会话采集 8 条 ≈20s。

---

## 7. 已知限制

- **群号搜索不支持**：TikTok Web 端不支持按群 ID 搜索，群聊只能在会话列表内按群名匹配。
- **未开过对话的目标无法采集**：会话列表里不存在的目标没有 `conversation_id`，无法定位。
- **仅采集已渲染的消息**：极端大量历史需要多轮滚动，默认上限 15 轮。
- **登录态依赖**：消息页需要登录；程序只做检测与提示，不绕过任何验证。
