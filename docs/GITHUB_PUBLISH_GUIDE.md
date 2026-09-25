# 上传 GitHub 完整指南

> 适用：TikTok 作品链接采集器 v1.0.0
> 目的：版本托管 + 自动更新源 + 离线备份
> 预计耗时：10 分钟

---

## 0. 一句话结论

把项目推到 **公开仓库**，每次发版往 **Releases** 传一个 zip，程序内的「自动更新」就能自动发现新版本——这就是前面实现的更新机制的数据来源。

---

## 1. 仓库信息（直接抄）

| 项 | 推荐值 |
| ---- | ---- |
| **仓库名称** | `tiktok-link-collector` |
| **描述 Description** | 见下方（中英二选一） |
| **可见性 Visibility** | **Public（公开）** |
| **默认分支** | `main` |
| **License** | MIT（已生成 `LICENSE` 文件） |
| **Topics 标签** | `tiktok` `link-collector` `playwright` `python` `windows` `customtkinter` |

### 描述文案（二选一）

**中文版（推荐，目标用户是中文）：**
```
批量采集自己 TikTok 账号作品链接的 Windows 桌面工具。一键导出纯文本链接，支持多账号、断点续传、数据库备份与自动更新。
```

**英文版（国际化）：**
```
Windows desktop tool to batch-collect video links from your own TikTok accounts. One-click export of plain-text links, multi-account, resume support, DB backup & auto-update via GitHub Releases.
```

> 描述上限约 350 字符，上面两条都在范围内。

---

## 2. 上传前的 3 个准备（重要）

### 2.1 确认 .gitignore 已就绪（已配置好）
项目里的 `.gitignore` 已排除所有敏感/体积大的内容：
- `data/`（数据库 + 浏览器会话，**含你的登录态**）
- `logs/`、`links_log/`、`exports/`
- `diagnostics/`（真实账号的 API 证据）
- `dist/`、`build/`、`dist_bak*/`、`build_bak*/`（打包产物与历史备份）
- `.env`（真实密钥）

**无需再改**，但推送前强烈建议跑一次下面的「模拟预览」确认没有漏网之鱼。

### 2.2 替换 LICENSE 里的版权名
打开 `LICENSE`，把第一行 `[你的名字或 GitHub 用户名]` 改成你自己的名字或 GitHub 用户名。

### 2.3 检查 README 无真实账号
README、docs/ 下的账号已脱敏（`demo_alpha` 等）。若你后面在别处写了真实账号，推送前搜一下：
```bash
grep -rn "你的真实账号" docs/ tests/ app/ README.md
```

---

## 3. 本地初始化 + 首次提交（完整命令，逐条执行）

```bash
# 1) 进入项目目录
cd "D:/TikTokLinkCollector"

# 2) 初始化仓库（默认分支 main）
git init -b main

# 3) 模拟预览：看将要上传哪些文件（应该是干净的源码 + 文档）
git add -A
git status
#    ↑ 确认没有 data/、diagnostics/、dist/ 等被加入

# 4) 确认无误后提交
git commit -m "v1.0.0: 首个正式版 — 采集闭环 + UI 产品化 + 自动更新"

# 5) 配置身份（首次需要，用户名/邮箱用你的 GitHub 账号）
git config user.name "你的GitHub用户名"
git config user.email "你的邮箱@example.com"
```

> ⚠️ 第 3 步 `git status` 是关键检查点：如果看到 `data/sessions/...`、`diagnostics/raw/...` 出现在「to be committed」列表里，说明 .gitignore 没生效，先 `git rm --cached -r` 那些路径再继续。

---

## 4. 创建远程仓库（两种方式，选其一）

### 方式 A：网页操作（推荐新手）
1. 打开 https://github.com/new
2. 填 `Repository name`：`tiktok-link-collector`
3. 填 `Description`：复制上面第 1 节的描述
4. 选 **Public**
5. ⚠️ **不要勾选** "Add a README / .gitignore / license"（本地已有了，勾了会冲突）
6. 点 **Create repository**

### 方式 B：命令行（已装 GitHub CLI 的话）
```bash
gh repo create tiktok-link-collector --public \
  --description "批量采集自己 TikTok 账号作品链接的 Windows 桌面工具" \
  --source . --remote origin --push
# 这条命令会：建仓库 + 关联 remote + 直接推送，一步到位
```

---

## 5. 关联远程并推送

```bash
# 方式 A 之后执行这两条
git remote add origin https://github.com/你的GitHub用户名/tiktok-link-collector.git
git push -u origin main
```

推送成功后，浏览器打开 `https://github.com/你的GitHub用户名/tiktok-link-collector` 就能看到代码了。

---

## 6. 发布 Release（对接「自动更新」，关键步骤）

这是让程序自动更新的数据来源，**每次发版都要做**。

### 6.1 打包并压缩便携版
```bash
# 打包完成后，把便携版目录压成 zip（约 840MB）
# 注意：只打包「运行时所需」，不要把 dist_bak 一起压进去
cd dist
# 用系统资源管理器压缩 TikTokLinkCollector 文件夹为 TikTokLinkCollector-v1.0.0.zip
```

### 6.2 网页发 Release
1. 仓库主页 → 右侧 **Releases** → **Create a new release**
2. **Tag version**：填 `v1.0.0`（⚠️ 必须带 `v` 前缀，且要比程序内当前版本号 `1.0.0` 对应的 tag 新）
3. **Release title**：`v1.0.0`
4. **Describe**：写更新说明（用户点「查看下载」时会看到）
5. 把 `TikTokLinkCollector-v1.0.0.zip` 拖进 **Attach binaries** 区
6. 点 **Publish release**

### 6.3 程序内填写更新源
1. 打开程序 → 设置 → 「更新」分组
2. GitHub 仓库填：`你的GitHub用户名/tiktok-link-collector`
3. 保存

之后每次你发新版（tag 版本号递增），用户/你自己打开程序就会自动弹「发现新版本」。

---

## 7. 版本号递增约定（发版必读）

- 程序内版本号在 `app/constants.py` 的 `APP_VERSION`（和 `app/__init__.py` 的 `__version__`）。
- Release 的 tag 必须与 `APP_VERSION` 一致（`APP_VERSION="1.0.0"` ↔ tag `v1.0.0`）。
- 下次发版：改 `APP_VERSION` → 重新打包 → 发新 Release（tag 递增，如 `v1.0.1` / `v1.1.0`）。
- 程序判断「是否有新版」就是拿 tag 和本地 `APP_VERSION` 比大小，tag 比本地大才会提示。

---

## 8. 常见问题

### Q1：想私有仓库怎么办？
私有仓库的 Releases API 匿名访问会返回 404，程序会静默当「无更新」。需要额外配 Personal Access Token（PAT）——对个人小工具不划算。**建议保持公开**；若坚持私有，把 PAT 填进程序的更新配置并接受「token 有过期风险」。

### Q2：840MB 的 zip 传得上吗？
GitHub Release 单文件上限 **2GB**，够用。但注意：**不要**把 zip 也 `git add` 进仓库（会撑爆 git 历史），只通过 Release 页面附件上传。

### Q3：提示 push 失败 / 401？
说明没登录或没权限，用 `gh auth login` 登录，或改用 HTTPS + Personal Access Token 推送。

### Q4：后悔公开了？
仓库 → Settings → Danger Zone → Change visibility → Private，随时可切回私有。

---

## 附：完整命令速查（复制粘贴版）

```bash
cd "D:/TikTokLinkCollector"
git init -b main
git add -A
git status                      # ← 检查点
git commit -m "v1.0.0: 首个正式版"
git branch -M main
git remote add origin https://github.com/<你的用户名>/tiktok-link-collector.git
git push -u origin main
```
