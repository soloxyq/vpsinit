# VPS TUN 固定值与访问权限审计

日期：2026-11-14。范围：本机当前用户级代理与独立 `xq_tun` 模式，不包含另一台 WSL 的历史归档。

本轮完成检查、入口加固和不停服验证。两核心 PID 仍为 `2607788`、`2460344`；没有停止服务、切换 OFF、清理既有 conntrack 或设置定时回滚。

## 固定值检查

| 项目 | 检查结果与处理 |
| --- | --- |
| 本机 IP | 转发控制器没有写死 `192.168.5.173`；验收器原有的固定 IP 断言已移除，改为从上游路由 `prefsrc/src` 读取 |
| 物理接口 | 验收器原有 `ens160` 已改为从实际路由读取；强绑测试和维护保护规则也使用动态接口 |
| 公网出口 | `179.255.139.228` 仅在文档中记录实测值；运行配置及验收没有要求出口必须等于它，始终实时查询 |
| 系统 DNS | 验收器从 `/etc/resolv.conf` 读取实际 IPv4 resolver，不再固定要求 `127.0.0.53` |
| 代理上游 | 用户指定的 `192.168.5.34:4066` 保留，是唯一的代理端口；旧端口 `16791` 的兼容改写已于 2026-11-14 删除 |
| 授权身份 | `xuqian`、UID/GID `1006:1006` 保留，不能改为任意调用者 UID，否则会扩大授权 |
| 安装主机与架构 | `Mico-system`、`x86_64` 是防止误装的检查，不参与实际转发 |
| TUN 内部地址 | `172.30.254.1/32`、`172.30.255.1/30` 及对应 DNS 地址保留；不是物理网卡 IP，启用时检查冲突 |
| 专属 DNS 入口 | `127.0.0.1:1053` 保留，本轮新增访问限制 |
| DoH | `1.1.1.1:443`、`cloudflare-dns.com` 和 `/dns-query` 是 DNS 服务配置，不是出口 IP |
| 内部资源 | namespace/TUN 名、路由表 `20261`、conntrack zone `20261`（2026-11-14 新增）、优先级 `18410`、mark 位、MTU `1280`、nft hook 顺序等保留，属于配套配置 |
| LAN 例外 | 私网、链路本地、多播/广播集合是用户要求的策略，不是写死当前网卡地址 |
| 版本与校验 | sing-box `1.14.4`、架构、SHA256、绝对工具路径和 root 配置路径保留，用于版本及提权安全 |
| 查询目标 | `api.ipify.org`、`icanhazip.com`、`example.com` 等是测试服务地址，返回值不是固定出口 |

动态发现不等于忽略历史基线差异。若管理员合法更改本机地址或接口，仍需另行更新网络基线；验收不会静默接受无关网络变更。

## 新的访问限制

- 普通流量仍只按 xuqian 的 socket UID 接管。root 和其他 UID 自己新建的普通连接不自动进入用户 TUN。
- 本机私有 DNS 只允许 UID1006、其已归属连接的合法后续包和回复。root/其他 UID 显式访问 `127.0.0.1:1053` 被拒，原系统 DNS 保持可用。
- 两套 TUN 出口均增加 owner 限制；其他 UID 无法借用它们发起连接。
- 已知非 owner UID 的拒绝规则排在 OWNER 回退之前，防止其他 UID 复用旧连接标记获得权限。OWNER 只作为无法取得 socket UID 的后续包回退。
- 公共 `xq_tun` 和 Bash 快捷函数只接受 EUID1006。独立控制器的 `run/shell` 还要求原 sudo 调用者为 UID1006；普通 root 调用也拒绝。
- root 的安装、状态查询和服务管理权限保留。内部 namespace 入口仍校验实际网络环境、挂载和 resolver，再降权为 xuqian。

## 不停服实测

| 测试 | 结果 |
| --- | --- |
| xuqian 的私有 DNS UDP/TCP | 成功 |
| root、UID65534 的私有 DNS UDP/TCP | 拒绝，命中专属 ACL 计数 |
| root、UID65534 的原系统 DNS及受控本地 HTTP/UDP | 正常 |
| UID65534 复用 xuqian 刚关闭的 UDP 五元组访问私有 DNS | 拒绝 |
| root 给 socket 显式打 TUN 路由标记 | 被专属 TUN ACL 丢弃，有计数证据 |
| root、UID65534 在独立 namespace 中主动发起 TUN TCP | 拒绝，命中 guard 计数 |
| root/其他 UID 调用公开 `xq_tun`、未授权 backend `run` | 拒绝 |
| root 加载用户 helper 后调用 `xq_proxyon` | 拒绝，未操作网络 |
| xuqian 真实终端调用 `xq_tun run /usr/bin/id` 和 `xq_tun shell` | 成功，身份仍为 `1006:1006` |
| 独立环境内 `xq_tun run claude --version` | `2.1.325 (Claude Code)` |
| 用户级现有/新进程 DNS、无代理变量 HTTPS | 成功，本次出口 `179.255.139.228` |
| 其他路由、resolver、转发参数与无关 nftables | 与原基线一致；只更改自有 guard |
| 两个核心 PID | 全程不变 |

访问测试与在线验收均退出 `0`。最终日志和备份在 `/var/backups/xq-tun-access-fvqheldr/`；首次加固前的完整备份在 `/var/backups/xq-tun-access-me5f13pp/`。

## 明确边界

**无法阻止真正的 root 管理员主动绕过。** root 可修改规则、替换程序、修改环境或切换为 UID1006。当前实现保证默认策略不接管 root，并拒绝其普通应用入口，不是防不可信管理员的隔离方案；拥有等价管理权限的账号同理。

内核 conntrack 五元组不包含用户身份。其他 UID 若碰巧复用残留的 owner DNS NAT 五元组，ACL 会拒绝该次私有入口访问，而不授予代理权限；该次解析可能需要重试。因此不能把共享宿主网络描述成所有异常情形下的跨用户强隔离。本轮没有为此修改其他用户的 conntrack zone、清除全机连接或更改全局 DNS。

**2026-11-14 后续修复：** owner 的 DNS 改写已移入专用 conntrack zone `20261`。zone 只设置在 owner 的 DNS 流量和私有入口的回复上，其他用户的 conntrack 仍在默认 zone，未被改动；复用源端口不再串用映射。详见[用户级说明](scripts/xq-user-proxy/README.md)。

本轮限制的是这台 VPS 的 TUN 和私有入口。其他用户自行直连远端 `192.168.5.34:4066` 不经过本 TUN；若要限制远端代理本身，需在代理端配置认证/ACL，不能顺带封掉其他用户正常的 LAN 连接。

继续遵守用户要求：没有定时回滚，故障不自动 OFF，不自动恢复公网直连。

## 2026-11-15 补充：便携包的固定值与 DNS 入口归属

以上各节记录的是 2026-11-14 部署在 Mico-system 上的固定版本，它的专属 DNS 入口是 `127.0.0.1:1053`。2026-11-15 本机已[原地升级](scripts/xq-user-proxy/README.md#2026-11-15-原地升级为便携包版本)为[便携安装包](scripts/xq-user-tun/README.md)的版本，以下内容自那时起也是本机的现状。

新增或改变的固定值：

| 项目 | 取值与理由 |
| --- | --- |
| 专用 DNS 入口 | `127.0.0.1:40`，取代非特权的 `1053`。40 在 IANA 未分配，低于常见的 `ip_unprivileged_port_start` 调整值（80、53），也不在 bindresvport/rresvport/NFS 使用的 512–1023 范围。控制器中只有一个常量，模板、配置校验、全部 nft 规则、预检绑定和安装器参数校验都取自它 |
| 核心身份 | UID 0，即核心单元的运行用户 root。规则只允许这个身份从 40 端口发出回复；以后改用专用账号时只需改这一个常量 |
| 核心单元能力 | `CAP_NET_ADMIN`、`CAP_NET_RAW`，新增 `CAP_NET_BIND_SERVICE`（绑定特权端口所需） |
| 端口门槛 | `net.ipv4.ip_unprivileged_port_start` 必须大于 40；内核没有这个 sysctl 时按固定门槛 1024 处理 |
| 默认 resolver | 只判断 `/etc/resolv.conf` 中 glibc 实际使用的前 3 个 nameserver；分类所用的直连范围就是生成 nft 规则的同一组常量 |
| DNS 改写范围 | 只改写发往本机地址的查询；哪些地址属于本机在运行时向内核查询（`fib daddr type local`），不写死。发往公网 DNS 的查询不改写，进入 TUN |
| 从 TUN 进入的包 | `tun_input`/`from_tun` 两条链：必须是 owner 已有连接的回复，或发给本机的 RST |
| 启动记录 | `/run/xq-user-proxy/core.json`：核心这次启动加载的配置摘要、上游和 DNS 入口端口，由服务单元的 `prepare`/`attach` 写入 |

入口归属的保证：

- 绑定 40 端口需要 `CAP_NET_BIND_SERVICE`。普通用户（包括 owner 自己）在核心停止期间也无法监听 `127.0.0.1:40` 或 `0.0.0.0:40`，owner 被改送的查询不会交给其他普通进程；没有监听者时查询立即被拒绝，不回退到系统 DNS。
- raw 优先级的 output 链在“把 `127.0.0.1:40` 发出的包归入 DNS zone”之前，先丢弃源端口为 40 而 socket UID 不是核心身份的包。冒充的回复进不了 owner 的 conntrack 映射。内核生成的 RST/ICMP 没有 socket，不匹配该规则，核心停止时仍能快速失败。
- 请求方的入口限制、专用 zone、标记位和局域网例外均未改变；其他用户的普通流量不受影响。

限度：

- root 和持有 `CAP_NET_BIND_SERVICE` 的程序（包括带文件能力的可执行文件）可以绑定该端口，属于受信任范围。
- 端口门槛被调到 40 或以下时，普通用户可以绑定入口并读到 owner 的查询；安装和首次开启会拒绝，开启期间由 `status`/`check` 报告为异常。此时回包身份规则仍丢弃冒充的回复，但不能阻止查询被读取。
- 状态命令不检查监听进程；保证来自内核对特权端口和发送身份的限制。

验证状态：修复前，隔离命名空间中没有 `CAP_NET_BIND_SERVICE` 的进程可以绑定 `1053`、收到 owner 的查询，其应答被 owner 接受；修复后，同一进程绑定 40 端口得到 `PermissionError`，owner 立即得到连接被拒绝。回包身份规则、各类 resolver 的路径已在 rootless 命名空间中以单一身份实测；以真实的其他 UID 进行的测试（`sudo unshare --net python3 -I tests/netns-check.py`）已于 2026-11-15 执行并全部通过，包括其他 UID 绑定 40 端口失败、调低门槛后其他 UID 冒充入口的回复被丢弃。
