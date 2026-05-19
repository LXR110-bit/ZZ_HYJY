# 飞书机器人服务器部署清单

服务器信息：阿里云轻量应用服务器 `47.95.254.15`（Ubuntu 24.04）

> 等本地全流程跑通后再执行第 5 步启动服务。前 4 步可以先做。

---

## 1. 登录服务器

在本地 Mac 终端执行：

```bash
ssh root@47.95.254.15
```

第一次登录输 `yes` 确认指纹，再输服务器密码（在阿里云控制台"设置密码"那里设的）。

**忘记密码**：控制台 → 实例 → "设置密码" → 重置 → **重启服务器才生效**。

**登录成功标志**：提示符变成 `root@iZxxxx:~#`

---

## 2. 安装运行环境 + 拉取代码

登录服务器后，复制粘贴这一整段（大概 2-3 分钟）：

```bash
apt update && apt install -y python3 python3-pip python3-venv git vim && \
cd /opt && \
git clone https://github.com/LXR110-bit/ZZ_HYJY.git && \
cd ZZ_HYJY && \
python3 -m venv venv && \
source venv/bin/activate && \
pip install -r requirements.txt
```

**成功标志**：最后一行看到 `Successfully installed lark-oapi-x.x.x anthropic-x.x.x ...`

---

## 3. 上传 .env 配置

代码仓库里没有 .env（安全起见），需要手动创建：

```bash
cd /opt/ZZ_HYJY
vim .env
```

按 `i` 进入编辑模式，粘贴这些内容：

```
FEISHU_APP_ID=cli_aa8849a7f43a5bd6
FEISHU_APP_SECRET=OnSX5xfwimy7e4hLK7zZwdNlqvTSr3OS
FEISHU_CHAT_ID=oc_2952fa8c5ff83e7bf225a7d6ef4dd58b
CLAUDE_API_KEY=sk-b18b33dbe2c2b828d08dfae3718fce1ab7124ee0faada2e2cca884bbecb02c9f
CLAUDE_BASE_URL=https://v2.qixuw.com
CLAUDE_MODEL=claude-opus-4-6
```

按 `Esc`，输入 `:wq` 回车保存退出。

**验证**：`cat .env` 能看到上面的内容就 OK。

---

## 4. 配置 systemd 开机自启（推荐）

让服务崩溃后自动重启、开机自动运行。复制粘贴这段：

```bash
cat > /etc/systemd/system/feishu-bot.service << 'EOF'
[Unit]
Description=Feishu Meeting Minutes Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ZZ_HYJY
ExecStart=/opt/ZZ_HYJY/venv/bin/python3 /opt/ZZ_HYJY/main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/feishu-bot.log
StandardError=append:/var/log/feishu-bot.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable feishu-bot
```

**还不要启动**。等本地全流程跑通再走第 5 步。

---

## 5. ⚠️ 启动服务（等本地调通后再做）

### 前置动作：本地服务停掉

本地那个 `python3 main.py` 终端按 `Ctrl+C` 停掉。
同一个应用同一时间只能有一个长连接，两边同时跑事件会乱。

### 服务器上 git pull 最新代码

```bash
cd /opt/ZZ_HYJY
git pull
```

### 启动服务

```bash
systemctl start feishu-bot
```

---

## 6. 常用运维命令

```bash
# 查看服务状态
systemctl status feishu-bot

# 实时看日志（类似 tail -f）
journalctl -u feishu-bot -f

# 或看完整日志文件
tail -f /var/log/feishu-bot.log

# 重启服务
systemctl restart feishu-bot

# 停止服务
systemctl stop feishu-bot

# 拉取新代码并重启（本地改完 push 后用）
cd /opt/ZZ_HYJY && git pull && systemctl restart feishu-bot
```

---

## 7. 检查清单

部署完后按这个验证：

- [ ] `systemctl status feishu-bot` 显示 `active (running)` 绿色
- [ ] `journalctl -u feishu-bot -f` 能看到 `[main] 启动飞书长连接，等待会议结束事件...`
- [ ] 开一个测试会议结束后，日志里出现 `[main] 收到会议结束事件`
- [ ] 飞书群里收到纪要消息
- [ ] 重启服务器 `reboot`，5 分钟后 SSH 回去看 service 自动起来了

---

## 常见问题

**Q: SSH 连不上？**
- 检查阿里云安全组 22 端口是否开放（默认开）
- 密码是否设置正确，是否重启过实例

**Q: git clone 很慢？**
- GitHub 在国内访问慢，可以忍。如果超过 5 分钟，换成 Gitee 镜像
- 或者 `git config --global https.proxy` 设代理

**Q: pip install 卡住？**
- 换国内源：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

**Q: 启动后报错找不到模块？**
- 确认在 venv 里：`source venv/bin/activate` 后再 `pip list` 检查
- systemd 里写的是 `/opt/ZZ_HYJY/venv/bin/python3` 这个绝对路径，不依赖激活

**Q: 如何确认飞书事件推到服务器而不是本地？**
- 本地 `main.py` 进程必须停掉
- 服务器日志有 `[main] 启动飞书长连接` 就说明服务器在监听
