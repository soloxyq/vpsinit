# 便携用户级 TUN 安装包

这是另一台 VPS 的首次安装入口。提供 SOCKS5 代理的 IPv4 地址和端口，脚本为当前普通用户生成配置并部署用户级 TUN；用户名、UID/GID 不沿用 Mico-system 的数值。

完整流程、故障处理及隔离边界见 [VPS 用户级 TUN 一键部署](../../VPS-用户级TUN一键部署.md)。

**2026-11-15：** 当前版本在修复公网 DNS 直连泄漏和配置修改后不重载（提交 `51eb45c`）之后，又去掉了回复方向保持宿主路由、放行出网的例外：被代理用户发往公网的包在原始方向和回复方向都进入 TUN（IPv4）或被出口守卫丢弃（IPv6），关闭了外部预置一条反向 conntrack 记录就把非 DNS 的公网 UDP、IPv6、TCP 引到物理出口的通道（代价见下方行为说明）。两处都已部署到 Mico-system：第二批通过[原地升级](../xq-user-proxy/README.md#2026-11-15-原地升级为便携包版本)，第三批通过替换控制器并重载规则，均不改动核心配置、不重启核心。用本包的安装器在一台新机器上完整安装，仍未做过。

Mico-system 在 2026-11-22 23:39（服务器时间）部署了 `b98369dbc` 的控制器，沿用已加载的规则和运行中的核心。该版已修复开启时清理旧 DNS 映射的竞态，并在映射集中到期时按剩余条数继续清理。2026-11-23 06:20 又部署了 `e0d3d24` 的控制器（`attach` 等 TUN 启用后才给它路由，`check` 先核对已加载规则的摘要），同样没有重载规则，也没有重启核心。同日 17:29 核心在真实 systemd 下重启，新的 `attach` 退出码 0，核心 PID 为 `2573772`、`NRestarts=0`，随后 `check` 通过；`attach` 第一次查询时 TUN 已经启用，等待 TUN 启用的路径没有走到，这一版的修复式 `xq_proxyon` 分支在本机宿主上也没有执行过的记录。此后安装和开启前的 NSS 检查改为接受 `myhostname`（Debian 12 云镜像的 `hosts` 行里有它），并按 glibc 的读法读 `hosts` 行；2026-11-24 又把防直连规则丢失之后的修复式开启改为先装回只阻断的规则、再核对核心配置和做 NSS 检查，`check`、`xq_proxystatus` 和服务单元的几处报告随之改动。这两项修改都不改变生成的规则，2026-11-24 17:40 随 `541771c` 的控制器部署到 Mico-system，同样没有重载规则，也没有重启核心；部署之前以三个真实身份验收了这一版，修复式开启在本机宿主上还没有执行过。2026-11-25 02:07 又部署了 `77813af` 的控制器（开关 ON 期间 `check` 和 `xq_proxystatus` 也做 NSS 检查，生成的规则不变），同样没有重载规则，也没有重启核心；这一版没有以 root 重做三身份验收。

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

安装前提见[指南第 1 节](../../VPS-用户级TUN一键部署.md#1-安装前提)。其中 `/etc/nsswitch.conf` 必须恰好有一条 `hosts` 行，行里必须有 `dns`，并且只接受 `files`、`dns`、`mdns4_minimal`、`[NOTFOUND=return]` 和 `myhostname`；带 `resolve` 等其他模块或运行 nscd 的机器会被拒绝，报错指出是哪几项。行尾注释也会被拒绝：glibc 把行中间 `#` 后面的词当作模块加载，检查按同样的读法读这一行。

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
- 核心的启动记录缺失、损坏或端口不符时，它留下的 DNS 映射可能指向已经不用的入口。`xq_proxyon` 在旧核心和新核心之间删除本功能的全部 DNS 映射并确认一条不剩；这期间规则换成只阻断、不转发的形态，与 `xq_proxyoff` 清理时相同（约 0.1 秒），目标用户发往本机地址的 DNS 被守卫丢弃，不会直连。2026-11-22 修复：此前这一步在完整规则下进行，核心已停、入口立即拒绝，持续重试的解析程序留下的新映射会让 `xq_proxyon` 报“清理本功能 DNS conntrack 失败”，停在核心未启动的状态。在这一步中断时开关仍是 ON，`xq_proxystatus` 报告“开启尚未完成”，再次执行 `xq_proxyon` 继续。
- 不全局替换 DNS，不授予 sudoers 免密权限，不创建定时回滚。核心故障时保留阻断规则，不自动恢复公网直连。
- root 及其他 UID 的正常新建连接不被接管，专用 DNS/TUN 入口限制 owner。root 管理员仍能修改规则或切换身份绕过。owner 的 DNS 改写放在专用 conntrack zone `20261`，其他用户复用相同 UDP 源端口时不会再套用它，反之亦然（2026-11-14 修复，`tests/netns-check.py` 含回归测试）。
- 专用 DNS 入口是特权端口，普通用户在核心停止期间也无法监听；只有核心身份（root）发出的回复才会交给 owner（2026-11-15）。前提是 `net.ipv4.ip_unprivileged_port_start` 大于 40；root 和持有 `CAP_NET_BIND_SERVICE` 的程序属于受信任范围。
- 核心停止期间，owner 发往本机地址的 DNS 和发往公网 DNS 的 UDP 查询立即失败；发往公网 DNS 的 TCP 连接没有应答，等到程序自己的超时。都不会回退到系统 DNS 或物理出口。
- `xq_proxyoff` 先确认 conntrack 可用再动手，否则拒绝并保持原状；中途失败后重复执行即可继续清理。`xq_proxystatus` 在开关 OFF 但仍有残留时返回非零并列出残留。
- 控制器在每次删除后重新列出 DNS 映射，列表为空即清理完成。conntrack-tools 1.4.8 之前的版本遇到刚到期的条目会中途退出。删除报错后，只要剩余条数还在减少，控制器就继续尝试。连续 3 次条数没有减少，或累计删除 50 次仍有剩余，都会报错并保留防直连规则。删除命令成功但复查仍有映射时，控制器立即报错并保留规则。
- 防直连依赖自有的 nftables 表。`nft flush ruleset`、停止 `nftables.service`，或加载含 `flush ruleset` 的 `/etc/nftables.conf`（Debian/Ubuntu 默认如此）都会删除它，此后 owner 的新连接和 DNS 直连；`xq_proxystatus` 会明确报告，执行 `xq_proxyon` 重建。`xq_proxyon` 第一步装回只阻断、不转发的规则，再核对 `sing-box.json`、做 NSS 检查，然后换成完整规则；核对或检查不通过时停在只阻断的形态，owner 新发起的公网访问被阻断而不是直连，`xq_proxystatus` 报告“开启尚未完成”，处理好之后再执行 `xq_proxyon`，或用 `xq_proxyoff` 关闭（2026-11-24 修改：此前先检查、后重建，被拒绝时 owner 继续直连）。规则缺失期间已经建立的连接不会被切断，关闭时还可能把积压的数据和关闭包从物理出口发出（测过的情形里，只阻断的形态下都是如此；换回完整规则之后，取决于连接跟踪怎样登记了它）；交给共享解析服务的名称查询由那个服务自己发出，也不在此列。详见[指南第 6 节](../../VPS-用户级TUN一键部署.md#nftables-规则集被清空时)。

编辑或打包本目录不会更新任何正在运行的服务。

## 验证范围

已完成离线身份、安全与配置测试及 `sing-box check`；在隔离的测试网络中验证了 owner 专属入口、root/其他 UID 的普通 DNS/TCP/UDP，以及拒绝访问私有入口。模拟 TUN 消失时，目标用户黑洞路由保留，root 原路由和 DNS 仍可用。Mico-system 在 2026-11-23 17:29 真实重启了 systemd 服务：新的 `attach` 在真实 systemd 下完成（它第一次查询时 TUN 已经启用，没有走到等待），之后目标用户的默认 DNS 和 HTTPS 正常；这项现场记录不替代第二台新 VPS 的 systemd、软件包、网络和端到端验收。

维护者可从本目录复查：

```bash
python3 -I tests/test_portable.py       # 安装器、配置范围、与控制器的一致性
python3 -I tests/test_lifecycle.py      # 生命周期与失败注入；模拟内核，不需要 root，不执行任何命令
sudo unshare --net python3 -I tests/netns-check.py   # 真实内核，owner/其他 UID/root 三个真实身份
sudo unshare --net python3 -I tests/core-check.py --core /path/to/sing-box   # 真实控制器 + 真实 sing-box 1.14.4
```

`core-check.py` 同样只在全新的临时网络命名空间里运行。它用真实的控制器和真实的核心走完开启、关闭和修复：owner 各类 DNS 的实际路径；120 次提前放弃的查询之后没有包从物理出口发出；被 conntrack 遗忘的连接在关闭时就地复位；外部预置了 conntrack 记录的连接（DNS 和 443 端口）不从物理出口发出、也得不到应答，换一个源端口即可用；核心被杀后不漏包、其他 UID 无法占用入口；调低端口门槛后冒充的应答到不了 owner；改动磁盘配置后 `status` 如实报告、`on` 重新加载；换了版本的规则被替换；owner 的程序持续查询、被拒绝 1 毫秒后就重试时，`on` 仍能替换没有启动记录的核心。命名空间里没有 systemd，服务单元的各步骤由测试按单元文件的顺序执行；核心的 DoH 和上游在测试配置中换成本地替身，其余配置与安装时相同。

`netns-check.py` 只允许在一个全新的临时网络命名空间运行，拒绝在宿主网络中加载测试规则。没有 root 时可以用 rootless 命名空间运行它的单一身份部分。分两条命令执行：第一条先记下宿主网络命名空间，写在同一条命令前面时 shell 展开出的 `$HOSTNS` 是空的，测试会拒绝运行：

```bash
HOSTNS=$(readlink /proc/self/ns/net)
unshare --user --map-root-user --net env XQ_HOST_NETNS="$HOSTNS" python3 -I tests/netns-check.py
```

此时命名空间内只有一个身份，各角色通过规则中的 UID 常量轮流扮演，需要两个用户同时存在的检查会标为 SKIPPED；它不能代替上面的 root 运行。2026-11-15 的版本在 Mico-system（Ubuntu 22.04，内核 6.8）上执行了全部四项：离线 15 + 57 项、rootless 运行、root 下的三身份运行、`core-check.py` 连续 6 次，全部通过。2026-11-22 第四批修改的运行记录列出了离线 15 + 64 项、rootless 运行、root 下的三身份运行和 `core-check.py` 连续 6 次通过。当前版本的离线测试为 `test_lifecycle.py` 121 项、`test_portable.py` 15 项（第 95 项是 2026-11-23 为 NSS 检查新增的；其后 23 项是 2026-11-24 新增的，22 项针对修复式开启的顺序和它的报告，1 项针对 `xq_proxystatus` 里关于 `mdns4_minimal` 的一句；同日 `netns-check.py` 增加一条断言；再后 3 项是 2026-11-25 为开启期间的 NSS 检查和两处报告新增的）；2026-11-24 对 `541771c` 控制器的三身份验收为 `netns-check.py` 3/3（含这条断言）、`core-check.py` 8/8，随后部署；2026-11-23 对 `e0d3d24` 控制器的三身份验收为 `netns-check.py` 3/3、`core-check.py` 8/8，所用的 `core-check.py` 与 `2576030` 中的文件相同（此后 `fce5067` 只改了一条断言的报错文字）。本机另有一次真实 systemd 重启，新的 `attach` 完成，但没有走到等待（见上文）。详细拆分见[验证记录](../../VPS-用户级TUN一键部署-验证记录.md)。

2026-11-23 在独立网络命名空间内用三个真实身份复核了当时的部署版 `b98369dbc`、合并前的候选版和 `e0d3d24` 的控制器，逐项结果见[三身份验收记录](../../VPS-用户级TUN一键部署-验证记录.md#2026-11-23-三身份验收)。2026-11-24 对 `541771c` 的三身份验收见[验证记录](../../VPS-用户级TUN一键部署-验证记录.md#2026-11-24-修复式开启先恢复防直连再做-nss-检查)。
