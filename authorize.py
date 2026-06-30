"""一次性用户授权脚本。浏览器打开 → 点"同意" → 自动拿到 refresh_token 存本地。"""

import webbrowser
import http.server
import urllib.parse
import threading
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET
from services.tokens import save_tokens, _app_access_token

REDIRECT_URI = "http://localhost:9999/callback"
SCOPES = "minutes:minutes:readonly minutes:minutes.basic:read minutes:minutes.transcript:export minutes:minutes.artifacts:read calendar:calendar:readonly"

# OAuth 授权 URL (Authorization Code 模式)
AUTHORIZE_URL = (
    f"https://open.feishu.cn/open-apis/authen/v1/authorize"
    f"?app_id={FEISHU_APP_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&scope={urllib.parse.quote(SCOPES)}"
)

_code_holder = {"code": None}
_done = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            _code_holder["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>✅ 授权成功，可以关闭此页面了</h2>".encode("utf-8"))
            _done.set()
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"missing code")

    def log_message(self, *_):
        pass


def exchange_code_for_tokens(code: str):
    app_token = _app_access_token()
    resp = requests.post(
        "https://open.feishu.cn/open-apis/authen/v1/access_token",
        headers={"Authorization": f"Bearer {app_token}"},
        json={"grant_type": "authorization_code", "code": code},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"换 token 失败: {data}")
    d = data["data"]
    save_tokens(d["access_token"], d["expires_in"], d["refresh_token"])
    print(f"[auth] ✅ 授权完成，refresh_token 已保存到 .user_token.json")
    print(f"[auth] 授权用户：{d.get('name', '')} ({d.get('user_id', '')})")


def main():
    server = http.server.HTTPServer(("localhost", 9999), CallbackHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print(f"[auth] 浏览器即将打开授权页面...")
    print(f"[auth] 若没自动打开，手动访问：\n{AUTHORIZE_URL}\n")
    webbrowser.open(AUTHORIZE_URL)

    print("[auth] 等待授权回调...")
    if not _done.wait(timeout=300):
        print("[auth] ❌ 超时,没收到回调")
        return
    server.shutdown()

    code = _code_holder["code"]
    print(f"[auth] 收到 code: {code[:20]}...")
    exchange_code_for_tokens(code)


if __name__ == "__main__":
    main()
