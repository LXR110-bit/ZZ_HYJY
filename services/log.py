"""带时间戳的日志输出。

现状：main.py / handlers / services 里的 print 都不带时间戳，排查时只能靠
最近一条 [Lark] SDK 日志反推时间。新增和改动的代码路径统一走这里。
不对存量 print 做全局改造——那会 touch 太多文件，风险大于收益。
"""

import time


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{ts}] {msg}", flush=True)
