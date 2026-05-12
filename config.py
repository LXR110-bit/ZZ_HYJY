import os
from dotenv import load_dotenv

load_dotenv()

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_CHAT_ID = os.getenv("FEISHU_CHAT_ID")

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
CLAUDE_BASE_URL = os.getenv("CLAUDE_BASE_URL", "https://v2.qixuw.com")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
