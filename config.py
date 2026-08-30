import os
from dotenv import load_dotenv

load_dotenv()

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_CHAT_ID = os.getenv("FEISHU_CHAT_ID")

# 主持人白名单（逗号分隔的 open_id），只处理这些人发起的会议
# 为空则处理所有会议（调试模式）
_raw_whitelist = os.getenv("MEETING_OWNER_WHITELIST", "").strip()
MEETING_OWNER_WHITELIST = {x.strip() for x in _raw_whitelist.split(",") if x.strip()}

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_BASE_URL = os.getenv("CLAUDE_BASE_URL", "https://v2.qixuw.com")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# 授权用户 open_id（李肖然）。判定"是否参会"和文档转 owner 都用它。
# 原先硬编码在 services/feishu.py 里，现收敛到此处。
AUTHORIZED_USER_OPEN_ID = os.getenv(
    "AUTHORIZED_USER_OPEN_ID", "ou_a6cee6c6461d5ba265b68fea58f89b3a"
)

# 影子运行：跑真实事件流和判定，但不建文档、不转 owner、不发群消息。
DRY_RUN = os.getenv("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
