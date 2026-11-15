# 在另一台 WSL 从零复现

本页是新环境的执行入口，按顺序操作。历史审查和操作记录用于排错，不应按时间顺序全部重新执行。

本流程对应已经验证的 **Windows 11 + WSL2 + Ubuntu 24.04 + amd64 + NAT 网络 + systemd**，以及 sing-box **1.14.4**、Ubuntu 软件源的 conntrack **1.4.8**。其他发行版、ARM64 或 mirrored 网络需要另外适配；不能直接假定这份控制器适用。

目标行为：美式英语、洛杉矶时区；完整启动 Ubuntu/WSL 默认 OFF；手动 ON 后启用 WSL 全流量 TUN、代理 DNS 和防直连，其中应用 DNS 在网络层接管，不改写 `/etc/resolv.conf`；同一环境中新开终端不改变状态；没有健康定时器。普通 OFF 网络可以联网，但具体网站是否可达由原网络决定。

## 1. 获取材料，不复制运行状态

在目标 WSL 的 Linux 主目录克隆本仓库，不在 Windows 挂载盘中运行安装器。下文引用这些材料的命令都通过变量 `XQ_WSL_TUN` 指向仓库中的 `WIKI/WSL_TUN` 目录：

```bash
git clone https://github.com/soloxyq/vpsinit.git "$HOME/vpsinit"
XQ_WSL_TUN="$HOME/vpsinit/WIKI/WSL_TUN"
cd "$XQ_WSL_TUN"
sha256sum -c SHA256SUMS
```

`SHA256SUMS` 中的路径相对 `WSL_TUN` 目录，因此要在该目录执行校验。`XQ_WSL_TUN` 是普通 shell 变量：重新打开终端后（包括第 3 节完整重启之后），先重新执行上面第二行；仓库放在其他位置时，按实际路径设置。

材料最早在第 6 节使用。若目标 WSL 暂时无法直连 GitHub，可先完成第 2–4 节，再让克隆显式使用第 4 节的 Karing 入口，随后照常执行上面其余三行；目标系统没有 `git` 时，可把 `git` 加入第 4 节的安装命令：

```bash
git -c "http.proxy=$XQ_BOOTSTRAP_PROXY" clone https://github.com/soloxyq/vpsinit.git "$HOME/vpsinit"
```

从其他机器复制时，复制在 Linux 中得到的完整克隆；Windows 版 Git 可能把换行改为 CRLF，导致校验失败。

`WSL_TUN` 中的控制器是本地 DNS 接管版本的 2026-11-15 修订，见 [配套脚本说明](scripts/xq-proxy/README.md)。这次修订改了两处：从干净的 OFF 开启时先预检、后改网络；只有迁移旧版 TUN resolver 时才依赖原 DNS 备份。它通过了离线测试、无特权网络命名空间中的演练和 root 下的隔离命名空间测试，还没有部署到原机器，也没有在任何宿主上做过 ON/OFF 验收；原机器验收过的是 2026-11-14 版本。按本指南安装的就是这份修订版，第 8、9 节的验收不能省略。

不要改用 `WIKI-WSL-replay-2026-11-13.tar.gz` 迁移包或其他旧副本：旧控制器 ON 时改写 `/etc/resolv.conf`，WSL 重建该文件后，DNS 会被它自己的防直连规则拒绝。

不要覆盖目标机器上已有的同名目录，先备份或换目录。仓库只含文档和程序副本；不要复制原机器的 `/var/lib/xq-proxy`、`/run` 标记、现成 DNS 备份、`.credentials.json`、`auth.json`、完整私人 Codex 配置或整个用户主目录。

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

不需要因为禁用互操作就取消 Windows 磁盘挂载。不要把 `WSLInterop` 的共享 binfmt 注册状态单独当作是否允许 Windows 程序的证明；详见 [2026-11-13 复查报告](2026-11-13-复查报告.md) 的“WSL 互操作检查标准更正”一节。

## 4. 先建立安装用代理，再安装依赖

TUN 尚未安装，因此下载阶段显式指定 Karing，不依赖 `sudo` 继承代理变量。每次重新打开终端后，如还在安装阶段，重新执行本段变量设置以及第 1 节的 `XQ_WSL_TUN`：

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
sudo apt-get -o "Acquire::http::Proxy=$XQ_BOOTSTRAP_PROXY" -o "Acquire::https::Proxy=$XQ_BOOTSTRAP_PROXY" install -y ca-certificates curl python3 iproute2 nftables conntrack locales tzdata util-linux passwd file
```

`iproute2` 提供 `ip` 和 `ss`；`conntrack` 提供控制器固定调用的 `/usr/sbin/conntrack`，用于 ON 前检查连接跟踪资源、OFF 时精确清理本功能的 DNS 映射。缺少它时控制器拒绝开启。

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
python3 "$XQ_WSL_TUN/scripts/xq-proxy/download-core.py" --proxy "$XQ_BOOTSTRAP_PROXY"
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
python3 -I "$XQ_WSL_TUN/scripts/xq-proxy/test_dns_reliability.py"
```

它只使用临时文件和模拟命令层，最后应显示 `OK`。

建议再运行隔离网络命名空间测试。它需要 root，在新建的、只有 `lo` 的临时网络命名空间中用 `scripts/xq-proxy` 里的控制器安装真实的 nftables 规则，检查当前内核能否完成 DNS 接管、DNS 映射清理和故障时防直连。它不改宿主的路由、resolver 或服务，但首次运行可能加载 dummy 内核模块，在宿主留下一个未启用、无地址的 `dummy0` 网卡（不影响流量）；可先用 `ip -br link show dummy0` 记下它是否已存在，原本没有的话测试后用 `sudo ip link del dummy0` 删除：

```bash
cd "$XQ_WSL_TUN/scripts/xq-proxy"
sudo unshare --net python3 -I tests/netns-check.py
```

每组检查通过时输出一行 `PASS:`；任何一项失败都会报错退出。失败时不要继续安装，先确认内核以及 `nft`、`conntrack` 是否可用。

再从目标用户的终端运行只读前置检查：

```bash
sudo python3 "$XQ_WSL_TUN/scripts/xq-proxy/install.py" --check
```

安装器会检查版本、systemd、NAT、TUN、依赖命令（含 `ss` 和 `/usr/sbin/conntrack`）、内核防火墙能力（含 DNS 接管所需的 conntrack zone/mark 和 inet NAT）、原 DNS（至少一个 IPv4 nameserver）、网卡 MTU、路由资源冲突、DNS 接管资源冲突和旧安装残留。它采用首次安装模式，拒绝覆盖原控制器、同名服务、已有 `.bashrc` 函数或运行状态；不要通过删除冲突项来绕过检查。

DNS 接管资源是指：其他 nft 规则不能使用 conntrack mark/zone（iptables 规则不在自动检测范围内，包括 iptables-nft 兼容层的 CONNMARK、CT --zone、connmark，需自行确认），conntrack zone `20262` 在首次安装时必须为空，本地 DNS 端口 `1053`（TCP/UDP）不能被其他程序占用。每次 ON 在改动网络之前也会做同类检查，冲突时拒绝开启；同样不要删除其他程序的规则或进程来强行开启。

检查通过后安装：

```bash
sudo python3 "$XQ_WSL_TUN/scripts/xq-proxy/install.py"
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

首次 ON 会按目标机器动态生成 `/etc/xq-proxy/sing-box.json`（含本地 DNS 入口 `127.0.0.1:1053`）和运行状态。**不要从旧机器复制这些已生成文件。**

## 8. 在目标机完成 ON/OFF 验收

先在明确的 OFF 状态验证原网络。如果原网络原本不通，应先处理基础网络，不能用开启代理掩盖 OFF 不可用：

```bash
xq_proxystatus
ls -l /etc/resolv.conf
cat /etc/resolv.conf
getent ahostsv4 ip.sb
curl --disable -4 --connect-timeout 5 --max-time 15 https://icanhazip.com
```

记下 resolver 的链接和 `nameserver`。它由 WSL 管理，ON 和 OFF 都不应把它改成 `172.30.255.2`。

开启前确认 Windows 上的 Karing 正在运行。从干净的 OFF 开启时，控制器先做只读检查，确认 resolver 可读且有 IPv4 nameserver，以 `xq-proxy` 用户对 Windows 网关的 4066 端口做 SOCKS5 握手，并让 `sing-box check` 校验生成的配置，全部通过后才改动网络。Karing 没有运行、端口不通，或 4066 上应答的不是无认证 SOCKS5 时，`xq_proxyon` 返回 1，报错以 `；未改变网络` 结尾，例如（网关地址因机器而异）：

```text
xq-proxy: Karing 172.21.32.1:4066 SOCKS5 握手失败：ConnectionRefusedError: [Errno 111] Connection refused；未改变网络
```

此时仍是 OFF：没有写入 ON 标记，没有安装防直连规则，普通网络照常可用，不需要执行 OFF；`xq_proxystatus` 显示 `已关闭（恢复原网络）`。排除原因（按第 2 节检查 Karing 的端口和共享设置）后重新执行 `xq_proxyon` 即可。

开启并验证：

```bash
xq_proxyon
xq_proxystatus
ip -4 route get 1.1.1.1
ls -l /etc/resolv.conf
cat /etc/resolv.conf
getent ahostsv4 ip.sb
curl --disable -4 --proxy '' --noproxy '*' --connect-timeout 5 --max-time 15 https://www.cloudflare.com/cdn-cgi/trace
```

`xq_proxystatus` 正常时返回 0，关键行如下（IP 行因机器而异，默认 DNS 地址取自目标机的 `/etc/resolv.conf`）：

```text
代理状态：已开启（WSL 全流量）
防直连：已开启
DNS 接管：应用 IPv4 TCP/UDP 53 → 127.0.0.1:1053 → 代理 DoH；WSL 继续管理 resolver
配置检查：DNS 入口、接管规则、路由和运行版本正常
默认 DNS 连通性：成功（默认 DNS 10.255.255.254，example.com A）
```

预期：普通用户访问公网走 `xq-tun` / 表 20260；`/etc/resolv.conf` 与 OFF 时相同，仍是 WSL 自己的配置（例如指向 `/mnt/wsl/resolv.conf`、`nameserver 10.255.255.254`），**不是** `172.30.255.2`；`getent` 能解析；即使 curl 不读取代理变量，服务端报告的出口仍为所选代理出口。不要要求新机器的 IP 必须等于本机历史 IP。

ON 时，应用发往该 resolver 的 IPv4 TCP/UDP DNS 会在网络层改送本地 `127.0.0.1:1053`，再经 Karing 向 Cloudflare DoH 查询。只存在于 Windows hosts 文件或内网 DNS 的名称在 ON 时不能解析。`xq_proxyon` 只有在控制器报告配置完整且默认 DNS 探测成功时，才查询并显示公网出口；否则返回 1。

下面的检查需要管理员读取规则，但不会切换网络：

```bash
sudo nft list table inet xq_proxy
ip -6 route show table 20260
ss -H -l -n -t -u sport = :1053
sudo conntrack -L -f ipv4 --zone 20262
```

nft 表应有 `dns_zone_output`、`dns_nat_output`（含 `dnat ip to 127.0.0.1:1053`）、`output` 和 `forward` 四条链；`ss` 应显示 `127.0.0.1:1053` 上的 TCP `LISTEN` 和 UDP `UNCONN`；刚有 DNS 查询时，conntrack 能列出本功能 zone 中回复方向为 `127.0.0.1` 端口 `1053` 的映射，没有近期查询时为空也正常。

IPv6 应为 unreachable；当前实现明确阻断 IPv6，IPv6 DNS 也不接管。保持 ON，用普通用户运行 UDP 出口诊断：

```bash
python3 "$XQ_WSL_TUN/scripts/xq-proxy/check-udp.py"
```

脚本通过普通 UDP socket 查询公开 STUN 服务，不使用应用代理变量；网络由 TUN 接管。对比它显示的 UDP 公网出口与上面的 HTTPS 出口，确认两者符合所选线路。TCP 和 UDP 可能使用不同出口，不能仅凭地址不同判定泄漏。

UDP 的端到端能力取决于目标 Windows 防火墙、代理节点和 STUN 服务。查询失败只能说明本次所选 STUN 查询未成功；查看 `--help` 可更换服务器复查，不要仅凭 SOCKS 握手成功就判定 UDP 正常。脚本只诊断，不切换开关或修改配置。

关闭并确认恢复：

```bash
xq_proxyoff
xq_proxystatus
cat /etc/resolv.conf
getent ahostsv4 ip.sb
curl --disable -4 --connect-timeout 5 --max-time 15 https://icanhazip.com
```

预期 TUN 核心停止；本功能的 DNS 接管规则、DNS 连接映射、自有策略规则和 guard 被移除；`/etc/resolv.conf` 没有被改动，查询直接回到 WSL/Windows DNS，普通网络可用。状态显示 `代理状态：已关闭（恢复原网络）`，不再显示 DNS 行，也不做 DNS 探测。`ip link show xq-tun` 此时应报设备不存在，这是期望结果；`sudo nft list table inet xq_proxy` 应报表不存在，`ss -H -l -n -t -u sport = :1053` 应无输出。

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
sudo journalctl -b -t xq-proxyctl --no-pager
```

预期默认 OFF 且普通联网可用；本次启动的 `xq-proxyctl` 日志包含 `boot-off completed: owned DNS mappings, routes and guard removed`。再手动 ON，新开第二个终端，状态应仍为 ON；新终端不能自动关闭代理。在第二个终端也运行 `xq_proxystatus` 和 `getent ahostsv4 ip.sb`：WSL 新会话可能重建 `/etc/resolv.conf`，但 DNS 接管在 nftables 中完成，状态应仍返回 0，解析应成功。

这里只关闭终端窗口并不能证明 WSL 已完整停止。原机器已验证启动复位单元的动作，但此前没有完成整台 WSL 重启验收；2026-11-14 的 DNS 接管修复也只模拟了 resolver 重建，没有实际新建 WSL 会话。因此新机器必须执行这一节，不能省略。

## 10. 故障定位与恢复

```bash
xq_proxystatus
sudo journalctl -u xq-proxy.service -n 80 --no-pager
sudo journalctl -u xq-proxy-boot.service -n 40 --no-pager
sudo journalctl -t xq-proxyctl -n 80 --no-pager
```

`xq-proxyctl` 标签记录控制器的启停结果、默认 DNS 探测失败和控制器报错；核心的连接错误仍看 `xq-proxy.service`。

- `ON，但配置异常`：按每行 `检查异常：` 的具体项目检查，例如核心、本地 DNS TCP/UDP 1053 监听、接管规则摘要、路由或恢复备份；手动 `xq_proxyon` 可重新应用所选模式，需要时会重启核心。
- `配置完整，但默认 DNS 探测失败`：规则和路由完整，但向默认 resolver 发出的探测查询（经本地入口和 Karing 的 DoH，最多 4 秒）没有得到成功答案。先检查 Karing 节点和全代理端口，再看 `xq-proxy.service` 日志；此时状态返回 1，`xq_proxyon` 不显示公网出口。
- 代理不可用：保持 ON 时，防直连规则会阻止回落，DNS 也不会回落到 WSL 原 DNS；需要普通网络时明确执行 OFF。
- OFF 时执行 `xq_proxyon` 被拒绝，报错以 `；未改变网络` 结尾：这是从干净的 OFF 开启时的预检，网络、ON 标记和状态都没有改动，不需要执行 OFF。按报错原因处理：`Karing <网关>:4066 SOCKS5 握手失败` 检查 Karing 是否运行、全代理端口和共享设置；`默认 resolver 缺少 IPv4 DNS` 或 `DNS 配置不可读取` 先恢复 OFF 下可用的 `/etc/resolv.conf`；`代理核心配置未通过 sing-box check` 核对 sing-box 是否为第 6 节安装的 1.14.4。
- 已经是 ON（或 OFF 中途失败留下残留）时执行 `xq_proxyon`，Karing 不可用：顺序仍是先装回防直连规则再握手，报 `Karing <网关>:4066 SOCKS5 握手失败：…`，并提示 `未自动回退直连。恢复原网络请执行 sudo xq-proxyctl off。`。防直连规则和 ON 标记保留，不会因为这次失败而撤除；Karing 恢复后再执行 `xq_proxyon`，或执行 OFF 回到普通网络。
- WSL 改写或重建 `/etc/resolv.conf` 不再影响 ON：控制器不写这个文件，也不把 WSL 默认 resolver 报告为异常。原机器 2026-11-14 的断网，正是旧控制器在 resolver 被改回 WSL 默认值后拒绝该 DNS 所致。只有 resolver 没有 IPv4 DNS，或残留旧版 TUN resolver（`172.30.255.2` 或旧管理标记）时才报告；后者在下一次 `xq_proxyon` 时迁移回原 DNS。
- ON 被拒绝，并提示 conntrack、DNS 端口 1053 或 conntrack zone/mark：这些检查都在改动网络之前。缺少 conntrack 时按第 4 节安装；端口、zone 或 mark 被其他程序使用时，先找出使用者，不要删除它们来强行开启。
- 报错 `原 DNS 备份无效，且无法核实 WSL 原 DNS；保留保护规则，拒绝误恢复 TUN DNS`：只会在 `/etc/resolv.conf` 仍是旧版 TUN resolver（`172.30.255.2` 或旧管理标记）、而保存的原 DNS 和 `/mnt/wsl/resolv.conf` 都无法核实时出现，此时控制器不恢复错误的 DNS，防直连规则保留。先手动把 `/etc/resolv.conf` 改成 OFF 下实际可用的 DNS 配置（不含 `172.30.255.2` 和旧管理标记），再执行 ON 或 OFF。resolver 不是旧版残留时，旧备份失效不影响 ON、OFF 和启动复位，状态也不报告它。
- `xq_proxystatus` 报告 `防直连：缺失` 和 `检查异常：防直连规则表缺失`：`inet xq_proxy` 表被删除，原因可能是有人执行了 `nft flush ruleset`，或启动、重载、重启、停止了会清空规则集的 `nftables.service`（Ubuntu 默认的 `/etc/nftables.conf` 含 `flush ruleset`）。此时 DNS 接管已经消失；resolver 是 WSL 本地地址时查询回到 WSL/Windows 的 DNS 路径，其余 IPv4 流量在核心存活期间仍进入 TUN，核心一旦停止就会直连。执行 `xq_proxyon`，它通过只读检查后先装回防直连规则，再做其他步骤；或执行 OFF。没有定时检查，清空后不会自动发现；说明这些后果不等于清空是安全的，ON 期间不要做这些操作。详见 [配套脚本说明](scripts/xq-proxy/README.md) 的“nftables 规则集被整体清空”。
- OFF 中途报错：状态可能显示 `OFF，但存在残留配置`，防直连规则可能仍在。排除报错原因后再次执行 OFF，会继续清理本功能资源。ON 期间不要卸载 conntrack；OFF 需要它清理本功能的 DNS 映射。
- 不用 `ping` 单独证明远端连接或代理出口；以 DNS、HTTPS 服务端出口、路由和 UDP 实测为准。

即使函数没有加载，恢复入口仍可直接调用：

```bash
sudo /usr/local/sbin/xq-proxyctl off
```

不要清空全机 nftables 规则、conntrack 表或删除所有策略路由。若需撤销安装，先 OFF，再根据安装清单只移除本方案文件、`.bashrc` 加载段及专用用户；不要恢复旧机器的状态文件。

## 11. 可选：Codex、Claude Code 和 MCP

基础 WSL/TUN 验收完成后，按 [开发工具配置](WSL-开发工具配置.md) 安装 Linux 版工具、登录自己的账号和配置 MCP。旧机器的现成 fnm、Node、uvx 不会因为复制 Wiki 自动出现在新机器上。

现有 [操作记录](2026-11-13-操作记录.md)、[部署记录](WSL-全流量代理部署记录.md) 保留了诊断过程。旧的环境变量版代理函数仅供历史参考，不要叠加到新 TUN 开关上。
