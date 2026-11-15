# 在另一台 WSL 从零复现

本页是新环境的执行入口，按顺序操作。历史审查和操作记录用于排错，不应按时间顺序全部重新执行。

本流程对应已经验证的 **Windows 11 + WSL2 + Ubuntu 24.04 + amd64 + NAT 网络 + systemd**，以及 sing-box **1.14.4**。其他发行版、ARM64 或 mirrored 网络需要另外适配；不能直接假定这份控制器适用。

目标行为：美式英语、洛杉矶时区；完整启动 Ubuntu/WSL 默认 OFF；手动 ON 后启用 WSL 全流量 TUN、代理 DNS 和防直连；同一环境中新开终端不改变状态；没有健康定时器。普通 OFF 网络可以联网，但具体网站是否可达由原网络决定。

## 1. 复制材料，不复制运行状态

把整个 `WIKI` 目录复制到目标 Linux 用户的 `~/WIKI`。建议使用 Linux 主目录，不在 Windows 挂载盘中运行安装器。

若使用打包文件，目标 WSL 中解压：

```bash
tar -xzf /path/to/WIKI-WSL-replay-2026-11-13.tar.gz -C "$HOME"
cd "$HOME/WIKI"
sha256sum -c SHA256SUMS
```

不要覆盖目标机器已有的同名 Wiki，先备份或换目录。此迁移包仅含文档和程序副本；不要复制原机器的 `/var/lib/xq-proxy`、`/run` 标记、现成 DNS 备份、`.credentials.json`、`auth.json`、完整私人 Codex 配置或整个用户主目录。

如果“另一套 WSL”是在**同一台 Windows 上的第二个发行版**，先确认网络是否与原发行版共享。共享同一网络命名空间时不要重复部署第二套，应使用唯一的管理入口或先建立独立网络；原发行版暂时 OFF 不代表重复部署安全。检测到现有 `xq-tun`、XQ 防火墙或保留路由时，安装器会拒绝；不要删除这些冲突来强行安装第二套，它们可能属于原发行版。

## 2. 准备 Windows 和 Karing

以下两条命令在 **Windows PowerShell** 执行：

```powershell
wsl --version
wsl --list --verbose
```

确认目标发行版的 VERSION 为 2，并记住它的准确名称。下文示例名称 `Ubuntu` 必须按目标机器实际修改。

在目标 Windows 的 Karing 中：

1. 连接你选择的可用节点。
2. 在“设置 → 端口”确认并配置 **全代理端口 4066**。规则端口、全直连端口不能替代它。
3. 开启允许 WSL/其他主机访问该代理的网络共享设置，使服务能通过 Windows 的 WSL 网关地址访问。
4. Windows 防火墙应允许对应 WSL 来源访问 Karing。SOCKS UDP 中继使用动态 UDP 端口，仅放行 TCP4066 不代表 UDP 已可用；按应用和实际 WSL 来源范围设置规则，不需要关闭整个防火墙。

当前归档开关固定使用 4066。若新机器必须使用另一个端口，需要同时审查控制器与显示说明后重新校验；安装器不会猜测或自动改 Karing 配置。

本方案在 WSL 内运行 TUN，不要求开启 Windows Karing 的 TUN。安装期间需要 Karing 上游可用。[Karing 端口说明](https://karing.app/en/tutorial/lan)

## 3. 设置 WSL 基础配置并完整重启

下面开始在 **目标 WSL 的非 root Linux 用户**中操作，该用户需要 `sudo` 权限：

```bash
id
cat /etc/os-release
uname -m
```

备份并编辑：

```bash
sudo cp -a /etc/wsl.conf "/etc/wsl.conf.before-xq-$(date +%Y%m%d-%H%M%S)"
sudoedit /etc/wsl.conf
```

若文件原本不存在，跳过备份命令。按现有节合并下列字段，不要重复创建同名节；原有 `[user]` 和其他自定义设置保留。

```ini
[boot]
systemd=true

[time]
useWindowsTimezone=false

[interop]
enabled=false
appendWindowsPath=false

[automount]
enabled=true
root=/mnt/
```

保存工作，在 **Windows PowerShell** 完整停止目标发行版：

```powershell
wsl --terminate Ubuntu
```

重新打开目标 WSL，再检查：

```bash
cat /proc/1/comm
wslinfo --networking-mode
test -c /dev/net/tun && printf 'TUN device OK\n'
ip -4 route
printf '%s\n' "$PATH" | tr ':' '\n'
```

预期 PID 1 为 `systemd`，网络模式为 `nat`，TUN 设备存在，Windows PATH 不再自动注入。若系统没有 `wslinfo` 或相关能力，先在 Windows 侧更新 WSL，再重新检查。

如果 Windows 侧已有 `.wslconfig` 将网络改为 mirrored，不要直接套用本控制器；切换 NAT 会影响该 Windows 主机上的 WSL 网络，应先评估再手动修改并完整重启。[微软 WSL 配置](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)

不需要因为禁用互操作就取消 Windows 磁盘挂载。不要把 `WSLInterop` 的共享 binfmt 注册状态单独当作是否允许 Windows 程序的证明；详见 [已有部署记录](WSL-全流量代理部署记录.md)。

## 4. 先建立安装用代理，再安装依赖

TUN 尚未安装，因此下载阶段显式指定 Karing，不依赖 `sudo` 继承代理变量。每次重新打开终端后，如还在安装阶段，重新执行本段变量设置：

```bash
XQ_BOOTSTRAP_HOST="$(ip -4 route show default | awk '{for (i=1;i<NF;i++) if ($i=="via") {print $(i+1); exit}}')"
test -n "$XQ_BOOTSTRAP_HOST"
XQ_BOOTSTRAP_PROXY="http://${XQ_BOOTSTRAP_HOST}:4066"
printf 'Karing 安装入口：%s:4066\n' "$XQ_BOOTSTRAP_HOST"
```

这里是普通变量，不是全局网络接管。不要写死旧机器的 `172.21.32.1`。

安装基础依赖：

```bash
sudo apt-get -o "Acquire::http::Proxy=$XQ_BOOTSTRAP_PROXY" -o "Acquire::https::Proxy=$XQ_BOOTSTRAP_PROXY" update
sudo apt-get -o "Acquire::http::Proxy=$XQ_BOOTSTRAP_PROXY" -o "Acquire::https::Proxy=$XQ_BOOTSTRAP_PROXY" install -y ca-certificates curl python3 iproute2 nftables locales tzdata util-linux passwd file
```

通过 Karing 查询一次出口，确认代理可达以及所选线路符合你的需求：

```bash
curl --disable --fail --show-error --connect-timeout 5 --max-time 15 --proxy "$XQ_BOOTSTRAP_PROXY" --noproxy '' https://www.cloudflare.com/cdn-cgi/trace
```

观察 `ip=` 和 `loc=`。这只是安装前的单次代理查询，不代表此时整台 WSL 已走 TUN。

如要同时复现当天系统升级，先阅读目标机器升级计划，再决定执行：

```bash
apt -s dist-upgrade
sudo apt -o "Acquire::http::Proxy=$XQ_BOOTSTRAP_PROXY" -o "Acquire::https::Proxy=$XQ_BOOTSTRAP_PROXY" dist-upgrade
sudo dpkg --audit
sudo apt-get check
```

## 5. 设置默认英文和洛杉矶时区

```bash
locale -a
```

若没有 `en_US.utf8`，用 `sudoedit /etc/locale.gen` 确保存在未注释的 `en_US.UTF-8 UTF-8` 行，再运行：

```bash
sudo locale-gen
```

设置系统默认值和时区：

```bash
sudo update-locale LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL
sudo timedatectl set-timezone America/Los_Angeles
sudo dpkg-reconfigure -f noninteractive tzdata
```

在用户自己的 `~/.bashrc` 交互式判断之后、所有代理函数之外加入下列两行；存在则修改原行，不重复追加：

```bash
export LANG="en_US.UTF-8"
export LANGUAGE="en_US:en"
```

验证：

```bash
unset LC_ALL
source ~/.bashrc
locale
env -u TZ date '+%Y-%m-%d %H:%M:%S %Z %z'
readlink -f /etc/localtime
```

`LC_ALL` 留空正常，各分类继承 LANG。不要永久强制 LC_ALL，也不要把语言设置放进 `xq_proxyon`。

`update-locale` 的默认文件位置随发行版版本而异；本机 `/etc/default/locale` 是到 `/etc/locale.conf` 的链接。保留目标机器原有布局，不要手动复制本机文件替换它的链接。

## 6. 下载并校验 sing-box

当前归档已验证的包是 amd64 的 sing-box **1.14.4**。下载器通过显式 Karing 代理下载官方资产，验证固定 SHA256 和 Debian 包名/版本/架构；它不会安装或更改网络。

```bash
python3 "$HOME/WIKI/scripts/xq-proxy/download-core.py" --proxy "$XQ_BOOTSTRAP_PROXY"
```

然后安装已经校验的本地包：

```bash
sudo apt-get -o "Acquire::http::Proxy=$XQ_BOOTSTRAP_PROXY" -o "Acquire::https::Proxy=$XQ_BOOTSTRAP_PROXY" install -y "$HOME/.cache/xq-proxy-deploy/sing-box_1.14.4_linux_amd64.deb"
sing-box version
```

不要开启包自带的 `sing-box.service`；本套流程使用单独的 `xq-proxy.service`。不要直接替换为最新版再假定配置兼容。若包下载失败，检查 Karing/GitHub 连接，不跳过 SHA256 检查。

ARM64 不能安装这个 amd64 包；本指南尚未在 ARM64 上验收，需另选匹配的官方包和校验值。[sing-box 安装说明](https://sing-box.sagernet.org/installation/package-manager/)

## 7. 安装配套控制器与 shell 函数

先运行无需 root、无需网络的离线回归测试：

```bash
python3 "$HOME/WIKI/scripts/xq-proxy/test_dns_reliability.py"
```

再从目标用户的终端运行只读前置检查：

```bash
sudo python3 "$HOME/WIKI/scripts/xq-proxy/install.py" --check
```

安装器会检查版本、systemd、NAT、TUN、内核防火墙能力、原 DNS、网卡 MTU、路由资源冲突和旧安装残留。它采用首次安装模式，拒绝覆盖原控制器、同名服务、已有 `.bashrc` 函数或运行状态；不要通过删除冲突项来绕过检查。

检查通过后安装：

```bash
sudo python3 "$HOME/WIKI/scripts/xq-proxy/install.py"
source ~/.bashrc
xq_proxystatus
```

安装器会：

- 自动创建非登录用户 `xq-proxy`，由系统分配 UID，**不固定为 999**。
- 安装 root 所有的控制器、两个 systemd 单元，以及用户自己的 `~/.config/xq/proxy.bash`。
- 备份原 `.bashrc`，只增加一次加载函数的入口。
- 仅启用完整启动默认 OFF 的复位服务；不启动 TUN、不改 DNS/路由/防火墙，也不装定时器。
- 输出备份目录和安装清单。初始状态应为 OFF。

安装失败时按输出的 `/var/backups/xq-proxy-before-install-.../installation.json` 检查已完成的文件步骤和原 `.bashrc` 备份。安装器不做破坏性的自动清理；部分安装后应先核对清单，不直接反复运行首次安装。

首次 ON 会按目标机器动态生成 `/etc/xq-proxy/sing-box.json` 和运行状态。**不要从旧机器复制这些已生成文件。**

## 8. 在目标机完成 ON/OFF 验收

先在明确的 OFF 状态验证原网络。如果原网络原本不通，应先处理基础网络，不能用开启代理掩盖 OFF 不可用：

```bash
xq_proxystatus
getent ahostsv4 ip.sb
curl --disable -4 --connect-timeout 5 --max-time 15 https://icanhazip.com
```

开启并验证：

```bash
xq_proxyon
xq_proxystatus
ip -4 route get 1.1.1.1
cat /etc/resolv.conf
curl --disable -4 --proxy '' --noproxy '*' --connect-timeout 5 --max-time 15 https://www.cloudflare.com/cdn-cgi/trace
```

预期：普通用户访问公网走 `xq-tun` / 表 20260，DNS 为 `172.30.255.2`，状态检查正常；即使 curl 不读取代理变量，服务端报告的出口仍为所选代理出口。不要要求新机器的 IP 必须等于本机历史 IP。

下面的检查需要管理员读取规则，但不会切换网络：

```bash
sudo nft list table inet xq_proxy
ip -6 route show table 20260
```

IPv6 应为 unreachable；当前实现明确阻断 IPv6。保持 ON，用普通用户运行 UDP 出口诊断：

```bash
python3 "$HOME/WIKI/scripts/xq-proxy/check-udp.py"
```

脚本通过普通 UDP socket 查询公开 STUN 服务，不使用应用代理变量；网络由 TUN 接管。对比它显示的 UDP 公网出口与上面的 HTTPS 出口，确认两者符合所选线路。TCP 和 UDP 可能使用不同出口，不能仅凭地址不同判定泄漏。

UDP 的端到端能力取决于目标 Windows 防火墙、代理节点和 STUN 服务。查询失败只能说明本次所选 STUN 查询未成功；查看 `--help` 可更换服务器复查，不要仅凭 SOCKS 握手成功就判定 UDP 正常。脚本只诊断，不切换开关或修改配置。

关闭并确认恢复：

```bash
xq_proxyoff
xq_proxystatus
getent ahostsv4 ip.sb
curl --disable -4 --connect-timeout 5 --max-time 15 https://icanhazip.com
```

预期 TUN 核心停止，自有策略规则和 guard 被移除，原 DNS 恢复，普通网络可用。`ip link show xq-tun` 此时应报设备不存在，这是期望结果。

## 9. 必做的完整重启验收

在目标 WSL 中手动 ON，然后保存工作。在 **Windows PowerShell** 中执行：

```powershell
wsl --terminate Ubuntu
```

再次打开该发行版，不执行 ON：

```bash
xq_proxystatus
getent ahostsv4 ip.sb
curl --disable -4 --connect-timeout 5 --max-time 15 https://icanhazip.com
```

预期默认 OFF 且普通联网可用。再手动 ON，新开第二个终端，状态应仍为 ON；新终端不能自动关闭代理。

这里只关闭终端窗口并不能证明 WSL 已完整停止。原机器已验证启动复位单元的动作，但此前没有完成整台 WSL 重启验收；因此新机器必须执行这一节，不能省略。

## 10. 故障定位与恢复

```bash
xq_proxystatus
sudo journalctl -u xq-proxy.service -n 80 --no-pager
sudo journalctl -u xq-proxy-boot.service -n 40 --no-pager
```

- `ON，但配置异常`：按具体提示检查 DNS、路由或备份；手动 `xq_proxyon` 可重新应用所选模式。
- 代理不可用：保持 ON 时，防直连规则会阻止回落；需要普通网络时明确执行 OFF。
- 原机器曾在 ON 时发现 resolver 被改回 WSL 默认值。新状态检查能够报告这类覆盖，但没有定时自动修复；若目标机重复出现，要采集当时文件及日志再定位。
- 不用 `ping` 单独证明远端连接或代理出口；以 DNS、HTTPS 服务端出口、路由和 UDP 实测为准。

即使函数没有加载，恢复入口仍可直接调用：

```bash
sudo /usr/local/sbin/xq-proxyctl off
```

不要清空全机 nftables 规则或删除所有策略路由。若需撤销安装，先 OFF，再根据安装清单只移除本方案文件、`.bashrc` 加载段及专用用户；不要恢复旧机器的状态文件。

## 11. 可选：Codex、Claude Code 和 MCP

基础 WSL/TUN 验收完成后，按 [开发工具配置](WSL-开发工具配置.md) 安装 Linux 版工具、登录自己的账号和配置 MCP。旧机器的现成 fnm、Node、uvx 不会因为复制 Wiki 自动出现在新机器上。

现有 [操作记录](2026-11-13-操作记录.md)、[部署记录](WSL-全流量代理部署记录.md) 保留了诊断过程。旧的环境变量版代理函数仅供历史参考，不要叠加到新 TUN 开关上。
