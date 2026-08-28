# Personal AI QQ Bridge

本仓库保存可复现的部署代码：普通 QQ 经 NapCat/OneBot v11 接入 AstrBot，AstrBot 插件直接调用本机 Codex CLI，并使用 OpenViking 保存隔离的长期记忆。它不使用 VikingBot，不配置 OpenAI-compatible Provider，也不需要额外 OpenAI API Key。

仓库内容与排除的运行数据详见 [`docs/REPOSITORY_CONTENTS.md`](docs/REPOSITORY_CONTENTS.md)。

## 安全边界

- AstrBot WebUI 只监听 `127.0.0.1:6185`，NapCat WebUI 只映射到 `127.0.0.1:6099`。
- OneBot 服务只监听 Docker bridge 网关 `172.30.0.1:6199`，随机 token 不进入 Git。
- Codex 固定使用 `/home/ubuntu/.local/bin/codex exec` 和 `workspace-write` sandbox，模型只允许 `gpt-5.6-luna` 与 `gpt-5.6-sol`，默认 Luna；reasoning effort 默认 `medium`。服务使用独立的 `astrbot/codex-home/` 保存 thread，只通过只读符号链接引用现有登录文件，不复制它。
- Bridge 默认拒绝所有 QQ 用户、关闭群聊；真实使用前必须在 WebUI 填 `qq_owner_ids`。
- OpenViking 为每个 QQ 用户及每个启用的 QQ 群创建彼此独立的 API key；QQ 号、群号和 session ID 只以单向哈希标识进入记忆服务。
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

所有者可以按 session 选择模型：`/codex_model luna|sol|default`。私聊和每个群分别保存选择；群聊命令仍需 `@` 机器人。`/codex_default luna|sol` 设置没有单独覆盖时使用的全局默认模型。普通白名单用户不能执行模型切换命令。

所有者也可以按 session 设置 reasoning effort：`/codex_effort none|low|medium|high|xhigh|max|default`。`/codex_effort_default none|low|medium|high|xhigh|max` 修改全局默认；已单独设置的私聊或群不受影响。`/codex_status` 会同时显示当前模型、effort 和 thread 状态。

仅在私聊且当前 effort 为 `medium`/`high`/`xhigh`/`max` 时，Bridge 会立即回复已开始或已排队（含模型和 effort），之后默认每 120 秒发送一次项目相关的 TODO 进度：具体列出已完成、正在进行和下一步。进度来自主 Codex 的 JSONL `todo_list` 与插件自身的阶段状态，再交给独立的 `gpt-5.6-luna`/`low` 只读临时会话整理；它不接收原始 QQ 消息、回复正文、命令输出、日志、路径或凭据。Luna 总结失败时自动回退到本地生成的详细 TODO，不影响主任务。`none`/`low` 以及所有群聊都不发进度消息，避免刷屏。

主任务仍限制为最多 2 个不同 session 并发、同一 session 串行；进度总结另有 2 个独立 Luna 槽位，因此最多可同时运行 2 个主任务和 2 个轻量总结任务。总结会话使用 `--ephemeral`、`read-only` sandbox，不占主任务队列。单次主任务超时可在 WebUI 配置为 10–3600 秒；当前部署使用 2400 秒，超时后 Bridge 会终止对应 Codex 进程而不是放任其后台继续。

QQ 文件会被复制到专用工作区的私有随机路径再交给 Codex 只读分析；单文件上限 20 MiB，每次最多 3 个且合计上限 40 MiB，暂存 7 天后清理。下载仅允许公网 HTTP(S) 目标，文件名、QQ 下载地址和暂存路径不写入 OpenViking。群文件仍要求同条消息 `@` 机器人。

群聊可由所有者在目标群内使用 `@机器人 /group_context on|off|status` 单独控制上下文。开启后会在内存中缓冲最近 100 条纯文本、默认保留 24 小时，并从 OpenViking 读回精确近期消息尾部与语义长期记忆，因此插件热重载或服务重启后不只依赖内存缓冲。每次最多向 Codex 注入 20,000 字符；合规纯文本串行、异步提交到该群独立的 OpenViking 长期记忆空间。图片、命令、疑似凭据、事件 ID 和 QQ 号元数据不进入记忆。不同群、私聊与群聊相互隔离，所有检索材料都作为不受信任的参考输入。

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
