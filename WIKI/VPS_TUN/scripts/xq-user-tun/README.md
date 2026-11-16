# 便携用户级 TUN 安装包

这是另一台 VPS 的首次安装入口。提供 SOCKS5 代理的 IPv4 地址和端口，脚本为当前普通用户生成配置并部署用户级 TUN；用户名、UID/GID 不沿用 Mico-system 的数值。

完整流程、故障处理及隔离边界见 [VPS 用户级 TUN 一键部署](../../VPS-用户级TUN一键部署.md)。

**2026-11-15：** 当前版本在修复公网 DNS 直连泄漏和配置修改后不重载（提交 `51eb45c`）之后，又去掉了回复方向保持宿主路由、放行出网的例外：被代理用户发往公网的包在原始方向和回复方向都进入 TUN（IPv4）或被出口守卫丢弃（IPv6），关闭了外部预置一条反向 conntrack 记录就把非 DNS 的公网 UDP、IPv6、TCP 引到物理出口的通道（代价见下方行为说明）。两处都已部署到 Mico-system：第二批通过[原地升级](../xq-user-proxy/README.md#2026-11-15-原地升级为便携包版本)，第三批通过替换控制器并重载规则，均不改动核心配置、不重启核心。用本包的安装器在一台新机器上完整安装，仍未做过。

## 安装

支持使用 systemd 的 Debian 12+ / Ubuntu 22.04+，CPU 为 x86_64 或 aarch64；安装前需有 Bash 和 Python 3.9+。目标用户须已有 sudo 管理权限，还需要内核 TUN 支持，以及可达的无认证 SOCKS5 TCP 代理。`net.ipv4.ip_unprivileged_port_start` 须大于 40（默认 1024），`/etc/resolv.conf` 的前 3 个 nameserver 中至少有一个 IPv4 或 IPv6 ULA/链路本地地址；不满足时安装器在写入系统文件之前拒绝。安装器会通过 apt 准备缺少的系统依赖，经给定代理下载 [sing-box 1.14.4 官方发行包](https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4) 并核对内置 SHA256。

安装依赖可能触发软件包维护脚本；已有复杂防火墙的服务器建议先由管理员预装依赖并核对规则。TUN 的用户范围限制不等于系统软件包安装过程绝无其他影响。

复制整个本目录到新 VPS，在要使用 TUN 的普通用户账号下执行：

```bash
cd xq-user-tun
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066
source ~/.bashrc
xq_proxyon             # 清理本终端旧代理变量；默认安装已 ON，此命令检查/恢复现有服务
xq_proxystatus
```

将示例 IP 和端口改为新 VPS 实际可达的代理地址。`192.168.5.34` 是私网地址，另一台公网 VPS 通常不能直接访问，不能仅因原机器能用就照搬。

也可运行 `bash install.sh`，按提示输入代理 IP 和端口。安装默认开启 TUN；第一次开启后只接管目标 UID 的宿主网络程序。只安装、暂不开启时增加 `--no-start`。

```bash
xq_proxyon             # 开启当前用户全部宿主会话的 TUN，仍留在原 shell
claude                 # 之后启动的 Claude Code 使用该用户网络策略
xq_proxyoff            # 明确关闭，恢复该用户原网络
xq_proxystatus         # 查询状态
```

## 参数

| 参数 | 用途 |
| --- | --- |
| `--proxy-ip IPv4` | SOCKS5 上游 IPv4 地址；不接受域名 |
| `--proxy-port PORT` | 上游端口，范围 1–65535 |
| `--user USER` | 显式指定非 root 目标账号；通常不需要，直接 root 登录时必须指定 |
| `--no-start` | 安装后保持 OFF，稍后执行 `xq_proxyon` |
| `--render-dir DIR` | 只在尚不存在的目录中生成安装配置，不含核心文件，不提权、不安装、不修改网络 |
| `--archive FILE` | 使用本地官方 sing-box 1.14.4 `.tar.gz`，仍按当前架构核验内置 SHA256 |
| `--help` | 查看实际脚本支持的参数 |

普通用户运行时自动选择该用户；`sudo bash install.sh ...` 会识别 sudo 前的用户。目标必须是已有的非 root 账号，并已有后续执行开关所需的 sudo 管理权限。root 使用 `--user` 代装不会自动授予目标账号 sudo 权限；安装器不写 sudoers。每台 VPS 只允许本安装包管理一个用户，遇到旧安装或资源冲突会拒绝，不提供原地升级。唯一的例外是 Mico-system 上的冻结版本：它由专门的 [upgrade-to-portable.py](../xq-user-proxy/upgrade-to-portable.py) 原地换成本包的控制器、服务单元和配置，过程见[归档说明](../xq-user-proxy/README.md)。

## 部署包

WIKI 的 `dist/` 目录提供 [xq-user-tun.tar.gz](../../dist/xq-user-tun.tar.gz) 和 [校验文件](../../dist/xq-user-tun.tar.gz.sha256)。校验后解压即可使用：

```bash
sha256sum -c xq-user-tun.tar.gz.sha256
tar -xzf xq-user-tun.tar.gz
bash xq-user-tun/install.sh --proxy-ip 192.168.5.34 --proxy-port 4066
```

必须复制整个目录或使用完整压缩包，不能仅复制 `install.sh`。本包不自动安装独立命名空间模式的 `xq_tun run`；该模式的旧文档在 [scripts/xq-tun](../xq-tun/README.md)。

## 行为约定

- 开关作用于目标用户的全部宿主会话，不是单终端开关；不会因关闭终端而 OFF。重启系统后默认 OFF。
- 安装器无法清除现有终端或其他进程的旧代理环境变量。当前终端执行 `source ~/.bashrc` 后运行 `xq_proxyon` 可清理其常见代理变量；其他终端需分别处理。
- 私网、链路本地及多播/广播按宿主路由直连；公网 IPv4 TCP 经代理，公网 UDP、ICMP 和 IPv6 主动出站阻断。
- 被代理用户发往公网地址的包，无论 conntrack 把它算作原始方向还是回复方向，一律走 TUN 路由（IPv4）或被出口守卫丢弃（IPv6）；回复方向没有直接出网的例外（2026-11-15 修复）。此前外部预置一条 conntrack 记录（伪造源地址的 UDP 数据报，或装在广播帧里的 TCP SYN），就能让被代理用户随后从同一端口发往同一地址的包被当作回复、从物理出口发出。现在这类包不再直出，但那条连接也不通：核心的应答在 TUN 入口被丢弃，连接在记录存在期间得不到应答，换一个源端口的新连接不受影响。另一个代价是被代理用户自己的服务无法应答公网客户端；发往局域网和回环的应答仍按各自规则保持宿主路由。`tests/netns-check.py` 和 `tests/core-check.py` 含回归测试和对照，限度见[指南第 7 节](../../VPS-用户级TUN一键部署.md#没有-socket-的包)。
- DNS 按目的地址区分。发往**本机地址**的查询（`127.0.0.53` 等回环地址、`0.0.0.0`、配置在本机网卡上的非局域网地址）改送专用入口 `127.0.0.1:40`；发往**其他公网 IPv4** 的查询不改写，与其他公网流量一样进入 TUN，由核心接管应答。两条路径都经代理 DoH 解析，查询不会到达原来的 DNS 服务器。局域网 IPv4 和 IPv6 ULA/链路本地地址直连、不经代理；其余 IPv6（含 `::1`）阻断。`xq_proxystatus` 逐个列出默认 nameserver 的实际路径；默认 DNS 全部被阻断时拒绝开启，默认 DNS 走局域网直连时给出警告。
- 程序关闭 socket 之后，内核替它发出的包（RST、ICMP 错误、未确认内容的重传）不带 UID，只能按连接归属。公网连接不做地址改写，这些包按连接上的 owner 标记继续进入 TUN；从 TUN 进来的包必须是 owner 已有连接的回复（或 RST），否则在入口丢弃，内核不会为它生成从物理出口发出的应答（2026-11-15 修复：此前公网 DNS 也被改写到回环入口，提前放弃的查询会让内核按原目的地址从物理网卡发出 ICMP 错误和 RST，其中 UDP 的 ICMP 错误带有查询内容）。仍然存在的限度见[指南第 7 节](../../VPS-用户级TUN一键部署.md#没有-socket-的包)。
- 核心只在启动时读取配置。服务单元在核心启动前后记下这次加载的配置（`/run/xq-user-proxy/core.json`）；此后 `settings.json` 或 `sing-box.json` 被修改时，`xq_proxystatus` 和 `check` 报告“新配置尚未加载”，并显示运行中的核心实际使用的上游；`xq_proxyon` 重启核心加载新配置，期间防直连规则和黑洞路由保留。
- 控制器记下它所生成规则的摘要。已加载的规则不是当前控制器和配置生成的版本时（例如更新了控制器），`check` 报告异常，`xq_proxyon` 原子替换整张表，不清空 conntrack，核心配置没有变化时不重启核心。
- 不全局替换 DNS，不授予 sudoers 免密权限，不创建定时回滚。核心故障时保留阻断规则，不自动恢复公网直连。
- root 及其他 UID 的正常新建连接不被接管，专用 DNS/TUN 入口限制 owner。root 管理员仍能修改规则或切换身份绕过。owner 的 DNS 改写放在专用 conntrack zone `20261`，其他用户复用相同 UDP 源端口时不会再套用它，反之亦然（2026-11-14 修复，`tests/netns-check.py` 含回归测试）。
- 专用 DNS 入口是特权端口，普通用户在核心停止期间也无法监听；只有核心身份（root）发出的回复才会交给 owner（2026-11-15）。前提是 `net.ipv4.ip_unprivileged_port_start` 大于 40；root 和持有 `CAP_NET_BIND_SERVICE` 的程序属于受信任范围。
- 核心停止期间，owner 发往本机地址的 DNS 和发往公网 DNS 的 UDP 查询立即失败；发往公网 DNS 的 TCP 连接没有应答，等到程序自己的超时。都不会回退到系统 DNS 或物理出口。
- `xq_proxyoff` 先确认 conntrack 可用再动手，否则拒绝并保持原状；中途失败后重复执行即可继续清理。`xq_proxystatus` 在开关 OFF 但仍有残留时返回非零并列出残留。
- 防直连依赖自有的 nftables 表。`nft flush ruleset`、停止 `nftables.service`，或加载含 `flush ruleset` 的 `/etc/nftables.conf`（Debian/Ubuntu 默认如此）都会删除它，此后 owner 的新连接和 DNS 直连；`xq_proxystatus` 会明确报告，执行 `xq_proxyon` 重建。详见[指南第 6 节](../../VPS-用户级TUN一键部署.md#nftables-规则集被清空时)。

编辑或打包本目录不会更新任何正在运行的服务。

## 验证范围

已完成离线身份、安全与配置测试及 `sing-box check`；在隔离的测试网络中验证了 owner 专属入口、root/其他 UID 的普通 DNS/TCP/UDP，以及拒绝访问私有入口。模拟 TUN 消失时，目标用户黑洞路由保留，root 原路由和 DNS 仍可用。尚未在第二台真实 VPS 完整执行安装；这些检查不能替代目标机器的 systemd、软件包、网络和端到端连通性验收。

维护者可从本目录复查：

```bash
python3 -I tests/test_portable.py       # 安装器、配置范围、与控制器的一致性
python3 -I tests/test_lifecycle.py      # 生命周期与失败注入；模拟内核，不需要 root，不执行任何命令
sudo unshare --net python3 -I tests/netns-check.py   # 真实内核，owner/其他 UID/root 三个真实身份
sudo unshare --net python3 -I tests/core-check.py --core /path/to/sing-box   # 真实控制器 + 真实 sing-box 1.14.4
```

`core-check.py` 同样只在全新的临时网络命名空间里运行。它用真实的控制器和真实的核心走完开启、关闭和修复：owner 各类 DNS 的实际路径；120 次提前放弃的查询之后没有包从物理出口发出；被 conntrack 遗忘的连接在关闭时就地复位；外部预置了 conntrack 记录的连接（DNS 和 443 端口）不从物理出口发出、也得不到应答，换一个源端口即可用；核心被杀后不漏包、其他 UID 无法占用入口；调低端口门槛后冒充的应答到不了 owner；改动磁盘配置后 `status` 如实报告、`on` 重新加载；换了版本的规则被替换。命名空间里没有 systemd，服务单元的各步骤由测试按单元文件的顺序执行；核心的 DoH 和上游在测试配置中换成本地替身，其余配置与安装时相同。

`netns-check.py` 只允许在一个全新的临时网络命名空间运行，拒绝在宿主网络中加载测试规则。没有 root 时可以用 rootless 命名空间运行它的单一身份部分。分两条命令执行：第一条先记下宿主网络命名空间，写在同一条命令前面时 shell 展开出的 `$HOSTNS` 是空的，测试会拒绝运行：

```bash
HOSTNS=$(readlink /proc/self/ns/net)
unshare --user --map-root-user --net env XQ_HOST_NETNS="$HOSTNS" python3 -I tests/netns-check.py
```

此时命名空间内只有一个身份，各角色通过规则中的 UID 常量轮流扮演，需要两个用户同时存在的检查会标为 SKIPPED；它不能代替上面的 root 运行。2026-11-15 的版本在 Mico-system（Ubuntu 22.04，内核 6.8）上执行了全部四项：离线 15 + 57 项、rootless 运行、root 下的三身份运行、`core-check.py` 连续 6 次，全部通过，详见[指南第 9 节](../../VPS-用户级TUN一键部署.md#9-已验证范围)。
