"""用户 access_token 管理：持久化 refresh_token，自动续期。

多实例/重启健壮性说明：
- refresh_token 是一次性的，刷新一次即作废旧值。若多个进程各持内存副本，
  会互相把对方的 refresh_token 刷失效（飞书报 20026 "refresh token is invalid,
  it may has been used"）。
- 为此：每次取 token 前重读文件拿最新值；refresh 命中 20026 时重读文件并重试一次，
  以自愈其它来源刚刚完成的刷新。
"""

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


def _load(force: bool = False):
    """从文件加载 token 到内存缓存。

    force=True 时无条件重读（用于每次取用/刷新前拿到最新的 refresh_token），
    force=False 时仅在缓存为空时读一次（兼容旧行为）。
    """
    if (force or _cache["refresh_token"] is None) and TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
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
        _cache["expire_at"] = time.time() + int(expires_in)
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


def _do_refresh_request(refresh_token: str) -> dict:
    app_token = _app_access_token()
    resp = requests.post(
        f"{BASE_URL}/authen/v1/refresh_access_token",
        headers={"Authorization": f"Bearer {app_token}"},
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    return resp.json()


def _refresh():
    if not _cache["refresh_token"]:
        raise RuntimeError(
            "未授权。请先运行 python3 authorize.py 完成用户授权。"
        )
    data = _do_refresh_request(_cache["refresh_token"])

    # 20026: refresh token 已被使用（多为其它来源刚刷过）。重读文件拿最新 token 自愈。
    if data.get("code") == 20026:
        print("[tokens] refresh 命中 20026，重读文件后重试")
        _load(force=True)
        # 若文件里的 access_token 仍然有效，直接用，避免再次刷新
        if _cache["access_token"] and time.time() < _cache["expire_at"] - 300:
            return
        data = _do_refresh_request(_cache["refresh_token"])

    if data.get("code") != 0:
        raise RuntimeError(f"刷新 user_access_token 失败: {data}")
    d = data["data"]
    _cache["access_token"] = d["access_token"]
    _cache["expire_at"] = time.time() + d["expires_in"]
    _cache["refresh_token"] = d["refresh_token"]
    _save()


def get_user_access_token() -> str:
    with _lock:
        # 每次都重读文件，拿到最新的 refresh_token / access_token
        _load(force=True)
        if _cache["access_token"] and time.time() < _cache["expire_at"] - 300:
            return _cache["access_token"]
        _refresh()
        return _cache["access_token"]
