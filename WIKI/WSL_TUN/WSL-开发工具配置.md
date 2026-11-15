# WSL 开发工具配置（可选）

这是[迁移文档入口](README.md)的补充：先完成 WSL 基础设置和全流量代理，再在目标 WSL 内安装 Linux 版开发工具。以下命令分段在同一个 Bash 终端执行；本文记录命令，没有替你运行安装或登录。

源机器在 2026-11-13 使用 Node.js `24.15.0`、Codex `0.169.0`、Claude Code `2.1.325`。这些是核对用的版本快照，新机器可以使用官方当前版本。源机器的 Claude 来自 npm；本指南使用官方推荐的原生安装方式。

## 1. 准备下载环境

```bash
source "$HOME/.bashrc"
xq_proxyon
xq_proxystatus
sudo apt update
sudo apt install -y ca-certificates curl unzip less nano
tool_setup_dir=$(mktemp -d "${TMPDIR:-/tmp}/wsl-tools.XXXXXX")
```

确认状态为 ON 后继续。这里依靠已部署的 WSL TUN，不需要为 npm、uv 或 CLI 再配置 `HTTP_PROXY`。在新终端中，开关继承当前 WSL 状态；完整重启 WSL 后默认 OFF，下载前需重新开启。

安装脚本先下载到文件，再查看、执行。`less` 按 `q` 退出；遇到下载错误应先检查代理状态，不要继续执行空文件。

## 2. 安装 Linux fnm、Node.js 和 npx

[fnm 官方安装说明](https://github.com/Schniz/fnm#installation)支持指定安装目录和 `--skip-shell`，便于自己检查 shell 初始化内容。

```bash
curl -fLsS https://fnm.vercel.app/install -o "$tool_setup_dir/fnm-install.sh"
less "$tool_setup_dir/fnm-install.sh"
bash "$tool_setup_dir/fnm-install.sh" --install-dir "$HOME/.local/share/fnm" --skip-shell
nano "$HOME/.bashrc"
```

检查 `.bashrc` 是否已有 fnm 初始化；已有时更新原段落，不要重复添加。没有时，在文件末尾加入一次：

```bash
export PATH="$HOME/.local/bin:$HOME/.local/share/fnm:$PATH"
if command -v fnm >/dev/null 2>&1; then
    eval "$(fnm env --shell bash)"
fi
```

不复制另一台机器写死的 `/home/chris` 路径。保存后执行：

```bash
source "$HOME/.bashrc"
fnm install 24
fnm default 24
fnm use 24
node --version
npm --version
npx --version
node -p 'process.platform'
```

最后一项应为 `linux`。这里选择 Node 24 系列；如确需源机器的精确版本，可将三个 `24` 都改为 `24.15.0`。随后 npm 全局安装位于当前用户的 fnm 目录，无需 `sudo npm`。

## 3. 安装 uv / uvx

`fetch` MCP 使用 `uvx`。[uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)提供 Linux 安装脚本：

```bash
curl -fLsS https://astral.sh/uv/install.sh -o "$tool_setup_dir/uv-install.sh"
less "$tool_setup_dir/uv-install.sh"
sh "$tool_setup_dir/uv-install.sh"
export PATH="$HOME/.local/bin:$PATH"
uv --version
uvx --version
command -v node npx uvx
```

默认安装位置是 `~/.local/bin`，上一节的 `.bashrc` 已覆盖该路径；若安装器报告其他目录，按实际目录调整。不要单独运行 MCP 启动命令来测试版本，它们可能进入等待客户端连接的状态。

## 4. 安装与登录 Codex

按 [Codex 官方说明](https://github.com/openai/codex#installation)，在这个已初始化 Node 的 WSL 终端执行：

```bash
npm install -g @openai/codex
codex --version
codex login
codex login status
```

使用目标机器自己的账号登录。Windows 互操作已关闭时，手动把显示的登录网址复制到浏览器，不从 WSL 启动 Windows 命令。若浏览器回调不可用，可在支持该方式的账号上尝试 `codex login --device-auth`；先用 `codex login --help` 核对当前版本支持的选项。

## 5. 安装与登录 Claude Code

[Claude Code 官方安装说明](https://code.claude.com/docs/en/setup)推荐原生安装，这里选择 stable 通道：

```bash
curl -fLsS https://claude.ai/install.sh -o "$tool_setup_dir/claude-install.sh"
less "$tool_setup_dir/claude-install.sh"
bash "$tool_setup_dir/claude-install.sh" stable
export PATH="$HOME/.local/bin:$PATH"
claude --version
claude auth login
claude auth status
```

用开通 Max 的 Claude 账号完成官方登录，按终端提示手动打开网址或输入回传代码。不要为了使用 Max 而设置 `ANTHROPIC_API_KEY` 或复制其他服务商的 `ANTHROPIC_BASE_URL`；这些配置可能改变认证或请求去向。原生安装器有自动更新机制，版本可能与源机器不同。

## 6. 配置 Codex 上下文与 MCP

编辑目标机器自己的配置；已有配置先备份，再合并以下字段，不要整份覆盖：

```bash
mkdir -p "$HOME/.codex"
if [ -f "$HOME/.codex/config.toml" ]; then
    cp -p "$HOME/.codex/config.toml" "$HOME/.codex/config.toml.bak.$(date +%Y%m%d-%H%M%S)"
fi
touch "$HOME/.codex/config.toml"
chmod 600 "$HOME/.codex/config.toml"
nano "$HOME/.codex/config.toml"
```

下面两项是顶层字段，必须放在所有 `[表名]` 之前；同名字段和 MCP 表只保留一份。Context7 的占位符需换成你自己的 key，或先删除该服务器配置，待取得 key 后再添加。

```toml
model_context_window = 1000000
model_auto_compact_token_limit = 500000

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
env = { CONTEXT7_API_KEY = "REPLACE_WITH_YOUR_OWN_KEY" }
startup_timeout_sec = 60

[mcp_servers.sequential-thinking]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-sequential-thinking"]
startup_timeout_sec = 60

[mcp_servers.fetch]
command = "uvx"
args = ["mcp-server-fetch"]
startup_timeout_sec = 60
```

参考：[Codex 配置项](https://learn.chatgpt.com/docs/config-file/config-reference)、[Context7 的 Codex 配置](https://context7.com/docs/clients/codex)、[官方 MCP 服务器仓库](https://github.com/modelcontextprotocol/servers)。这里使用 Linux 终端已初始化的 `PATH` 查找 `npx` / `uvx`；修改 Node 默认版本后应重新打开终端，再启动 Codex。

不要加入已被忽略的 `disable_response_storage` 或 `mcp_servers.<名称>.type`。上述 MCP 由命令启动，无需 `type = "stdio"`。首次启动会下载包，需保持 TUN ON；60 秒只用于 MCP 启动等待，不是代理重试机制。

`1000000` 是申请的窗口大小，不能扩大模型或服务端实际上限。源机器当日模型目录中 `gpt-6-astra` 的上限为 `872000`，不是所有新模型的统一限制；`500000` 是自动压缩阈值。目标机器应使用其账号实际可用的模型，避免复制源机器的私有 provider、服务地址或模型名称。

```bash
chmod 600 "$HOME/.codex/config.toml"
python3 - <<'PY'
from pathlib import Path
import tomllib
with (Path.home() / ".codex/config.toml").open("rb") as handle:
    tomllib.load(handle)
print("TOML 语法通过")
PY
codex mcp list
```

TOML 通过只说明文件语法正确；还要重启 Codex，确认没有未知配置告警，并在 `/mcp` 检查服务器是否成功连接。Codex `0.169.0` 另有 `codex app-server --strict-config --print-startup-config` 可检查配置；其他版本先查看帮助。不要使用不受该版本支持的 `codex --strict-config mcp list`。

## 7. 迁移后的核对

```bash
command -v node npx uvx codex claude
node -p 'process.platform'
file "$(readlink -f "$(command -v node)")"
file "$(readlink -f "$(command -v claude)")"
xq_proxystatus
```

命令路径应在 Linux 文件系统里；Node 平台应为 `linux`。使用 `file` 判断二进制格式：Linux 原生程序通常为 ELF，脚本则检查其启动器；不要仅凭扩展名判断。源机器 npm 包内的 `claude.exe` 实际就是 Linux ELF，Windows 可执行文件通常显示 PE32/PE32+。

需要重新登录时使用各工具的官方流程。迁移文档和脚本不应包含 `~/.codex/auth.json`、Claude 凭据文件、真实 Context7 key 或私有 provider 配置；分享状态输出前也应去除账号信息。

如果旧 Codex 后台进程仍持有旧 PATH 或配置，先退出已有会话，再在普通终端查看 `codex app-server daemon --help`；源机器版本支持 `codex app-server daemon restart`。最后重新启动 Codex 验证。不要在进行中的工作会话里强制重启共享后台进程。

工具安装完成后可执行 `xq_proxyoff` 恢复直连；这会切换整个 WSL 的网络状态，不是只影响当前终端。关闭终端本身不会执行 OFF。
