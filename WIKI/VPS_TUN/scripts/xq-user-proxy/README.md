# Mico-system 用户级 TUN 代理

**新 VPS 请使用 [便携一键部署指南](../../VPS-用户级TUN一键部署.md)。** 本目录保留 Mico-system 的历史部署及安装器，不用于在其他机器首次安装。

**2026-11-15：Mico-system 已从本目录的冻结版本原地升级为[便携安装包](../xq-user-tun/README.md)的版本。** 现在运行的控制器、服务单元和核心配置来自 `scripts/xq-user-tun/`（提交 `51eb45c`）。本目录的 `xq-user-proxyctl`、`xq-user-proxy.service`、`sing-box.json`、`verify.py` 等是升级前版本的记录，不再是本机现状，也不再维护。升级过程和结果见[下文](#2026-11-15-原地升级为便携包版本)；日常命令没有变化。

冻结版本有下列已确认的缺陷，升级后不再存在：

1. 开启中途失败、路由表 `20261` 尚未创建时，`off` 因 `FIB table does not exist` 每次都失败，无法完成清理，xuqian 的公网访问一直被阻断；
2. `off` 先删除开启标记、换规则、停核心，之后才发现缺少 conntrack，此时原来可用的状态已被破坏；
3. 开关 OFF 但核心、guard 等残留仍在时，`status` 仍返回 0；
4. `status` 固定声称“默认系统 DNS 和公网 DNS 查询经代理解析”。默认 DNS 是局域网地址时实际直连、不经代理，是 `::1` 或公网 IPv6 时实际被阻断，均没有检测；
5. 私有 DNS 入口 `127.0.0.1:1053` 是非特权端口。多用户主机上，核心没有监听时其他普通用户可以占用它，收到 xuqian 被改送的 DNS 查询并返回应答；现有入口限制只验证请求方，不验证接收方和回复方；
6. 修改 `/etc/xq-user-proxy/sing-box.json` 的上游后，状态正常时的 `on` 不重启核心，新配置不会加载；`status` 显示的上游是控制器中的固定值，看不出实际加载的配置；
7. 发往公网 DNS 的查询也被改写到回环入口。程序在应答到达之前放弃查询时，内核替已关闭的 socket 补发的 ICMP 错误和 TCP RST 找不到被改写的连接记录，按原目的地址从物理网卡直接发往该 DNS 服务器，其中 UDP 的 ICMP 错误带有应答内容（含域名）。默认解析走 `127.0.0.53`，补发的包不离开本机；只有直接向公网 DNS 发查询的程序会触发。
8. 回复方向的包保持宿主路由并放行出网，本意是让 owner 自己的服务应答外部访问。外部先向本机发一个包、在 conntrack 中留下一条反向记录（伪造源地址的 UDP、广播帧触发的 TCP、松散跟踪下的中途段），就能把 owner 随后从同一端口发往同一地址的**非 DNS 公网包**（UDP、IPv6、TCP）当作该记录的回复，从物理网卡直出，暴露真实出口。冻结版和便携包首版都有此例外；DNS 因按目的地址在两个方向都进 TUN 而不受影响。

第 1 至 5 项在便携包的 `f720a10` 中修复，第 6、7 项在 `51eb45c` 中修复。第 8 项在便携包首版仍在，于 `1a58d33` 去除（见下文“第三批修改”）。依据 2026-11-15 的复核：第 1、5、7 项在真实内核的隔离网络命名空间中复现，第 7 项另在本机网卡上被动抓包确认，第 8 项在隔离命名空间用真实内核对非 DNS UDP、IPv6、TCP 三种复现，其余为离线复现。“日常操作”之后各节是 2026-11-14 的记录，保持原样；其中的 `1053` 端口、`verify.py` 和“不停服检查”的命令都属于冻结版本。

## 2026-11-15 原地升级为便携包版本

用 [upgrade-to-portable.py](upgrade-to-portable.py) 完成，服务器时间 20:23:38 开始、20:23:43 结束，退出码 0。脚本依次：

1. 只读检查：每个受管文件必须正好是冻结版的文件（或已经是新版），新规则和核心配置有效，新入口端口 `40` 空闲，开着的安装通过自己的 `check`；
2. 把将要替换的文件、当时的规则表和路由备份到 `/var/backups` 下的新目录；
3. 原子替换各文件，复制核心程序，`daemon-reload`；
4. 开关为 ON 时执行一次新版控制器的 `on`：规则表在一个 nft 事务里换成新版，停止旧核心，删除本功能自己的 DNS 映射（它们指向旧入口 `1053`），用新服务单元启动核心。防直连规则、策略规则和黑洞路由全程存在，这几秒内 xuqian 的公网访问是被阻断而不是直连；
5. 以 xuqian 的身份验证：`check`、监听端口、默认 DNS、发往公网 DNS 的查询、HTTPS 出口。

第 3 至 5 步失败时，脚本把旧文件放回并由冻结版控制器恢复规则和核心。这是回到升级前的代理状态，不是改为直连，也没有任何定时回滚。

本机上的变化：

| 路径 | 变化 |
| --- | --- |
| `/usr/local/sbin/xq-user-proxyctl` | 换成便携包的控制器，与仓库文件逐字节一致 |
| `/etc/systemd/system/xq-user-proxy.service` | 换成便携包的服务单元：增加 `CAP_NET_BIND_SERVICE` 和 `ExecStartPre=… prepare`，核心改用下面的副本 |
| `/etc/xq-user-proxy/sing-box.json` | DNS 入口端口 `1053` → `40`，其余内容不变 |
| `/etc/xq-user-proxy/settings.json` | 新增：用户 xuqian（UID/GID 1006）和上游 `192.168.5.34:4066` |
| `/etc/xq-user-proxy/managed-by` | `xq-user-proxy-v1` → `xq-user-tun-portable-v1` |
| `/usr/local/lib/xq-user-proxy/bin/sing-box` | 新增：sing-box 1.14.4 的副本，与 `/usr/local/lib/xq-tun/sing-box-1.14.4/sing-box` 相同；`xq_tun` 继续使用原文件 |
| `/usr/local/lib/xq-user-proxy/verify.py` | 删除，备份中保留。日常检查改用 `xq_proxystatus` 或 `sudo /usr/local/sbin/xq-user-proxyctl check` |
| `/run/xq-user-proxy/core.json` | 新增（运行时）：核心这次启动所加载配置的记录 |
| `/var/lib/xq-user-proxy/upgrade-backup` | 新增：记下本次备份的位置 |

没有改动：`~/.bashrc`、`/usr/local/share/xq-tun/xq-tun.bash`（快捷函数仍调用同一路径的控制器）、`xq-tun.service` 及其命名空间、`/etc/resolv.conf`、其他 nft 表、策略规则和路由。

结果：

- 用户级核心 PID `2607788` → `780699`，`NRestarts=0`；`xq-tun.service` 的 PID `2460344` 未变。
- `check` 通过；核心监听 `127.0.0.1:40`（TCP 和 UDP），`1053` 不再有监听；conntrack 中没有指向旧入口的映射；启动记录与磁盘配置一致。
- xuqian 的默认 DNS、直接发往 `1.1.1.1` 的 UDP 和 TCP 查询、发往 `127.0.0.53` 的 TCP 查询都得到正确应答；发往公网 DNS 的连接在 conntrack 中未被改写、带 owner 标记。发往局域网 DNS `192.168.5.2` 的 UDP 查询直连，公网 ping 仍被阻断。HTTPS 出口仍是 `179.255.139.228`。
- 本功能之外的 nft 表、策略规则、路由和 `/etc/resolv.conf` 前后一致。
- 被动抓包对比（`tcpdump -ni ens160 host 9.9.9.10`，期间以 xuqian 身份向 `9.9.9.10` 发出 10 次 UDP 和 10 次 TCP 查询并立即关闭 socket）：升级前物理网卡上出现 80 个包（10 个带应答内容的 ICMP 端口不可达，70 个 TCP RST）；升级后 0 个。
- 升级日志里“直接查询公网 DNS 1.1.1.1 得到 0.0.0.0”一行是验证脚本解析应答的错误（把应答末尾的 EDNS 记录当成了地址）。该项的判定依据是连接未被改写且带 owner 标记，不受影响；实际应答已用 `dig` 核实，脚本已修正。

备份和日志：`/var/backups/xq-user-proxy-upgrade-20261115-202339-hgiljq0u/`（被替换的文件、当时的规则表和路由、`upgrade.log`）。升级成功后没有提供回退命令。

升级之前，[upgrade-rehearsal.py](upgrade-rehearsal.py) 在一次性的网络、挂载和 PID 命名空间里，用真实的两版控制器、真实的服务单元文件和真实的 sing-box 演练了这个脚本，systemd 由替身代替。五个场景全部通过：开着升级、关着升级、新核心起不来时恢复冻结版、中途中断后再次执行完成、只检查不改动（以及新端口被占用时在改动之前拒绝）。演练中 owner 和另一个用户持续发 DNS 查询：另一个用户的查询全部得到应答；owner 的查询只在核心重启的约 0.2 秒内失败；长期复用同一个 socket 的 owner 程序升级后继续得到应答。

演练中观察到一种只在切换瞬间出现的情况：按旧规则被改写、且正好在换规则前一刻关闭的公网 DNS 的 TCP 连接，内核为它重传的几个不带内容的 FIN 会从上行发出（旧规则下的连接记录在专用 zone 里，新规则找不到它）。这是只在 20:23 那次升级（换 DNS 入口、重启核心）才涉及的边界；第三批重载规则没有改 DNS zone、没有重启核心，不涉及。本机升级时没有对切换的那一两秒做抓包，因此无法断定当时真机上没有发出这类包，只能说演练里是不带应答内容的 FIN、持续约几秒。

升级后的不同之处：

- 专用 DNS 入口是特权端口 `127.0.0.1:40`，其他普通用户在核心停止期间也无法占用。
- 只有发往本机地址的 DNS（包括默认的 `127.0.0.53`）改送该入口；发往公网 DNS 的查询不改写，与其他公网流量一样进入 TUN，由核心应答。
- `xq_proxystatus` 显示运行中的核心实际使用的上游，并逐个列出默认 nameserver 的实际路径；开关 OFF 但有残留时返回非零。
- 更换上游：同时修改 `/etc/xq-user-proxy/settings.json` 和 `sing-box.json` 中的地址和端口，然后执行 `xq_proxyon`，它会重启核心加载新配置。
- 其余说明以[便携包指南](../../VPS-用户级TUN一键部署.md)为准。

当前安装：`xq-user-proxy.service` 接管宿主 xuqian（UID 1006）的所有会话；`xq-tun.service` 是另一个用于 `xq_tun run` 的独立命名空间服务。

2026-11-14 已完成[固定值与权限审计](../../VPS-TUN固定值与访问权限审计.md)：本机地址/接口和出口动态获取，私有 DNS 与 TUN 出口限制 owner 使用；root/其他 UID 的普通入口调用被拒。真正的 root 管理员仍可修改规则或切换 UID，不能据此声称可防管理员绕过。

修复后已完成不停服验收，保持 ON，出口为 `179.255.139.228`。真实交互测试确认 `xq_proxyon` 返回原 shell，PID、namespace 和工作目录不变，新终端自动沿用用户状态。其他 UID 不被本功能接管；结果与限制见[最终验收记录](../../VPS-用户级TUN验收记录.md)。

## 2026-11-15 第三批修改：去掉回复方向的直接出网例外

升级之后 codex 复核时指出，上文第 8 项（非 DNS 的公网 UDP／IPv6 被预置反向记录引出）应优先实测，不能只当作管理员边界。处理结果：

1. **实测**：在一次性网络命名空间里用真实内核确认该泄漏成立——对非 DNS 公网 UDP、IPv6 和 TCP（广播帧预置反向记录）三种，owner 随后从同一端口发出的包都从上行直出。DNS（公网 53 端口）因两个方向都被强制进 TUN，不受影响。
2. **修改**（`1a58d33`）：删去 `target_route` 和 `target_output` 中对 `ct direction reply` 放行的两条规则。被代理用户发往公网地址的包，无论 conntrack 算作原始方向还是回复方向，一律走 TUN 路由（IPv4）或被出口守卫丢弃（IPv6）。预置的记录不再能把这类包引到物理出口；那条连接本身并不因此可用，见本节末尾的更正。
3. **代价**：被代理用户自己的服务无法应答公网客户端（应答进入 TUN，在那里不对应核心的任何连接）。发往局域网和回环的应答仍按各自规则保持宿主路由。本机上 xuqian 没有监听公网的服务，不受影响。

本机生效方式（服务器时间约 21:32）：替换 `/usr/local/sbin/xq-user-proxyctl` 为新版控制器，执行 `xq_proxyon`。已加载的规则被识别为“不是当前控制器生成的版本”，控制器在一个 nft 事务里把整张表换成新版；**不重启核心、不清空 conntrack、不改动核心配置**。

结果：

- `check` 前后都通过；`target_output` 和 `target_route` 中 `ct direction reply` 规则数由 1、1 变为 0、0；表的其余部分不变。
- 用户级核心 PID `780699` 未变，`NRestarts=0`；`xq-tun.service` 的 PID `2460344` 未变。
- xuqian 的默认 DNS、`dig @1.1.1.1`（UDP 和 TCP）、发往局域网 DNS `192.168.5.2` 的 UDP 查询都正常；HTTPS 出口仍是 `179.255.139.228`。
- `192.168.5.2` 的 53/TCP 对 root 和 xuqian 都立即拒绝连接（`connection refused`）。root 不受本功能管辖，xuqian 发往该地址的包按局域网规则直连，所以这是该网关本身不提供 TCP 的 DNS，与 TUN 无关。
- 替换前的控制器备份在 `/var/backups/xq-user-proxyctl-before-reply-fix-20261115-213230`（含当时的规则表 `*.nft-before.txt`）。回退：`cp -a` 该备份回原路径再执行 `xq_proxyon`。

验证（提交 `1a58d33`）：`tests/test_lifecycle.py` 57 项通过，断言两条链中再无 `ct direction reply` 例外；`tests/netns-check.py` 的预置检查扩展到 DNS、其他 UDP、IPv6、TCP 四类并断言都不直出，对照把旧例外放回后 UDP 和 IPv6 重新直出，rootless 与 root 三身份两种运行通过；另有单独的 TCP 预置实验确认修复前直出、修复后进 TUN、owner 服务无法从上行应答公网客户端。

### codex 的真机复核与一处更正

规则生效后 codex 在真机上复核：两条例外已删除，两个核心的 PID 未变；默认及公网 DNS、两套 HTTPS 正常，出口均为 `179.255.139.228`；root 和其他测试 UID 的原 DNS 和本地通信正常，访问私有 DNS 入口被拒绝。抓包：10 次 UDP 加 10 次 TCP 的 DNS 提前关闭、5 次非 DNS UDP 探测期间，物理接口出站 0 包，同期 TUN 上 128 包，抓包校准成功、内核丢包 0。

更正：提交 `1a58d33` 的说明和本节最初的文字写的是“预置记录只会让这类包经代理发出”，指南里写的是“连接照常可用”。后半句没有实测，也不成立。用真实核心在隔离命名空间里实测（owner 向一个公网地址发 DNS 查询，核心在 TUN 内应答）：

| 情形 | owner 的结果 | 从物理出口发出的包 |
| --- | --- | --- |
| 没有预置记录（UDP、TCP） | 得到应答 | 0 |
| 外部预置记录后，从该端口发往该地址（UDP、TCP） | 超时，得不到应答 | 0 |
| 同时从另一个源端口（UDP、TCP） | 得到应答 | 0 |
| 记录消失后，从原端口（UDP、TCP） | 得到应答 | 0 |

原因是核心的应答从 TUN 回来时，在 conntrack 看来属于外部先发起的那个方向，被 TUN 入口规则丢弃。所以预置方无法让流量直出，但可以让特定“源端口 → 地址”的连接在记录存在期间得不到应答；记录的寿命是内核的 conntrack 超时（UDP 30 至 120 秒，TCP 握手阶段 60 至 120 秒），每次重试都会刷新它。`tests/core-check.py` 新增这一项检查（DNS 和 443 端口、UDP 和 TCP 各一条预置的连接）；在 `51eb45c` 的控制器上它因 443 端口的 UDP 包从上行发出而失败。

控制器里对应的注释同时改正。改动只有注释，生成的规则逐字不变：22:07 把它装回 `/usr/local/sbin/xq-user-proxyctl`（与仓库文件逐字节一致），`check` 直接通过，已加载规则的摘要和状态里的记录都没有变化，没有重载规则，两个核心的 PID 未变。此前的文件备份在 `/var/backups/xq-user-proxyctl-before-comment-fix-20261115-220704`。

## 2026-11-22 第四批修改：开启时清理旧 DNS 映射的竞态

来自另一次独立审查。问题、复现和测试见[指南第 9 节](../../VPS-用户级TUN一键部署.md#9-已验证范围)。改动只在控制器里：

1. `xq_proxyon` 发现核心没有可用的启动记录时，在旧核心和新核心之间删除本功能的 DNS 映射。这一步现在与 `xq_proxyoff` 一样，先把规则换成只阻断、不改送的形态，删除并确认之后再换回。此前它在完整规则下进行：核心已停、入口立即拒绝，xuqian 的程序每被拒绝一次 UDP 查询就留下一条新映射，落在删除和复查之间就让 `xq_proxyon` 失败，核心停在未启动的状态（防直连规则仍在，不是直连）。
2. 删除 DNS 映射时，conntrack 报错而映射还在就再删一次，最多 3 次。本机的 conntrack-tools 1.4.6 遇到已自行消失的条目会中途退出。
3. 开关为 ON 而规则停在只阻断形态时（第 1 项的那一步被中断），`check` 和 `xq_proxystatus` 报告“开启尚未完成”，不再是“用户代理未开启”。
4. 给三条与后面规则重复的规则补了说明。生成的规则逐字不变。

本机日常不会走到第 1 项的分支：启动记录在，入口端口是 40。按上文记录，2026-11-15 20:23 的原地升级走过它一次（冻结版的核心没有启动记录），那次没有遇到这个竞态。

本机生效方式（服务器时间 19:50:45）：把 `/usr/local/sbin/xq-user-proxyctl` 换成新版控制器（同目录写临时文件后改名），与仓库文件逐字节一致。没有执行 `xq_proxyon`，没有重载规则，没有重启核心。

结果：

- 替换前后 `check` 都通过，`xq_proxystatus` 返回 0。新控制器接受已加载的规则：规则表的摘要与状态记录一致，状态里的规则版本记录就是新控制器现在会生成的版本。
- `/run/xq-user-proxy/state.json` 和 `core.json` 没有被改写，修改时间仍是当天 18:40:17。
- 用户级核心 PID `1742943` 未变，`NRestarts=0`；`xq-tun.service` 的 PID `2460344` 未变。
- xuqian 的默认 DNS 正常，出口仍是 `179.255.139.228`。
- 替换前的控制器备份在 `/var/backups/xq-user-proxyctl-before-dns-cleanup-fix-20261122-195045`，与提交 `cf48933` 的文件一致。回退：把该备份 `sudo cp -a` 回原路径；规则没有变，不需要重载。

用户级核心的 PID 与上文的 `780699` 不同，是因为当天 18:40 为验证开关执行过一次 `xq_proxyoff` 和 `xq_proxyon`，与本批修改无关。

真实 systemd 下的这条修复分支没有在本机执行。验证它需要先让核心失去启动记录，再执行 `xq_proxyon` 重启核心，会中断 xuqian 当时的公网连接；它的行为由 `tests/core-check.py`（真实控制器、真实核心、systemd 由替身代替）覆盖。

## 2026-11-22 部署 `b98369dbc` 的控制器

23:39:25（服务器时间），在 `/usr/local/sbin` 内原子替换 `xq-user-proxyctl`。原先的 `09ed7b4` 已备份至 `/var/backups/xq-user-proxyctl-before-b98369d-20261122-233925`。安装后的 SHA256 为 `a0ef06a68b7eb742f98e312ccd96e630a645a7a1bc97e43e4edee00dd5cbe4ea`，与 `b98369dbc` 中的文件一致。

替换前后 `check` 均通过。替换后 `status` 返回 0，开关为 ON。核心 PID 均为 `1742943`，`NRestarts=0`。分别比对已加载 nft 表的规则摘要、`state.json` 和 `core.json` 的文件摘要，三项均与替换前一致。xuqian 两次均能通过默认 DNS 解析 `example.com`，关闭 curl 的显式代理后访问 `api.ipify.org` 均得到 HTTP 200，出口为 `179.255.139.228`。

本次改善的是 `off` 或修复式 `on` 遇到 DNS 映射集中到期时的清理成功率。部署验收检查了正在运行的代理，清理负载的对照数据见[指南第 9 节](../../VPS-用户级TUN一键部署.md#9-已验证范围)。

## 日常操作

```bash
source ~/.bashrc        # 已有终端刷新快捷函数；新登录终端自动加载
xq_proxystatus          # 查询用户级代理状态
xq_proxyon              # 开启/恢复全部宿主会话的用户代理
xq_proxyoff             # 完整关闭用户代理，恢复原网络
```

以上三个快捷函数作用于 xuqian 的全部宿主会话，不是单终端开关。独立命名空间内请先 `exit` 回宿主再操作；其中 `xq_proxystatus` 会报告当前命名空间状态。

原 shell 的变量和工作目录保留，`xq_proxyon && claude` 现在可正常使用。新会话的网络状态来自内核规则，不依赖导出代理环境变量。既有公网长连接切换时可能需要重新建立；OFF 不会替其他进程清除其已有的代理变量或关闭既有代理连接。

指定程序仍使用 `xq_tun run claude`，其独立代理不随用户级 OFF 停止。root/sudo、其他 UID、容器或共享守护进程代发的请求不属于宿主 UID1006 接管范围。

明确的控制器入口为 `sudo /usr/local/sbin/xq-user-proxyctl {on|off|status|check}`。不要用 `service xq-user-proxy stop` 或 `systemctl stop xq-user-proxy` 作为正常 OFF：它们只停核心，保留公网防直连 guard 和黑洞路由。核心停止时可用控制器 `on` 恢复；完整关闭用 `off`。本功能重启默认 OFF。

## 2026-11-14 更新后的网络范围

- 私网、链路本地、多播/广播流量绕过 TUN，按宿主路由直接发出，包括显式访问局域网 DNS 的 TCP/UDP 53。
- IPv4 直连：`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`224.0.0.0/4`、`255.255.255.255/32`。
- IPv6 直连：`fc00::/7`、`fe80::/10`、`ff00::/8`。是否可达仍由现有接口、路由及目标决定。
- 当前物理局域网 `192.168.5.0/24` 走 `ens160`。Docker 的直连私网仍走相应桥接接口，不强制送到物理网卡。本次没有新增私网路由。
- 公网 IPv4 TCP 经 `192.168.5.34:4066`；普通公网 UDP、ICMP/ping、IPv6 主动出站仍阻断。
- 默认系统 DNS（127.0.0.53）和指定公网 DNS 的查询仍由本地 1053 接管并通过代理 DoH；显式查询局域网 DNS 则直连。
- 只使用 `.34:4066` 一个代理端口；原 `.34:16791` 兼容改写已于 2026-11-14 删除，见下节。

## 2026-11-14 删除 16791 兼容改写

现在只使用 `192.168.5.34:4066` 一个代理端口。删除内容：

- 控制器 `dns_output` 链中把 UID1006 新建的 `.34:16791` TCP 连接改写到 `.34:4066` 的 DNAT 规则、配套的 conntrack 标记位 `0x08000000`，以及 `status` 中的相应说明；
- `verify.py` 中的 16791 CONNECT/TLS 检查；
- `~/.bashrc` 中旧版 `xq_proxyon/xq_proxyoff`（导出 `http://192.168.5.34:16791`；此前已被 shell helper 覆盖，实际不生效）。备份：`~/.bashrc.before-remove-16791-20261114-024758`。
- VS Code 远程端设置 `~/.vscode-server/data/Machine/settings.json` 的 `http.proxy` 由 16791 改为 `http://192.168.5.34:4066`。VS Code 会把它注入扩展启动的进程（如 Codex 扩展的 `codex`）。备份：`settings.json.before-remove-16791-20261114-031708`。

线上按 `harden-access.py` 的不停服流程更新：只原子替换已安装文件和自有 nft 表；两核心 PID `2607788`、`2460344` 不变，自有资源以外的宿主快照前后一致，`xq_tun` 命名空间 guard 未变。备份与日志：`/var/backups/xq-tun-access-mkcrhtaq/`。更新前已在一次性网络命名空间中对比新旧规则：新连接不再改写；已建立的改写连接换表后继续工作；DNS 接管及其他 UID 的结果不变。

更新后的影响：

- 已被改写的既有连接保留到自然关闭；conntrack 中的 NAT 映射不随规则删除。
- 仍带旧代理变量（如 `http_proxy=http://192.168.5.34:16791`）的已运行程序，新连接改为直连 `.34` 上真实的 16791 端口（属局域网直连，不再改送 4066）。当天检查时仍带这些变量的是 Codex：VS Code 扩展启动的 `codex`（在本地 VS Code 执行 `Developer: Reload Window` 即可按新的 `http.proxy` 重启），以及 2026-10-21 起运行的 `codex app-server` 后台守护进程（无 codex 任务时在新终端执行 `codex app-server daemon restart`；会中断进行中的 codex 工作）。其他程序在新终端，或执行过 `xq_proxyon`（会清除旧代理变量）的终端中重新启动即可。
- `/etc/systemd/system/docker.service.d/http-proxy.conf` 仍把 Docker 守护进程的代理设为 `192.168.5.34:16791`。这是系统级 root 服务配置，从未受本规则影响；修改需要重启共享的 `docker.service`，会中断正在运行的容器，本次未改动。
- 新版 `verify.py` 不停服验收通过，退出码 `0`。原安装前基线已经过期（见下文“不停服检查”），本次改用派生基线。

## 2026-11-14 DNS 改写的 conntrack 隔离

宿主只有一张 conntrack 表，所有用户共用。原先 xuqian 的 DNS 改写（发往 `127.0.0.53` 或公网 DNS 的 53 端口 → `127.0.0.1:1053`）也记在这张表里，UDP 映射会保留约 30 秒。这期间如果其他用户的新查询恰好用了相同的源端口，就会套用 xuqian 的映射，被私有 DNS 的访问限制拒绝，立即收到一次 `EPERM`；反方向则是 xuqian 的那次查询失败。重试换了新端口即可恢复，概率很低，但确实影响其他用户。

修复：在自有表中新增 raw 优先级链 `dns_zone_output`，在 conntrack 查表之前，把以下流量放入专用 conntrack zone `20261`：

- xuqian 需要改写的 DNS 查询；
- xuqian 直接访问 1053 的查询；
- `127.0.0.1:1053` 发出的回复；
- 针对 1053 的 ICMP 不可达，使核心停止时仍立即报错，而不是等到超时。

其他用户的流量从不进入该 zone。OFF 按 DNS 标记清理时覆盖所有 zone；preflight 新增了 zone 占用检查。便携包控制器同步修改，并已重新打包。

验证：

- 一次性网络命名空间中，旧规则在三种源端口复用情形下都复现了 `EPERM`，新规则全部正常；各 UID 的常规行为、OFF 清理、核心停止时的快速失败均不变。
- 便携包 `test_portable.py` 和 `netns-check.py` 通过。`netns-check.py` 新增了复用测试，用旧控制器运行会失败。
- 线上按 `harden-access.py` 不停服更新，两核心 PID 不变。`verify.py` 与 `verify-access.py` 均通过，后者新增了两个方向的源端口复用测试，并核对 owner 的 DNS 条目位于 zone `20261`。备份与日志：`/var/backups/xq-tun-access-yo80rf39/`。

换表瞬间正在进行的 xuqian DNS 查询可能丢失一次，由解析器重试，不影响其他用户。xuqian 的其他连接仍记录在默认 zone 并带 OWNER 标记，但不做地址改写；本功能的规则都先按 socket UID 判断，该标记不改变其他用户连接的走向。

## 连通性检查

```bash
ping -c 3 192.168.5.34
curl --disable --proxy '' --noproxy '*' -4 -I --max-time 15 https://www.baidu.com
xq_proxystatus
```

局域网 ping 可以验证本地 ICMP 连通性；公网 `ping baidu.com` 被当前 TUN 配置明确拒绝，不能用它判断 HTTPS 是否可用。sing-box 的 ICMP reject 默认会生成 Host Unreachable，见[对应版本文档](https://github.com/SagerNet/sing-box/blob/v1.14.4/docs/configuration/route/rule_action.md#reject)。

已实测局域网 ping、TCP 代理端口、局域网 DNS 和公网 HTTPS。IPv6/其他私网/多播范围已完成规则语法与范围检查，未宣称每个网段都有可达设备。详细结果见[断网诊断与后续修复](../../2026-11-14-用户代理断网诊断.md)。

## 不停服检查与异常行为

新版验收器默认只检查已开启的代理，不停止核心、不切换 ON/OFF、不改防火墙。日常检查可运行：

```bash
sudo /usr/bin/python3 -I /usr/local/lib/xq-user-proxy/verify.py \
  --baseline /var/backups/xq-tun-access-mkcrhtaq/current-baseline-derived.json
```

基线最初是用户级安装前的宿主快照 `/var/backups/xq-user-proxy-live-20261113-KzVGamSt/host-before.json`。2026-11-14 Docker 移除了两个网桥及相关规则，按它运行会报 `-4route, -6route, nftables` 差异（与代理无关），因此改用删除 16791 前的宿主快照去掉本功能自有资源后的派生基线。若其他管理员或 Docker 之后再改动网络，差异需要另行核对，不应直接归因于代理。

只有显式增加 `--exercise-switches` 才进入会中断 xuqian 公网请求的维护演练，本轮没有执行。安装器只用于安装或更新，不能用作日常状态查询；它会明确启用代理，再运行默认在线验收。

按用户要求，没有定时回滚，也不在异常时自动 OFF 或恢复公网直连。核心异常时保留 guard/黑洞路由，使用 `xq_proxyon` 恢复核心，或由用户明确执行 `xq_proxyoff` 恢复原网络。
