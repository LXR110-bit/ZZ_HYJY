"""真值回放：用 2026-08-30 取证实测到的结果验证 did_user_attend。

打真实飞书 API，不参与 `unittest discover`（文件名不以 test_ 开头）。
手动运行：cd /opt/ZZ_HYJY && venv/bin/python3 tests/integration_replay.py

可证伪性：被替换掉的日历判定在这 6 场上返回 6/6 全 True。
新实现若也全 True，说明判定层根本没换成参会记录。
"""

import os
import sys

# 直接运行时 sys.path[0] 是 tests/，需要把项目根加进来
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.feishu import did_user_attend, VcLookupError

# (meeting_id, 会议, 2026-08-30 用 VC 参会人接口实测的真值)
CASES = [
    ("7674953097731722502", "08-17 品类组周会", False),
    ("7675193264808545572", "08-18 万象周例会W33", True),
    ("7675572111171226818", "08-19 诺曼底品类簇周会", False),
    ("7677551162732367107", "08-24 品类组周会", False),
    ("7677790316539726810", "08-25 万象周例会", False),
    ("7678168646402313516", "08-26 诺曼底品类簇周会", False),
]


def main() -> int:
    failures = 0
    for meeting_id, name, expected in CASES:
        try:
            actual, evidence = did_user_attend(meeting_id)
        except VcLookupError as e:
            print(f"  ERROR  {name:<26} {e}")
            failures += 1
            continue
        mark = "ok  " if actual == expected else "FAIL"
        if actual != expected:
            failures += 1
        print(f"  {mark}   {name:<26} 期望={expected!s:<5} 实际={actual!s:<5} {evidence}")

    print()
    if failures:
        print(f"回放失败：{failures}/{len(CASES)} 场不符")
        return 1
    print(f"回放通过：{len(CASES)}/{len(CASES)} 场与实测真值一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
