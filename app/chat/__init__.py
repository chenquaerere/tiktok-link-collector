"""TikTok 聊天链接采集模块（独立板块）。

与作品采集模块完全隔离：
- 不修改 ProfileCollector / CollectEngine / PublishTimeResolver / VideoParser。
- 仅共享 browser / session 基础设施（只调用，不改动）。
子模块：models（数据模型）/ provider（站点访问）/ search（目标搜索）/
resolver（目标解析）/ collector（链接采集）/ store（持久化 DAO）。
"""
