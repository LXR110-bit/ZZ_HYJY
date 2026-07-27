from pathlib import Path
import time
import json
import requests
from config import CLAUDE_API_KEY, CLAUDE_BASE_URL, CLAUDE_MODEL

PROMPT_DIR = Path(__file__).parent.parent / "prompts"

MAX_RETRIES = 3
RETRY_DELAY = 10

_HEADERS = {
    "Authorization": f"Bearer {CLAUDE_API_KEY}",
    "content-type": "application/json",
}


class _FakeContent:
    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeContent(text)]


def _call_claude(retries=MAX_RETRIES, **kwargs):
    """用 streaming 方式调用 DeepSeek（OpenAI 兼容）Chat API，避免代理对长响应的超时。

    注意 deepseek-v4-pro 是推理模型：SSE 里 delta.reasoning_content 是思维链、
    delta.content 才是正文；且 max_tokens 会被"思维链 + 正文"一起消耗，给小了正文会为空。
    """
    url = CLAUDE_BASE_URL.rstrip("/") + "/chat/completions"

    # OpenAI 格式不支持顶层 system，把 system 合并成 messages 里的 system role
    messages = list(kwargs.get("messages", []))
    if kwargs.get("system"):
        messages = [{"role": "system", "content": kwargs["system"]}] + messages

    payload = {
        "model": kwargs.get("model", CLAUDE_MODEL),
        "max_tokens": kwargs.get("max_tokens", 64000),
        "messages": messages,
        "stream": True,
    }

    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=_HEADERS, json=payload, stream=True, timeout=300)
            if resp.status_code != 200:
                err_msg = resp.text[:200]
                raise RuntimeError(f"HTTP {resp.status_code}: {err_msg}")
            # 逐行读取 SSE 流，只拼接正文 content（忽略 reasoning_content 思维链）
            text_parts = []
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8") if isinstance(line, bytes) else line
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                content = choices[0].get("delta", {}).get("content")
                if content:
                    text_parts.append(content)
            text = "".join(text_parts)
            if not text:
                raise RuntimeError("streaming 响应无 content 内容（可能 max_tokens 被思维链吃光）")
            return _FakeResponse(text)
        except Exception as e:
            if attempt < retries - 1:
                wait = RETRY_DELAY * (attempt + 1)
                print(f"[claude] API 调用失败 (attempt {attempt + 1}/{retries}): {e}，{wait}s 后重试", flush=True)
                time.sleep(wait)
            else:
                raise


def _load_prompt(filename: str) -> str:
    path = PROMPT_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ============ 万象部门经营分析周会（旧）名单 ============
WEEKLY_MEETING_PARTICIPANTS = ["徐超", "陈俊", "刘斯佳", "李肖然", "孟祥楠", "熊曼佚", "郑文浩", "夏晓童", "孙浩然"]

# ============ 品类周会：汇报人固定分工表（姓名, 负责板块） ============
PINLEI_ROSTER = [
    ("熊曼佚", "增效组数据"),
    ("潘琳心", "电脑办公品类数据（含组装机、配件、内存条、显卡、CPU、固态硬盘、显示器、鼠标键盘）"),
    ("刘亚婷", "摄影摄像品类数据（含数码相机、无人机）"),
    ("韩尹", "智能数码、探索品类、旧衣品类数据"),
    ("马保辉", "商家招商情况"),
    ("陈俊", "孵化组数据"),
    ("张金宇", "名酒品类数据"),
    ("陈劲松", "运动户外品类数据"),
    ("张建伟", "电动车、盲盒品类数据"),
    ("付京京", "健身器材品类招商"),
    ("吴旭", "运动户外品类招商"),
]


def _pinlei_weekly_block() -> str:
    """品类周会专属：汇报人固定分工表 + 议题组织规则。"""
    roster_table = "\n".join(f"| {name} | {duty} |" for name, duty in PINLEI_ROSTER)
    names = "、".join(name for name, _ in PINLEI_ROSTER)
    return f"""
---

# ⚠️ 本场是【品类周会】——汇报人固定分工表（最高优先级）

本场会议的参会汇报人**只可能是以下 {len(PINLEI_ROSTER)} 人**：{names}
他们各自的固定负责板块如下。议题汇报人必须严格从此表匹配，**禁止张冠李戴，禁止使用表外姓名**：

| 汇报人 | 负责板块 |
|---|---|
{roster_table}

执行规则：
1. **议题按上表"负责板块"拆分归类**，每个议题标题末尾用（xxx汇报）标注对应汇报人，汇报人必须来自上表 {len(PINLEI_ROSTER)} 人。
2. 逐字稿里的"说话人1/说话人2/说话人N"是飞书妙记占位符，**不是真实姓名**。根据该段讨论的品类/板块内容，映射到上表对应汇报人；无法判断时保留"说话人N"，**不要凭空编造姓名**。
3. 近音字优先匹配表内姓名（如"亚亭/亚婷"→刘亚婷，"金宇/金玉"→张金宇，"保辉/宝辉"→马保辉，"建伟/建为"→张建伟，"京京/晶晶"→付京京，"琳心/林新"→潘琳心，"韩尹/韩寅"→韩尹）。
4. "决策事项""待办事项"表格的负责人列：必须是上表 {len(PINLEI_ROSTER)} 人之一，或写"待定"，**禁止出现表外姓名**。
5. 特别注意区分"品类数据"和"品类招商"：**运动户外**有陈劲松（数据）和吴旭（招商）两人；**健身器材招商**是付京京；整体商家招商归马保辉。招商类内容优先归对应招商负责人。
6. **本场额外列席（非板块汇报人）**：除上表 {len(PINLEI_ROSTER)} 位汇报人外，**徐超**（会议 leader，负责拍板决策）和**李肖然**也参加本场品类周会。徐超、李肖然可以作为"决策事项/待办事项"的负责人；但**议题的板块汇报人仍严格按上表 {len(PINLEI_ROSTER)} 人**，不要把徐超/李肖然标为某个品类议题的汇报人（除非逐字稿明确是他俩在汇报该板块）。
7. **严禁使用以下万象周会人员**：刘斯佳、孟祥楠、郑文浩、夏晓童、孙浩然 **不参加本场品类周会**，严禁写入本场纪要的任何位置（参会人、议题汇报人、决策/待办负责人）。下方业务术语表里"九-A、周会专属"小节的人名分工只适用于万象周会，**对本场品类周会一律无效**，以上表为准。
8. **参会人字段**：若输出中需要列参会人，只列上表 {len(PINLEI_ROSTER)} 位汇报人 + 徐超、李肖然，不要添加其他任何姓名。

---

# ⚠️ 本场是【品类周会】——议题组织结构（最高优先级）

按上表分工，将会议内容拆分为若干议题，标题格式：`### N. <板块/品类名称>（<汇报人>汇报）`。每个议题内部按"背景 / 讨论要点 / 结论"三段式组织。

**内容归属规则**：
- 各品类的估价、下单、成交、价格策略、质检模板、新品节奏 → 归对应"品类数据"汇报人
- 服务商招商、建联、比价、签约 → 归对应招商负责人（运动户外招商=吴旭、健身器材招商=付京京、整体商家招商=马保辉）
- 孵化品类整体进展 → 陈俊；增效、转化提效类 → 熊曼佚
- **数码相机 / 相机 / 摄像机 → 刘亚婷（摄影摄像），严禁归韩尹**：韩尹负责的"智能数码"指电子书、VR、投影仪、扫地机器人等探索类数码产品，**不包含相机**；不要因为"数码相机"带"数码"二字就误归到韩尹的"智能数码"
- 如果某发言人讲到别人板块的事，按"事的归属"而非"说话人"决定放哪个议题

**待办事项要求（关键）**：
- 待办必须**尽可能详尽**，把会议中所有具体任务、跟进项全部列出，每条有明确负责人和截止时间，**不合并、不遗漏**
- 上周遗留仍在进行标注"进行中"，新增标注"待开始"

**决策与待办全局汇总**：
- 必须完整输出 6 大节：会议目标 / 关键讨论点 / 决策事项 / 待办事项 / 未解决问题 / 备注
- "三、决策事项"和"四、待办事项"必须是**全局汇总表格**，把所有议题里的决策/待办抽取到表里，**不允许省略**
"""


def _wanxiang_weekly_block() -> str:
    """万象部门经营分析周会专属：9 人名单强约束 + 固定汇报板块。"""
    names = "、".join(WEEKLY_MEETING_PARTICIPANTS)
    return f"""
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


def _build_system_prompt(meeting_topic: str = "") -> str:
    output_format = _load_prompt("output_format.md")
    glossary = _load_prompt("business_glossary.md")

    # 会议类型判断：品类周会走 11 人分工表，万象部门周会走 9 人名单
    is_pinlei = "品类" in meeting_topic
    is_wanxiang_weekly = any(kw in meeting_topic for kw in ["万象", "经营分析", "部门周会"])
    is_weekly = any(kw in meeting_topic for kw in ["周会", "周例会", "例会"])

    if is_pinlei:
        weekly_block = _pinlei_weekly_block()
    elif is_wanxiang_weekly or is_weekly:
        weekly_block = _wanxiang_weekly_block()
    else:
        weekly_block = ""

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
    """一次性整篇提交逐字稿，直接生成完整会议纪要。返回 {summary: 摘要, full: 完整版, meeting_topic}。

    DeepSeek-v4-pro 上下文 1M，逐字稿整篇提交即可，无需分批（分批会割裂议题、丢失跨段上下文）。
    """
    system_prompt = _build_system_prompt(meeting_topic)
    print(f"[claude] 逐字稿 {len(transcript)} 字符，一次性整篇提交生成纪要...", flush=True)

    user_content = f"【会议主题】{meeting_topic}\n\n" if meeting_topic else ""
    if auto_summary:
        user_content += f"【飞书自动生成的纪要（仅供参考）】\n{auto_summary}\n\n"
    user_content += f"【会议逐字稿（全文）】\n{transcript}\n\n"
    user_content += "请基于以上完整逐字稿，严格按照系统提示中的格式要求，生成完整版会议纪要（Markdown 格式）。\n【重要提醒】输出必须包含完整6节（一至六），决策事项和待办事项的表格绝不能省略。"

    response = _call_claude(
        model=CLAUDE_MODEL,
        max_tokens=24000,  # 完整6节纪要 + 推理模型思维链，给足避免正文截断
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    full_minutes = response.content[0].text
    print(f"[claude] 完整纪要生成完成，{len(full_minutes)} 字符", flush=True)

    # 基于完整纪要生成简短摘要（群消息用，300字以内）
    summary_prompt = f"""基于以下完整会议纪要，生成一份简短摘要（3-5条核心要点）。

要求：
- 每条一行，以 ✅ 开头
- 优先保留：决策事项、明确的 Action（带责任人和 DDL）、核心数据结论
- 格式：✅ 结论内容（@责任人 DDL）
- 客观陈述，不用主观评价词
- 总长度不超过300字

会议纪要：
{full_minutes[:10000]}"""

    summary_response = _call_claude(
        model=CLAUDE_MODEL,
        max_tokens=4000,  # 推理模型：思维链会占用额度，摘要正文才 300 字但要留足思维链空间
        messages=[{"role": "user", "content": summary_prompt}],
    )
    summary = summary_response.content[0].text

    return {"summary": summary, "full": full_minutes, "meeting_topic": meeting_topic}
