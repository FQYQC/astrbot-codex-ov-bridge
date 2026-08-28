# Personal AI QQ Bridge

本仓库保存可复现的部署代码：普通 QQ 经 NapCat/OneBot v11 接入 AstrBot，AstrBot 插件直接调用本机 Codex CLI，并使用 OpenViking 保存隔离的长期记忆。它不使用 VikingBot，不配置 OpenAI-compatible Provider，也不需要额外 OpenAI API Key。

## 安全边界

- AstrBot WebUI 只监听 `127.0.0.1:6185`，NapCat WebUI 只映射到 `127.0.0.1:6099`。
- OneBot 服务只监听 Docker bridge 网关 `172.30.0.1:6199`，随机 token 不进入 Git。
- Codex 固定使用 `/home/ubuntu/.local/bin/codex exec`、`gpt-5.6-luna` 和 `workspace-write` sandbox。服务使用独立的 `astrbot/codex-home/` 保存 thread，只通过只读符号链接引用现有登录文件，不复制它。
- Bridge 默认拒绝所有 QQ 用户、关闭群聊；真实使用前必须在 WebUI 填 `qq_owner_ids`。
- OpenViking 为每个 QQ 用户创建独立 API key；QQ 号和 session ID 只以单向哈希标识进入记忆服务。
- 含 token、Cookie、OAuth、认证文件名或疑似长密钥的回合不会写入记忆。

## 当前固定版本

见 `versions.lock`。AstrBot 由 uv/Python 3.12 独立安装；NapCat 镜像固定到 digest。Codex CLI 和 OpenViking 由迁移目标主机预先安装/恢复，本仓库不会复制它们的认证数据。

## 访问本机 WebUI

从 Mac 建立隧道：

```bash
ssh -N -L 6099:127.0.0.1:6099 -L 6185:127.0.0.1:6185 ubuntu@YOUR_VPS_IP
```

浏览器访问 `http://127.0.0.1:6185` 和 `http://127.0.0.1:6099`。AstrBot 首次密码保存在运行数据中，不在本仓库；需要重置时在 VPS 上交互执行 `/home/ubuntu/personal-ai/astrbot/bin/astrbot password`。

在 AstrBot 的插件配置中打开 `Codex Bridge`：把自己的 QQ 号填入 `qq_owner_ids`，保持 `group_chat_enabled=false`，保存后重载插件。所有者会自动获得使用权限；无需重复填普通白名单。

## 迁移与快速安装

新服务器先安装 Docker/Compose 和 Codex CLI，并完成 ChatGPT 订阅登录；恢复 OpenViking 配置与数据后，将本仓库放到 `/home/ubuntu/personal-ai`，执行：

```bash
./deployment/install.sh
```

完成 NapCat 扫码登录后执行：

```bash
./deployment/finalize_after_qq_login.sh
./deployment/verify.sh
```

这些脚本不会迁移或提交登录态。需要单独加密备份的运行目录包括：

- `astrbot/data/` 与 `astrbot/secrets/`
- `napcat/config/`、`napcat/qq/` 与 `napcat/secrets/`
- `openviking/data/` 与 `openviking/ollama/`

不要将这些目录上传到 GitHub；迁移时使用独立的加密备份通道。`~/.codex/auth.json` 永远不要放入本仓库或普通备份。

## 开发与验证

插件源码位于 `plugins/astrbot_plugin_codex_bridge/`，以符号链接加载到 AstrBot 运行目录。常规检查运行 `./deployment/verify.sh`。真实 Codex/OpenViking 冒烟脚本位于插件的 `tests/` 下，它们只输出布尔测试结果，不输出 thread ID、API key 或消息日志。
