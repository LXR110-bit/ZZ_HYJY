from pathlib import Path
import anthropic
from config import CLAUDE_API_KEY, CLAUDE_BASE_URL, CLAUDE_MODEL

client = anthropic.Anthropic(
    api_key=CLAUDE_API_KEY,
    base_url=CLAUDE_BASE_URL,
)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPT_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


WEEKLY_MEETING_PARTICIPANTS = ["徐超", "陈俊", "刘斯佳", "李肖然", "孟祥楠", "熊曼佚", "郑文浩", "夏晓童", "孙浩然"]


def _build_system_prompt(meeting_topic: str = "") -> str:
    output_format = _load_prompt("output_format.md")
    glossary = _load_prompt("business_glossary.md")

    is_weekly = "周会" in meeting_topic
    weekly_block = ""
    if is_weekly:
        names = "、".join(WEEKLY_MEETING_PARTICIPANTS)
        weekly_block = f"""
---

# ⚠️ 本场是【周会】——人名强约束规则（最高优先级）

本场会议的参会人**只可能是以下 9 人之一**：{names}

执行规则：
1. 纪要中所有人名必须来自上述 9 人。任何不在名单内的人名，**严禁凭空生成**。
2. 逐字稿里的"说话人 1 / 说话人 2 / 说话人 N"是飞书妙记的占位符，**不是真实姓名**。如果无法从上下文锁定身份（自我介绍、被点名、@提及），**保留"说话人 N"原样**，不要瞎猜。
3. 语音识别的近音字优先在名单内匹配：例如"思佳/思家/斯加"→刘斯佳，"祥南/向南"→孟祥楠，"满意/曼意"→熊曼佚，"小然/消然"→李肖然，"小金/小同/晓彤"→夏晓童，"孙昊然/浩然"→孙浩然。
4. 如果出现名单外的人名（语音识别可能把名单内的某人识别成了陌生昵称），**保留原文 + 后缀"（待确认）"**，例如"小李（待确认）"，方便人工核对。**不允许**直接用陌生人名作为决策/待办的负责人。
5. "决策事项"、"待办事项"表格的负责人列：必须是名单内的姓名，或写"待定"；**不允许**出现名单外的姓名。
6. 对照下方业务术语表的"九-A、周会专属"小节执行，遇冲突以本规则为准。

---

# ⚠️ 本场是【周会】——固定汇报板块结构（最高优先级）

本周会**严格按以下 7 大板块组织"二、关键讨论点"内容**，板块顺序、标题、负责人都必须固定：

```
## 二、关键讨论点

### 板块 1：上周待办回顾
（汇总上周遗留待办的进展，未完成的转入本周待办）

### 板块 2：部门 OKR 进度（汇报人：徐超）
- 本周 OKR 进展、关键里程碑、风险点

### 板块 3：产品进度（汇报人：孙浩然）
- 产品迭代、上线、需求评审进展

### 板块 4：增长 / 流量 / 转化（汇报人：李肖然）
- 流量异动、渠道、转化漏斗、活动承接

### 板块 5：履约流程（汇报人：郑文浩）
- 履约链路、质检、服务商、上门数据

### 板块 6：品类运营（汇报人：成长品类-熊曼佚 / 孵化品类-陈俊）
- 各品类的流量、估价、成交、新品节奏。**子标题先按"成长品类"和"孵化品类"区分**，再列具体品类

### 板块 7：服务与体验（汇报人：刘斯佳 / 夏晓童）
- 用户体验、NPS、客诉、客服人力、瑕疵视频等
```

板块内子议题的格式仍按 output_format.md 的"背景 / 讨论要点 / 结论"三段式。

**关键约束**：
- 即使某个板块本周没汇报内容，也要保留板块标题，正文写"本周无汇报"
- 不要把内容串到错的板块里：例如"豁免质检"必须在板块 5（履约流程），不能放在板块 7
- 板块 6（品类运营）的子议题先用 `#### 成长品类` 和 `#### 孵化品类` 分组，再列具体品类
- 如果某个发言人在自己负责的板块里讲到了别人板块的事，按"事的归属"而非"说话人"决定放哪个板块
- 板块标题原样保留"汇报人：xxx"信息，方便事后追溯
"""

    return f"""你是转转回收业务团队的专业会议纪要整理助手。

# 任务
基于会议逐字稿（可能包含语音识别错误）和飞书自动生成的纪要，产出一份完整、准确、结构化的会议纪要。

# 工作要求
1. **修正语音识别错误**：严格对照下方业务术语表，修正所有业务术语、产品名、指标名、人名等识别错误
2. **结构化输出**：严格按照下方输出格式要求组织内容
3. **客观表达**：禁用"效果显著"、"非常好"等主观评价词，用具体数据描述
4. **信息完整**：决策和待办必须保留完整信息（谁、做什么、什么时候）
5. **逻辑清晰**：按议题分段，每段有背景、讨论、结论
{weekly_block}
---

# 业务术语表（语音识别纠正参考）

{glossary}

---

# 输出格式要求

{output_format}
"""


def generate_meeting_minutes(transcript: str, auto_summary: str = "", meeting_topic: str = "") -> dict:
    """调用 Claude 生成完整会议纪要，返回 {summary: 摘要, full: 完整版}"""
    system_prompt = _build_system_prompt(meeting_topic)

    user_content = f"【会议主题】{meeting_topic}\n\n" if meeting_topic else ""
    if auto_summary:
        user_content += f"【飞书自动生成的纪要（仅供参考）】\n{auto_summary}\n\n"
    user_content += f"【会议逐字稿】\n{transcript}\n\n"
    user_content += "请基于以上内容，严格按照系统提示中的格式要求，生成完整版会议纪要（Markdown 格式）。"

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    full_minutes = response.content[0].text

    summary_response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": f"""以下是一份完整的会议纪要。请将其压缩为 3-5 条核心要点，用于群消息通知。

要求：
- 每条一行，以 ✅ 开头
- 优先保留：决策事项、明确的 Action（带责任人和 DDL）、核心数据结论
- 格式：✅ 结论内容（@责任人 DDL）
- 客观陈述，不用主观评价词

会议纪要：
{full_minutes}""",
        }],
    )
    summary = summary_response.content[0].text

    return {"summary": summary, "full": full_minutes}
