from pathlib import Path
import time
import anthropic
from config import CLAUDE_API_KEY, CLAUDE_BASE_URL, CLAUDE_MODEL

client = anthropic.Anthropic(
    api_key=CLAUDE_API_KEY,
    base_url=CLAUDE_BASE_URL,
)

PROMPT_DIR = Path(__file__).parent.parent / "prompts"

MAX_RETRIES = 3
RETRY_DELAY = 10


def _call_claude(retries=MAX_RETRIES, **kwargs):
    """带重试的 Claude API 调用，处理 502/503/529 等临时错误。"""
    for attempt in range(retries):
        try:
            return client.messages.create(**kwargs)
        except (anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            if attempt < retries - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"[claude] API 调用失败 (attempt {attempt + 1}/{retries}): {e}，{wait}s 后重试")
                time.sleep(wait)
            else:
                raise


def _load_prompt(filename: str) -> str:
    path = PROMPT_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


WEEKLY_MEETING_PARTICIPANTS = ["徐超", "陈俊", "刘斯佳", "李肖然", "孟祥楠", "熊曼佚", "郑文浩", "夏晓童", "孙浩然"]


def _build_system_prompt(meeting_topic: str = "") -> str:
    output_format = _load_prompt("output_format.md")
    glossary = _load_prompt("business_glossary.md")

    is_weekly = any(kw in meeting_topic for kw in ["周会", "周例会", "例会"])
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

按实际讨论内容拆分议题，标题用数字编号 + 实际议题名称，重要议题标注汇报人。不使用固定"板块N"编号。参考格式：

```
## 二、关键讨论点

### 1. Q3 OKR 目标与策略方向（徐超）
### 2. 增长/流量/活动侧进展（李肖然汇报）
### 3. 产品迭代进展（孙浩然汇报）
### 4. 履约侧数据与优化（郑文浩汇报）
### 5. 发展品类运营（熊曼佚汇报）
### 6. 孵化品类进展（陈俊汇报）
### 7. 德邦快递费成本管控
### 8. 用户体验与 NPS（刘斯佳/夏晓童汇报）
```

以上仅为示例，实际标题根据会议内容灵活拟定，数量不限，顺序按实际汇报顺序。重要的独立话题（如德邦物流、服务商考核）可以单独列为一个议题。

每个议题内部按"背景 / 讨论要点 / 结论"三段式组织。

**内容归属规则**：
- 流量转化路径异动（品类入口 UV/PV 涨跌、搜索/金刚位占比变化）→ 归增长相关议题（李肖然）
- 品类估价、下单、成交、价格策略、新品节奏 → 归品类运营议题（熊曼佚/陈俊）
- 品类运营内部先按"发展品类"和"孵化品类"分组。**孵化品类固定 5 个**：台球杆、公路车、名酒、盲盒、电动车；其余归发展品类
- 履约链路、质检、服务商考核、上门数据 → 归履约议题（郑文浩）
- 用户体验、NPS、客诉、客服人力、瑕疵视频 → 归服务与体验议题（刘斯佳/夏晓童）
- **物流相关**（德邦、运费、包装费、开单类型、揽收、回寄、超长加收）→ 归刘斯佳负责的议题
- 如果某个发言人在自己板块讲到了别人板块的事，按"事的归属"而非"说话人"决定放哪个议题

**待办事项要求（关键）**：
- 待办事项必须**尽可能详尽**，把会议中所有提到的具体任务、跟进项全部列出
- 每条待办必须有明确负责人和截止时间
- 不要合并多个任务为一条，宁可多列也不要漏
- 上周遗留待办如果本周仍在进行，标注"进行中"；新增的标注"待开始"

**决策与待办全局汇总**：
- 必须按 output_format.md 完整输出 6 大节：会议目标 / 关键讨论点 / 决策事项 / 待办事项 / 未解决问题 / 备注
- "三、决策事项"和"四、待办事项"必须是**全局汇总表格**，把所有议题里讨论出来的决策/待办抽取到表里，**不允许省略**
"""

    return f"""你是转转回收业务团队的专业会议纪要整理助手。

⚠️ 关键约束：你的输出必须包含完整的6大节（一、会议目标 / 二、关键讨论点 / 三、决策事项 / 四、待办事项 / 五、未解决问题 / 六、备注）。其中"三、决策事项"和"四、待办事项"必须是 Markdown 表格。"二、关键讨论点"每个议题简明扼要（背景1行 + 要点3-5行 + 结论1行），不要过于展开细节，确保整体输出不会在第二节结束后就停止。

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
    user_content += "请基于以上内容，严格按照系统提示中的格式要求，生成完整版会议纪要（Markdown 格式）。\n\n【重要提醒】输出必须包含完整6节（一至六），尤其决策事项和待办事项的表格绝不能省略。关键讨论点每个议题控制在3-5行，把篇幅留给决策和待办。"

    response = _call_claude(
        model=CLAUDE_MODEL,
        max_tokens=16384,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    full_minutes = response.content[0].text

    summary_response = _call_claude(
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
