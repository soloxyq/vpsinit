# 另一台 VPS：用户级 TUN 一键部署

使用 [scripts/xq-user-tun](scripts/xq-user-tun/README.md) 为新 VPS 的当前普通用户部署 TUN。安装时只需提供代理 IP 和端口；用户名、UID/GID 从目标系统获取，本机物理 IP、网卡和公网出口不写死。此入口不依赖之前在 Mico-system 安装的独立命名空间服务。

本指南描述新机器的首次安装。旧的 [Mico-system 部署记录](VPS-TUN部署记录.md)、[用户级验收记录](VPS-用户级TUN验收记录.md) 和 [权限审计](VPS-TUN固定值与访问权限审计.md) 保留历史用途，不能把其中的实测 IP、UID 或备份路径直接套用到新服务器。

**2026-11-15：** 本指南对应仓库中的便携包当前版本（恢复路径、默认 DNS 判断和专用 DNS 入口归属的修复），该版本**待部署**，尚未安装到任何机器。Mico-system 上运行的是 2026-11-14 的固定归档版本，没有这些修复，行为与本文不同，见[归档说明](scripts/xq-user-proxy/README.md)。

## 1. 安装前提

| 项目 | 要求 |
| --- | --- |
| 系统 | Debian 12+ / Ubuntu 22.04+，使用 systemd 管理服务；安装前需有 Bash 和 Python 3.9+ |
| 架构 | x86_64/amd64 或 aarch64/arm64 |
| 权限 | 目标是已有且具备 sudo 管理权限的普通用户；不以 root 作为被代理用户，安装器不授予 sudo 权限 |
| 内核 | 可用的 `/dev/net/tun`、nftables 和策略路由；宿主/容器需授予所需网络管理能力 |
| 特权端口 | `net.ipv4.ip_unprivileged_port_start` 必须大于 `40`（内核默认 `1024`）。专用 DNS 入口使用特权端口 `127.0.0.1:40`；该值被调到 `40` 或以下时普通用户可以占用入口，安装和开启都会拒绝 |
| 默认 DNS | `/etc/resolv.conf` 中 glibc 实际使用的 nameserver（前 3 个）至少有一个可用：IPv4 地址，或 IPv6 的 ULA/链路本地地址。只有 `::1` 或公网 IPv6 nameserver 时安装和开启都会拒绝，见第 5 节 |
| 上游 | 从新 VPS 可达的 SOCKS5 IPv4 地址及端口，无用户名密码认证，支持 TCP |
| 下载 | 能通过 apt 获取缺少的发行版依赖，并通过给定代理下载 sing-box 1.14.4 官方发行包；可提供对应架构的本地官方 `.tar.gz` |
| 共存 | 单台机器只由此安装包管理一个目标用户；安装前不能存在同名旧部署或占用其专用资源 |

例如，当前机器使用的 `192.168.5.34:4066` 是局域网代理。另一台公网 VPS 只有具备到该私网的网络路径时才能继续使用；否则应提供新 VPS 可达的代理地址。脚本会在改动代理网络规则前验证 SOCKS5 连接和 HTTPS。

若代理实际只支持 HTTP CONNECT，或要求用户名/密码，本安装包不适用；不能把它当作无认证 SOCKS5 端口使用。

自动安装缺少的系统包可能执行软件包维护脚本，因此不能承诺整个安装过程对系统其余部分绝无影响。已有复杂防火墙或其他网络管理服务的 VPS，建议管理员先预装所需依赖（`iproute2`、`nftables`、`iptables`、`conntrack`、`curl`、`util-linux`、`sudo`、`ca-certificates`），核对软件包操作和防火墙状态后再运行安装器。

## 2. 将安装包放到新 VPS

可以复制 WIKI 中的整个 `scripts/xq-user-tun/` 目录，也可以使用打包文件：

- [下载 xq-user-tun.tar.gz](dist/xq-user-tun.tar.gz)
- [下载 SHA256 校验文件](dist/xq-user-tun.tar.gz.sha256)

从持有 WIKI 文件的机器复制到目标 VPS，以下账号和地址需要替换：

```bash
scp dist/xq-user-tun.tar.gz dist/xq-user-tun.tar.gz.sha256 your-user@your-vps:~/
ssh your-user@your-vps
sha256sum -c xq-user-tun.tar.gz.sha256
tar -xzf xq-user-tun.tar.gz
cd xq-user-tun
```

此处没有公开下载站点或 `curl | bash` 地址；使用本 WIKI 中实际生成的文件。只复制 `install.sh` 会缺少配套控制器、配置和服务文件。

## 3. 一键安装

登录将使用 TUN 的普通用户，执行：

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066
```

将示例 IP 和端口替换为新 VPS 的上游。也可以交互输入：

```bash
bash install.sh
```

脚本自动确定当前用户，需要时调用 sudo。若使用 `sudo bash install.sh ...`，目标仍是 sudo 前的普通用户。以 root 直接登录时必须明确指定已有普通账号：

```bash
bash install.sh --user alice --proxy-ip 192.168.5.34 --proxy-port 4066
```

`alice` 仍须事先具备运行开关所需的 sudo 管理权限。root 代装不会为目标账号授予 sudo 权限，安装器不写 sudoers。

安装器准备依赖、获取 [sing-box 1.14.4 官方发行包](https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4) 并核对内置 SHA256、检查资源冲突、生成仅属于该账号的配置、安装 systemd 服务及 Bash 快捷函数。默认随后开启用户级 TUN，不修改全局 `/etc/resolv.conf`。

在安装依赖、下载或写入任何系统文件之前，安装器先检查特权端口门槛和默认 DNS：不满足第 1 节的要求时直接拒绝，并逐个列出 nameserver 及其原因；默认 DNS 在直连范围内（局域网 DNS）时允许安装，但会提示“不经代理”。

已有安装，包括当前 Mico-system 的历史部署，会被拒绝；此脚本不用于更新正在运行的服务。检测失败时先处理具体错误，不要用删除未知路由、防火墙规则或安装标记的方式强行通过。

安装完成后，在目标用户的终端执行：

```bash
source ~/.bashrc
xq_proxyon             # 默认已 ON；此命令检查/恢复服务，并清理当前 shell 的旧代理变量
xq_proxystatus
curl --disable --proxy '' --noproxy '*' -4 --fail --max-time 20 https://api.ipify.org
```

安装器无法修改此前打开的终端及其他进程的环境变量；只执行 `source ~/.bashrc` 也不会自动清理旧变量。在要继续使用的终端中执行 `xq_proxyon` 才会清除该 shell 的常见代理变量。其他终端需分别处理，已运行进程可能需要重启。

公网出口是运行时查询结果，换代理节点后可以变化，没有固定的预期 IP。

### 只安装，稍后开启

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066 --no-start
source ~/.bashrc
xq_proxyon
```

`--no-start` 仍会完成安装前的环境及代理检查，但不启用用户 TUN。

### 先查看生成结果

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066 \
  --render-dir /tmp/xq-user-tun-preview
```

目标目录必须尚不存在。此模式只生成配置文件，不包含 sing-box 核心，不提权、不安装依赖、不写系统目录、不改网络。它验证输入和配置生成，不代替目标机器上的内核、权限、资源冲突和实际连通性验收。

### 使用已下载的 sing-box 官方发行包

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066 \
  --archive /path/to/sing-box-1.14.4-linux-amd64.tar.gz
```

arm64 机器使用 `sing-box-1.14.4-linux-arm64.tar.gz`。本地包也必须匹配安装器固定的版本、架构及内置 SHA256，不能自行重新打包。此选项只跳过核心下载，不保证整个安装过程离线：系统依赖可能仍需安装，上游代理也需要实测。

## 4. 日常命令

```bash
xq_proxyon             # 开启或恢复服务，保留当前 shell
xq_proxystatus         # 查看目标用户的代理状态
xq_proxyoff            # 明确关闭，恢复原网络
```

启动 Claude Code：

```bash
xq_proxyon && claude
```

这些命令不会进入新的交互式 shell。开关覆盖目标 UID 的全部宿主会话及新进程，不是单个终端；关闭终端不会关闭服务，新终端沿用当前状态，完整重启后默认 OFF。部分切换前建立的公网长连接可能需要重新连接。

快捷函数会清除调用终端的常见代理环境变量，但无法改写其他已运行进程的环境。程序若自行指定代理，或由 root、其他 UID、容器、共享守护进程代发网络请求，不属于同一用户的宿主 TUN 接管保证。

本包仅安装用户级开关。原机器的 `xq_tun run claude` 属于另一个独立命名空间方案，本次便携安装不会额外创建该命令。

## 5. 转发和阻断范围

```text
目标用户的宿主程序
    → 按 UID 标记的策略路由
    → 私有 TUN / DNS 入口
    → sing-box
    → 指定 SOCKS5 代理
    → 互联网
```

| 流量 | 行为 |
| --- | --- |
| 目标用户主动访问公网 IPv4 TCP | 经 TUN 和 SOCKS5 上游 |
| DNS（TCP/UDP 53）发往直连范围以外的 IPv4 地址，包括 `127.0.0.53` 等回环地址和公网 DNS | 改送专用 DNS 入口 `127.0.0.1:40`，通过代理 DoH 查询 |
| DNS 发往 IPv4 直连范围内的地址（局域网 DNS） | 局域网例外：按宿主路由直连该服务器，**不经代理** |
| DNS 发往 IPv6 ULA、链路本地地址 | 按宿主路由直连，**不经代理**；是否可达取决于宿主网络 |
| DNS 发往其他 IPv6 地址，包括 `::1` 和公网 IPv6 | 阻断 |
| IPv4 私网、链路本地、多播/广播 | 直连；不强绑某块物理网卡 |
| IPv6 ULA、链路本地、多播 | 直连；是否可达取决于宿主网络 |
| 公网 UDP、ICMP/ping、IPv6 主动出站 | 阻断；上游 TCP 方案不提供这些传输 |
| root 和其他 UID 的普通新连接、DNS | 不按目标用户规则接管，仍到原服务器；访问专用 DNS 入口被拒绝 |

直连例外是 IPv4 `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`224.0.0.0/4`、`255.255.255.255/32`，IPv6 `fc00::/7`、`fe80::/10`、`ff00::/8`。因此“防直连”指对受管公网流量的阻断策略，不代表封掉全部局域网通信。

公网 ping 不通是预期策略，不能据此判断 Claude Code 或 HTTPS 代理失效。

### 默认 DNS 的实际路径

程序不指定 DNS 时使用 `/etc/resolv.conf`。glibc 按文件顺序只使用前 3 个有效的 nameserver；一个都没有时默认查询 `127.0.0.1`。条目是否有效按 glibc 的解析判断，不以文件看上去的样子为准：例如带 Windows 换行（CRLF）的文件里，IPv4 条目和不带 `%` 的 IPv6 条目都会被 glibc 丢弃，带 `%` 的 IPv6 条目仍然保留（`xq_proxystatus` 把 `%` 后面的不可见字符显示成 `\r` 这样的转义）。每个 nameserver 的去向由上表决定，与它是不是“默认”无关：

| 默认 nameserver | 开启后的路径 |
| --- | --- |
| `127.0.0.53`（systemd-resolved）、`127.0.0.1`、公网 IPv4 等直连范围以外的 IPv4 | 改送 `127.0.0.1:40`，经代理 DoH 解析 |
| 局域网 IPv4，例如 `192.168.x.x`、`10.x.x.x`、`169.254.x.x` | 直连该服务器，不经代理；允许使用，`xq_proxystatus` 和安装器给出警告 |
| IPv6 ULA（`fc00::/7`）、链路本地（`fe80::/10`） | 直连，不经代理；同样给出警告 |
| `::1`、公网 IPv6 | 阻断：查询立即失败或超时 |

以 IPv4 映射形式书写的地址（`::ffff:a.b.c.d`）实际发出的是 IPv4 包，按对应的 IPv4 地址处理。局域网 DNS 直连是既定策略，没有改成接管；因此“DNS 经代理”只对上表第一行成立。

`xq_proxystatus` 逐个列出 nameserver 及其路径，不再给出笼统结论。glibc 会使用的 nameserver 全部被阻断时，目标用户的域名解析必然失败：首次开启和安装会在改动网络之前拒绝，并指出每个 nameserver 及原因；开启期间变成这样时，`status`/`check` 报告异常。被阻断的 nameserver 排在可用的之前（或启用了 `options rotate`）时允许开启，但会警告解析变慢或间歇失败。

这些判断只读取配置，不发送查询，不能证明所列服务器此刻可用；以目标用户身份实测默认 DNS 尚未提供。

## 6. 出错时的处理

不会创建定时回滚，也不会在检查失败、核心退出或上游断开时自动 OFF。保护规则独立于核心运行；核心故障可能中断目标用户的公网访问，直到明确恢复或关闭。

先检查状态和日志：

```bash
xq_proxystatus
sudo /usr/local/sbin/xq-user-proxyctl check
sudo systemctl status xq-user-proxy.service --no-pager
sudo journalctl -u xq-user-proxy.service -n 80 --no-pager
```

恢复代理使用 `xq_proxyon`。明确要恢复该用户原网络时使用 `xq_proxyoff`。若 Bash 函数还没加载，可调用：

```bash
sudo /usr/local/sbin/xq-user-proxyctl on
sudo /usr/local/sbin/xq-user-proxyctl off
```

不要将 `systemctl stop xq-user-proxy.service` 当作 OFF：它只停止核心，仍会留下防直连保护和黑洞路由。

### 关闭的前提与中断后的继续

- `xq_proxyoff` 动手之前先做只读检查：核心状态、nft 表、策略规则、专用路由，以及 conntrack 能否列出本功能的 DNS 映射。`/usr/sbin/conntrack` 缺失、不可执行或无法列出时直接拒绝：不删除开启标记、不换规则、不停核心，代理和防直连保持原状，并说明原因。root 自身的网络不经代理，可直接执行 `sudo apt install conntrack` 后重试。
- 清理每一类自有对象时先查询、再删除、删除后再查询。从未创建的路由表、只创建了一部分的对象、已经清理过的对象都按“已经不在”处理；只有对象仍在而删除失败（例如权限或内核错误）才报错并保留防直连规则。判断不依赖工具的英文报错文字。路由表 `20261` 中不属于本功能的路由不会被删除。
- 关闭中途失败或被中断后，重复执行 `xq_proxyoff` 即可从中断处继续，直到输出“用户代理已关闭”。在此之前防直连规则保留，目标用户的公网访问是被阻断而不是直连。开启在任一步骤失败后，同样用 `xq_proxyoff` 清理。
- 没有本启动周期的归属记录（例如 `/run/xq-user-proxy` 被手工删除）而同名对象还在时，控制器不会删除它们，需要管理员核对后手动处理。

### status 和 check 的退出码

| 命令 | 退出码 0 | 退出码 1 |
| --- | --- | --- |
| `xq_proxystatus`（`xq-user-proxyctl status`） | 开关 ON 且检查通过；或开关 OFF 且没有残留（包括正常开机后从未开启） | 开关 ON 但检查发现异常；或开关 OFF 但有残留：上次操作停在未完成阶段、核心仍在运行、防直连 nft 表、专用策略规则、专用路由或 DNS conntrack 映射仍在。输出逐项列出，并给出恢复入口 `xq_proxyoff` |
| `xq-user-proxyctl check` | 开关 ON 且检查通过 | 其余情况，包括开关 OFF（“用户代理未开启”） |

开关 ON 时两者都只报告发现的第一个异常。开关 OFF 且缺少 conntrack 时，`status` 注明“未核验”DNS 映射；只要没有其他残留，仍返回 0。权限不足、参数错误或配置无效时两个命令也返回 1。

### nftables 规则集被清空时

本方案的选路决定放在 nftables 里：`xq_user_proxy` 表按 socket UID 给目标用户的包打路由标记，策略路由只认这个标记；DNS 改送和防直连规则也在这张表里。表被删除后，策略规则和专用路由虽然还在，却不再有包带标记：目标用户的新连接按 main 表从物理出口直连，DNS 直接发给系统 resolver，已建立连接的后续包也不再被改道。核心照常运行，不会有任何报错。

会删除这张表的操作：

- 管理员执行 `nft flush ruleset`；
- 停止 `nftables.service`（包括 restart 的停止阶段）：它的 `ExecStop` 就是 `nft flush ruleset`；
- 启动或 reload `nftables.service`，且 `/etc/nftables.conf` 含有 `flush ruleset`。Debian/Ubuntu 默认的 `/etc/nftables.conf` 以这一行开头；管理员改写后去掉这一行的配置不会清空其他表；
- 其他加载含 `flush ruleset` 文件的脚本或工具。

firewalld、ufw 的重载行为没有核实，本文不作结论。

发现方式：没有常驻监控，也没有定时检查。开关 ON 时，`xq_proxystatus` 和 `sudo /usr/local/sbin/xq-user-proxyctl check` 首先确认这张表存在；缺失时返回非零，并直接说明表不存在、目标用户的新连接和 DNS 可能正在直连、应执行 `xq_proxyon`。在下一次查询之前，直连不会被发现。

恢复方式：执行 `xq_proxyon`。它重建这张表并补齐策略路由，核心在运行时不重启。清空期间已经直连的连接不会被追回，相关程序需要重新连接。

写明这些并不能让清空规则集变成安全操作：防直连只在这张表存在时成立。需要“规则集被清空后仍不直连”的保证时，必须另行设计，本包没有提供。使用 nftables 管理防火墙的机器，应改为只操作自己的表（`nft delete table`、`nft flush table`），不要整体 `flush ruleset`。

如果安装在开启阶段失败，按安装输出中的路径检查已写入配置和日志，不要假设系统自动恢复了安装前的网络状态。安装记录及备份路径以该次脚本输出为准。

## 7. 用户隔离的边界

入口和路由按安装时确定的非 root UID 限制，其他普通用户不能借用私有 DNS 或 TUN 出口；root 的正常新建应用连接也不会自动被接管。系统 DNS、主路由和无关用户规则不被全局替换。

专用 DNS 入口 `127.0.0.1:40` 是特权端口：绑定它需要 `CAP_NET_BIND_SERVICE`，核心单元带有这项能力，普通用户（包括目标用户自己）即使在核心停止期间也无法监听。目标用户被改送的查询因此不会交给别的普通进程；核心不在时查询立即失败（连接被拒绝），不会回退到系统 DNS。此外，规则在进入 conntrack 之前丢弃“源端口为 40、但发送 socket 不属于核心身份（当前为 root）”的包，冒充入口的回复到不了目标用户；内核自己生成的 RST 和 ICMP 错误不属于任何 socket，照常放行。

这项保证的前提和限度：

- `net.ipv4.ip_unprivileged_port_start` 必须大于 `40`。安装和首次开启在改动之前检查，不满足就拒绝；开启期间被调低时，`status`/`check` 报告为异常（普通用户可以绑定入口，归属无法保证）。此时冒充的回复仍被丢弃，但查询内容可能已被占用者读到。
- root，以及被授予 `CAP_NET_BIND_SERVICE` 的程序（包括带文件能力的可执行文件），属于受信任范围，不在防护之内。
- 状态命令只核对规则和端口门槛，不检查监听进程是谁；保证来自内核对特权端口和发送身份的限制，而不是来自状态检查。

这不是防不可信 root 管理员的隔离方案。root 及拥有等价管理权限的人可以修改规则、替换程序或切换到目标 UID，无法在同一台 VPS 内禁止这些管理能力。

共享宿主网络的 conntrack 五元组不包含 UID。为此，目标用户的 DNS 改写及私有 DNS 入口的回复放在专用 conntrack zone `20261`：其他用户即使复用了相同的 UDP 源端口，也只会在默认 zone 中新建自己的连接，不会套用目标用户的映射，反之亦然。目标用户的其他连接仍记录在默认 zone，只带标记、不做地址改写；规则均先按 socket UID 判断。即便如此，也不能承诺任何异常场景下都对其他用户零影响；要求严格隔离时应另外设计独立命名空间或容器方案。

其他用户自行连接远端代理 IP 和端口不属于借用本 TUN。若连远端代理本身也要限制，应在代理服务器上配置访问控制或认证；本包不会顺带封禁其他用户的正常 LAN 连接。

## 8. 保留的配置常量

每次安装动态生成用户名、UID/GID 和上游地址；运行时不固定物理 IP、网卡名或出口 IP。下列项目仍是配套配置，不是从 Mico-system 复制的物理网络信息：

- TUN 名 `xq-utun`、内部地址 `172.30.254.1/32`、专用 DNS 入口 `127.0.0.1:40`（特权端口，IANA 未分配）。
- 核心身份 root（UID 0）：只有它可以从专用 DNS 入口发出回复；核心单元的能力集为 `CAP_NET_ADMIN`、`CAP_NET_RAW`、`CAP_NET_BIND_SERVICE`。
- 策略路由表 `20261`、conntrack zone `20261`、优先级 `18410`、nftables 表 `xq_user_proxy` 和专用标记位。
- DoH `1.1.1.1:443` / `cloudflare-dns.com`、MTU `1280`。
- systemd 服务及管理路径、固定 sing-box 版本和校验值。

安装时需要检查这些资源的冲突，不会为了迁就新机器而覆盖未知对象。仅自有 TUN 的接口参数会按需设置，例如 `rp_filter=2`，不改物理网卡及全局转发参数。配置主体保存在 `/etc/xq-user-proxy/`，其中 `settings.json` 记录授权用户与上游；不要只修改某一个文件后就假设其他配套设置会自动同步。

## 9. 已验证范围

便携包已通过离线身份、安全与配置测试，以及 sing-box 1.14.4 的配置检查。隔离测试网络已验证 owner 专属 DNS/TUN 访问限制、root/其他 UID 的普通 DNS/TCP/UDP 保持可用，以及其他 UID 访问私有入口被拒绝。模拟 TUN 消失后，目标用户仍受黑洞路由阻断，root 原路由和 DNS 保持可用。

2026-11-15 的修复按“先复现、再修复”完成，验证分三层，结论不能互相替代：

- **离线（模拟内核，无需 root）**：`tests/test_lifecycle.py` 加载真实控制器，命令由严格的模拟内核应答。覆盖开启、修复式开启和关闭的每一步分别“失败”和“生效后中断”后重复关闭都能清理干净并可再次开启；缺少 conntrack 时拒绝且不改动；`status` 各种状态的退出码；默认 DNS 分类矩阵和改动前拒绝；特权端口门槛；规则文本中的回包身份规则。同一套测试对修复前的控制器失败。
- **真实内核、单一身份（无需 root）**：`tests/netns-check.py` 在全新的 rootless 网络命名空间中运行，命名空间内只有一个身份，owner、旁观者、非核心发送者三种角色通过改变规则里的 UID 常量轮流扮演，“其他用户”的绑定权限由去掉 `CAP_NET_BIND_SERVICE` 的进程代替。已实际执行：缺表清理幂等及外来路由保留；启用/停用两种规则加载；各类 resolver 的 UDP/TCP 实际路径与分类一致；无该能力的进程无法绑定 40 端口；监听停止后 owner 立即失败且不回退到 53 端口，重启后恢复；非核心身份的回复被丢弃；规则表删除后 owner 新连接改走主路由；按关闭的顺序执行清理步骤后没有残留，重复执行不出错。命名空间里没有 systemd，核心的启停和完整的开关流程只在离线测试中覆盖。
- **真实内核、三个真实身份（需要 root）**：同一脚本用 `sudo unshare --net` 运行时，以真实的 owner、其他 UID 和 root 完成全部检查，包括其他 UID 绑定失败、调低端口门槛后其他 UID 抢占入口的回复被丢弃，以及借用 conntrack 元组和源端口复用。2026-11-15 已在开发机（WSL2，内核 6.18）上以 root 执行，全部检查通过（`ALL CHECKS PASSED: owner UID 23456, other UID 23457, root`）。第一次运行发现测试自身的一处断言没有考虑三身份模式下仍保留的 owner DNS 映射，已修正测试，控制器没有改动。另以 root 做了反证：去掉回包身份规则后，调低门槛的其他 UID 伪造的回复确实会到达 owner。

同日的复核又发现并修正两处，均先有失败的测试：

- **rootless 示例命令**：原先把 `HOSTNS` 的赋值和使用写在同一条命令里，在新开的 shell 中传给测试的是空值，测试拒绝运行。现已拆成两条命令；`tests/test_portable.py` 会实际执行文档和测试文件里的这段命令，检查传入的确实是调用者的网络命名空间。
- **默认 DNS 的解析与 glibc 不一致**：带 `%` 的 IPv6 条目后面跟着回车等字符时（例如 CRLF 文件里的 `::1%lo`）被当作无效，行内有 NUL 字节时整条被丢弃。两种情况下，实际会被阻断或直连的 nameserver 都被报告成“回退到 `127.0.0.1`、经代理”，开启也不会拒绝。现在按 glibc 的顺序解析：先把整个条目当作 IPv4，不行再取 `%` 之前的部分当作 IPv6，`%` 之后的内容不影响取舍；NUL 视为一行内容的结束。修正后在隔离的挂载命名空间里把 34 种写法与开发机 glibc 2.39 的实际解析结果逐项对照，全部一致。

修正后重新执行了上面三层测试，全部通过。

这些测试不需要改动 Mico-system 正在运行的 TUN。尚未在第二台真实 VPS 完整执行安装，因此没有把软件包安装、该机 systemd 启动和实际代理出口宣称为已在新服务器验收。目标机器仍需按安装器结果及本指南的状态、HTTPS 检查完成验证。

修改源码或文档后，可在 `WIKI/VPS_TUN` 目录重新生成部署包及 SHA256 校验文件：

```bash
python3 scripts/build-xq-user-tun.py
```

包内包含独立的 `DEPLOYMENT.md` 和 `CONTENTS.sha256`，不会打入当前服务器的配置、账号凭据或运行备份。
