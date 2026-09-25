"""全局常量定义。"""

APP_NAME = "TikTok Link Collector"
APP_NAME_CN = "TikTok 作品链接采集器"
APP_VERSION = "1.0.0"

# 默认路径（相对项目根）
DEFAULT_DB_PATH = "data/tiktok_link_collector.db"
DEFAULT_EXPORT_DIR = "exports"
DEFAULT_LOG_DIR = "logs"
DEFAULT_LINKS_LOG_DIR = "links_log"   # 每日链接日志归档目录（YYYYMMDD.txt）

# 采集默认值
DEFAULT_COLLECT_COUNT = 4
DEFAULT_MAX_RETRY = 3
DEFAULT_TIMEZONE = "Asia/Shanghai"

# 浏览器默认
DEFAULT_PAGE_LOAD_TIMEOUT_MS = 30000
DEFAULT_TASK_INTERVAL_MS = 2000
DEFAULT_ERROR_WAIT_MS = 3000
DEFAULT_ACCOUNT_INTERVAL_SECONDS = 4   # 账号间等待（规避 TikTok 风控，配置化）

# 常用时区（设置页下拉）
COMMON_TIMEZONES = [
    "Auto",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Hong_Kong",
    "Asia/Singapore",
    "America/Los_Angeles",
    "America/New_York",
    "Europe/London",
    "Europe/Paris",
    "UTC",
]
