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
