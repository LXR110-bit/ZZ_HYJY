# 飞书会议纪要自动化机器人

飞书会议结束后自动拉取妙记逐字稿，调用 Claude API 生成结构化会议纪要，发送到飞书群并创建详细文档。

## 核心流程

1. 监听飞书会议结束事件（WebSocket 长连接）
2. 拉取妙记逐字稿
3. Claude 根据业务术语表修正识别错误 + 生成结构化纪要
4. 发送摘要到飞书群 + 创建完整版飞书文档

## 项目结构

```
feishu-meeting-bot/
├── main.py                 # 入口：启动长连接事件监听
├── config.py               # 环境变量加载
├── handlers/
│   └── meeting_ended.py    # 会议结束事件处理
├── services/
│   ├── feishu.py           # 飞书 API 封装
│   └── claude.py           # Claude API 封装
├── prompts/
│   ├── output_format.md    # 会议纪要输出格式约束
│   └── business_glossary.md # 业务术语表（语音识别纠正）
└── requirements.txt
```

## 部署

### 本地运行

```bash
cp .env.example .env
# 填入 .env 的配置
pip3 install -r requirements.txt
python3 main.py
```

### 服务器常驻

```bash
nohup python3 main.py > bot.log 2>&1 &
```

## 飞书侧配置

1. 开发者后台创建自建应用
2. 申请权限：
   - `vc:meeting.all_meeting:readonly`
   - `vc:record:readonly`
   - `minutes:minutes.transcript:export`
   - `minutes:minutes.media:export`
   - `im:message` / `docx:document`
3. 事件订阅：`vc.meeting.all_meeting_ended_v1`（长连接模式）
4. 发布应用并加入目标群聊
