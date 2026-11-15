# Ubuntu / Debian VPS：美式英语与洛杉矶时区复现指南

整理日期：2026-11-13（America/Los_Angeles）。

**在新 VPS 部署用户级 TUN，请使用 [一键部署指南](VPS-用户级TUN一键部署.md) 和 [便携安装包](scripts/xq-user-tun/README.md)。** 本文保留语言、时区等环境复现流程；Mico-system 的历史 TUN 安装器绑定原部署，不能作为新机器安装入口。

这份指南把当天在 WSL 中完成的设置改写成普通 Ubuntu / Debian VPS 可执行的流程。**VPS 适配内容是复现建议，并非今天已在另一台 VPS 执行的记录。** 今天的实际变更、Codex 配置与 WSL 代理函数见 [WIKI 目录](README.md)。

这里的“US 环境”指 `en_US.UTF-8`、洛杉矶时区及你选择的网络连接方式。语言和时区不会改变公网 IP 的所属地区，也不构成任何服务的账号安全保证。文档不保存密码、API Key 或登录令牌。

## 1. 确认系统并备份

以下命令在 **VPS 的 Linux shell** 中执行。适用 Ubuntu / Debian；其他发行版不要照搬 `apt` 和 `update-locale`。

```bash
cat /etc/os-release
locale
locale -a
readlink -f /etc/localtime
```

备份本次会涉及的已有配置：

```bash
backup_dir="$HOME/.local/state/us-env-backup/$(date +%Y%m%d-%H%M%S)"
mkdir -p -m 700 "$backup_dir"
if [ -f "$HOME/.bashrc" ]; then cp -p "$HOME/.bashrc" "$backup_dir/bashrc"; fi
if [ -e /etc/locale.conf ]; then cp -L /etc/locale.conf "$backup_dir/locale.conf"; fi
if [ -e /etc/default/locale ]; then cp -L /etc/default/locale "$backup_dir/default-locale"; fi
if [ -e /etc/timezone ]; then cp -L /etc/timezone "$backup_dir/timezone"; fi
readlink -f /etc/localtime > "$backup_dir/localtime-target.txt"
printf '备份目录：%s\n' "$backup_dir"
```

保留输出的备份目录。恢复时注意 `/etc/default/locale` 可能是软链接，不要直接用普通文件替换它。

## 2. 更新软件包

这是当天执行过的升级流程的 VPS 版本。先查看计划，尤其是准备删除的软件包；不同 VPS 的结果不会与本机完全一致。

```bash
sudo apt update
apt -s dist-upgrade
```

确认计划适合这台 VPS 后执行：

```bash
sudo apt dist-upgrade
sudo apt install locales tzdata curl
```

验证软件包状态：

```bash
sudo dpkg --audit
sudo apt-get check
```

`dpkg --audit` 正常时没有输出。若软件包因 phased updates（分阶段更新）暂缓，不需要为了“全部更新”强行绕过。

如果 `/run/reboot-required` 存在，保存工作并安排重启；VPS 重启会中断 SSH。普通 VPS 使用 Linux 的重启方式，不使用 `wsl --shutdown`。

## 3. 设置系统默认语言

先运行：

```bash
locale -a
```

如果已经有 `en_US.utf8` 或 `en_US.UTF-8`，可以跳过生成步骤。

如果没有，编辑 `/etc/locale.gen`：

```bash
sudoedit /etc/locale.gen
```

确保下列行存在且没有以 `#` 注释，然后生成 locale：

```text
en_US.UTF-8 UTF-8
```

```bash
sudo locale-gen
```

设置默认值：

```bash
sudo update-locale LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL
```

这里的无值参数 `LC_ALL` 表示**删除系统配置中的 LC_ALL 覆盖项**。默认不设置 `LC_ALL`，让未单独设置的 `LC_*` 分类继承 `LANG`。

不同版本的 `update-locale` 默认写入位置不同，可用 `update-locale --help` 查看。本机默认写 `/etc/locale.conf`，而 `/etc/default/locale` 是指向它的软链接。**不要在另一台 VPS 上强行建立同样的软链接，也不要同时写出互相冲突的两个配置文件。** 让该系统自己的 `update-locale` 管理默认文件即可。

若原配置还有 `LC_TIME`、`LC_NUMERIC` 等单项覆盖，相关分类会优先使用这些值。需要统一时，检查并移除对应旧覆盖，例如：

```bash
sudo update-locale LC_TIME LC_NUMERIC
```

只移除确实不需要的覆盖，不必清空全部系统配置。

## 4. 让每个 Bash 终端独立于代理使用英文

在 `~/.bashrc` 的交互式检查之后、代理函数之外添加以下两行；已经存在则修改原行，不重复追加：

```bash
export LANG="en_US.UTF-8"
export LANGUAGE="en_US:en"
```

如果代理函数中还有上述设置或 `export LC_ALL=...`，把语言设置移出代理函数，并删除长期导出 `LC_ALL` 的行。

在当前终端清理旧的 `LC_ALL`，然后加载：

```bash
unset LC_ALL
source ~/.bashrc
locale
```

预期结果：

```text
LANG=en_US.UTF-8
LANGUAGE=en_US:en
LC_CTYPE="en_US.UTF-8"
LC_TIME="en_US.UTF-8"
…其他没有单独覆盖的 LC_* 同样为 en_US.UTF-8…
LC_ALL=
```

`LC_ALL` 为空是正常结果。再开一个新 SSH 会话复查，**不执行任何代理开启命令**。如果个别分类仍不同，检查客户端传入或 shell 启动文件设置的 `LC_*`；不必为此修改 SSH 的登录认证或端口配置。

## 5. 设置洛杉矶时区

先确认时区数据文件存在：

```bash
test -f /usr/share/zoneinfo/America/Los_Angeles
```

对于运行 systemd 的 VPS：

```bash
sudo timedatectl set-timezone America/Los_Angeles
sudo dpkg-reconfigure -f noninteractive tzdata
```

第二条用于同步发行版的 tzdata 配置。本机曾出现 `/etc/localtime` 已更新但 `/etc/timezone` 仍旧的情况，因此执行了这一步。

**VPS 适配：没有 systemd 时的替代方式**，例如某些容器：

```bash
sudo ln -sfn /usr/share/zoneinfo/America/Los_Angeles /etc/localtime
sudo dpkg-reconfigure -f noninteractive tzdata
```

验证时排除当前进程的 `TZ` 环境变量，避免它掩盖系统设置：

```bash
readlink -f /etc/localtime
env -u TZ date '+%Y-%m-%d %H:%M:%S %Z %z'
```

预期链接指向 `America/Los_Angeles`。冬季通常显示 `PST -0800`，夏季显示 `PDT -0700`，由时区数据库自动处理。部分发行版不再使用 `/etc/timezone`；若该文件不存在，不必为了验证强行创建。

## 6. VPS 的代理配置方式

**本节是 VPS 适配，不要直接复制 WSL 的 Windows 网关探测方式。** 普通 VPS 的默认网关不是 Windows 宿主机，也不代表那里运行了代理。

如果 VPS 本身的出口已经符合你的使用需求，可以不配置应用层代理。若确实需要代理，先准备一个真实可达的 HTTP 代理服务，再填写实际主机和端口。

例如，**仅当这台 VPS 自己运行的 HTTP 代理确实监听 `127.0.0.1:4066` 时**，在当前 shell 使用：

```bash
export XQ_PROXY_HOST="127.0.0.1"
export XQ_PROXY_PORT="4066"
export http_proxy="http://${XQ_PROXY_HOST}:${XQ_PROXY_PORT}"
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$http_proxy"
export all_proxy="$http_proxy"
export ALL_PROXY="$http_proxy"
export no_proxy="localhost,127.0.0.1,::1"
export NO_PROXY="$no_proxy"
```

如果代理在远端，替换成它真实的地址和端口。不要把当天 WSL 的 `172.21.32.1` 或动态公网出口 IP 当作 VPS 代理地址。

在设置完变量的**同一个终端**启动需要使用代理的程序，例如 `claude`。这些变量影响当前 shell 及随后启动的子进程；它们不是整台 VPS 的网络接管方案，也不会自动改变其他 SSH 会话或已运行程序的环境。

如需账号认证，应使用代理服务支持的凭据管理方式；不要把真实密码写入这份 WIKI 或共享脚本。

关闭当前 shell 的代理：

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
unset all_proxy ALL_PROXY
unset no_proxy NO_PROXY
```

不需要通过代理开关改变语言或时区。

## 7. 验证实际公网出口

在开启与关闭代理后分别运行以下命令，使用当前环境变量发起 HTTPS 请求；主查询服务失败时换用备用服务：

```bash
if public_ip="$(curl --disable -4 --fail --silent --connect-timeout 3 --max-time 8 https://api.ipify.org)"; then
  printf '公网出口 IP：%s\n' "$public_ip"
elif public_ip="$(curl --disable -4 --fail --silent --connect-timeout 3 --max-time 8 https://icanhazip.com)"; then
  printf '公网出口 IP：%s\n' "$public_ip"
else
  printf '公网出口 IP：获取失败，请检查连接或查询服务。\n'
fi
```

保留正常证书校验，不添加 `-k` / `--insecure`。不要把两次公网 IP 相同直接判定为代理失效，也不要把“查询成功”理解为所有程序都会走相同线路。

如果 Claude Code 已安装，可检查所用认证方式：

```bash
claude --version
claude auth status
```

Max 订阅应使用相应 Claude 账号登录。认证状态输出可能包含邮箱、组织等信息，分享检查结果时先脱敏；不要复制原机器的 `.credentials.json` 或其他登录令牌到 WIKI。Claude Code 的代理变量读取时机和支持范围见 [官方网络说明](https://code.claude.com/docs/en/network-config)。

## 8. 普通 VPS 不需要复制的 WSL 设置

以下内容只适用于 Windows 上的 WSL：

- `/etc/wsl.conf` 的 `[interop]`、`[automount]`、`[user]` 和 Windows 时区同步控制。
- 禁止 Windows `.exe` 互操作、停止追加 Windows PATH。
- 挂载 Windows 的 C/D/E 盘到 `/mnt/c`、`/mnt/d`、`/mnt/e`。
- 用 WSL 默认路由推断 Windows 宿主机 IP。
- 在 Windows PowerShell 运行 `wsl --terminate Ubuntu`。

普通 VPS 上完成语言、时区和实际需要的网络配置即可。不要在 VPS 上创建这些 WSL 配置来“模拟”它们。

## 9. 完成后的核对顺序

1. 新建 SSH 会话，不开代理，运行 `locale`：默认应为 `en_US.UTF-8`，`LC_ALL` 为空。
2. 运行 `env -u TZ date` 和 `readlink -f /etc/localtime`：系统时区应为洛杉矶。
3. 在使用代理的终端检查出口 IP，确认所填代理主机和端口真实可达。
4. 关闭代理，再检查直连是否可用，并记录两种连接方式的结果。
5. Codex、Claude Code 的安装、账号登录和模型限制单独核对，不从另一台机器复制密钥或身份凭据。

本指南不安装或升级 Codex / Claude Code。当天记录中的版本号、模型上下文上限和出口 IP 都是当时的观测值，不应当作新 VPS 的固定预期。
