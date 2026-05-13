"""用户 access_token 管理：持久化 refresh_token，自动续期。"""

import json
import time
import threading
from pathlib import Path
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET

BASE_URL = "https://open.feishu.cn/open-apis"
TOKEN_FILE = Path(__file__).parent.parent / ".user_token.json"

_lock = threading.Lock()
_cache = {"access_token": None, "expire_at": 0, "refresh_token": None}


def _load():
    if _cache["refresh_token"] is None and TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        _cache["access_token"] = data.get("access_token")
        _cache["expire_at"] = data.get("expire_at", 0)
        _cache["refresh_token"] = data.get("refresh_token")


def _save():
    TOKEN_FILE.write_text(
        json.dumps({
            "access_token": _cache["access_token"],
            "expire_at": _cache["expire_at"],
            "refresh_token": _cache["refresh_token"],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_tokens(access_token: str, expires_in: int, refresh_token: str):
    with _lock:
        _cache["access_token"] = access_token
        _cache["expire_at"] = time.time() + expires_in
        _cache["refresh_token"] = refresh_token
        _save()


def _app_access_token() -> str:
    resp = requests.post(
        f"{BASE_URL}/auth/v3/app_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 app_access_token 失败: {data}")
    return data["app_access_token"]


def _refresh():
    if not _cache["refresh_token"]:
        raise RuntimeError(
            "未授权。请先运行 python3 authorize.py 完成用户授权。"
        )
    app_token = _app_access_token()
    resp = requests.post(
        f"{BASE_URL}/authen/v1/refresh_access_token",
        headers={"Authorization": f"Bearer {app_token}"},
        json={"grant_type": "refresh_token", "refresh_token": _cache["refresh_token"]},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"刷新 user_access_token 失败: {data}")
    d = data["data"]
    _cache["access_token"] = d["access_token"]
    _cache["expire_at"] = time.time() + d["expires_in"]
    _cache["refresh_token"] = d["refresh_token"]
    _save()


def get_user_access_token() -> str:
    with _lock:
        _load()
        if _cache["access_token"] and time.time() < _cache["expire_at"] - 300:
            return _cache["access_token"]
        _refresh()
        return _cache["access_token"]
