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


def _build_system_prompt() -> str:
    output_format = _load_prompt("output_format.md")
    glossary = _load_prompt("business_glossary.md")

    return f"""你是转转回收业务团队的专业会议纪要整理助手。

# 任务
基于会议逐字稿（可能包含语音识别错误）和飞书自动生成的纪要，产出一份完整、准确、结构化的会议纪要。

# 工作要求
1. **修正语音识别错误**：严格对照下方业务术语表，修正所有业务术语、产品名、指标名、人名等识别错误
2. **结构化输出**：严格按照下方输出格式要求组织内容
3. **客观表达**：禁用"效果显著"、"非常好"等主观评价词，用具体数据描述
4. **信息完整**：决策和待办必须保留完整信息（谁、做什么、什么时候）
5. **逻辑清晰**：按议题分段，每段有背景、讨论、结论

---

# 业务术语表（语音识别纠正参考）

{glossary}

---

# 输出格式要求

{output_format}
"""


def generate_meeting_minutes(transcript: str, auto_summary: str = "", meeting_topic: str = "") -> dict:
    """调用 Claude 生成完整会议纪要，返回 {summary: 摘要, full: 完整版}"""
    system_prompt = _build_system_prompt()

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
