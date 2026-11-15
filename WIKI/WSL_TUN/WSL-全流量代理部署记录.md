# WSL 全流量代理部署记录

初次部署日期：2026-11-13（America/Los_Angeles）。2026-11-14 20:01 已部署本地 DNS 接管修复，并完成隔离测试及宿主 DNS、HTTPS、重复开关、核心停止和 resolver 重建模拟验收，最终保持 **ON**。实际新建 WSL 会话和完整发行版重启尚未执行；下文明确区分已验证项目与该限制。本页记录已经安装、启用并完成验收的版本；早先的[方案页](WSL-全流量代理方案.md)只代表部署前讨论。

另一台全新 WSL 请执行 [从零复现指南](../WSL_TUN/WSL-从零复现指南.md)，安装文件见 [WSL_TUN/scripts/xq-proxy](../WSL_TUN/scripts/xq-proxy/README.md)。本页的 IP、UID、PID、备份名和 ON/OFF 是原机器在不同测试时点的记录，不是新机器的固定配置或实时状态。

## 当前效果

公网连接路径为：WSL 程序 → `xq-tun` → Windows Karing 全代理端口 `4066` → Karing 所选节点。

- `xq_proxyon` 接管当前 WSL 网络命名空间中的普通程序、其他终端和后台程序的公网连接，不再仅设置当前 shell 的代理变量。
- IPv4 TCP/UDP 经 TUN 转发；应用的 IPv4 TCP/UDP DNS 查询由本地 sing-box DNS 入口接收，再通过 Karing 上游进行 DoH 查询。
- 本次实现明确阻断不支持的 IPv6，不回落到物理接口直连。
- 独立 nftables 规则在代理核心停止后仍阻止公网直连；代理恢复后重新附加路由，DNS 入口随核心恢复。
- `xq_proxyoff` 先拒绝新的 DNS 查询并停止新建 DNS 改写，再停止隧道、清理本功能的 DNS 连接映射并恢复路由，最后移除本功能的防直连规则，恢复原 WSL DNS 路径。
- **每次 Ubuntu/WSL 完整启动默认 OFF**，同一个运行环境中新开终端不会改变开关；需要代理时执行 `xq_proxyon`。之后只通过用户手动执行 `xq_proxyon/off` 切换，没有定时检查或自动重试机制。OFF 恢复普通网络，不经过 TUN。初次部署时的开机恢复 ON 设计已经停用。
- 2026-11-14 修复验收结束时保持 **ON**，普通 `chris` 用户访问 GitHub、Google 均返回 HTTP 200；当前实时状态请运行 `xq_proxystatus`。

这套控制不改变 Windows 的代理开关，不从 WSL 执行 Windows 程序，也不覆盖管理员主动修改网络规则的行为。其他独立网络命名空间或独立 WSL 发行版不能仅凭本页假定已被接管。

## 使用方法

在已有终端先加载更新后的函数：

```bash
source ~/.bashrc
```

日常命令：

```bash
xq_proxyon
xq_proxystatus
```

明确需要恢复原网络时：

```bash
xq_proxyoff
```

开关需要 Linux `sudo` 权限；没有把密码写入配置或脚本。开关现在固定使用 Karing 全代理端口 `4066`，不再接受旧版 `xq_proxyon 端口` 参数。

`.bashrc` 现在加载 `~/.config/xq/proxy.bash`。新函数会清理旧的大小写 HTTP/HTTPS/ALL_PROXY 和 NO_PROXY 环境变量，以免把应用层代理再套进 TUN。

已经运行的程序不会被改写环境。如果它们仍保留旧的 `16791` 代理地址，需要在清除旧变量后的终端重新启动；只修改另一个终端的变量不能更新既有程序。

## 安装内容

| 项目 | 配套内容 |
| --- | --- |
| 代理核心 | 官方 sing-box `1.14.4` |
| 防火墙与连接跟踪工具 | nftables；2026-11-14 已安装 conntrack 及其库依赖 |
| 专用账号 | 非登录用户 `xq-proxy`，本机 UID `999` |
| 控制器 | `/usr/local/sbin/xq-proxyctl`，由 root 安装管理 |
| 核心配置 | `/etc/xq-proxy/sing-box.json` |
| 核心服务 | `xq-proxy.service` |
| 启动复位服务 | `xq-proxy-boot.service`，已启用；每次启动执行一次 `boot-off`，恢复 OFF |
| 持久状态 | `/var/lib/xq-proxy/` |
| ON 标记 | `/var/lib/xq-proxy/enabled` |
| 当前启动周期标记 | `/run/xq-proxy-enabled` |
| 用户入口 | `~/.config/xq/proxy.bash` |

官方发行资产下载后验证的 SHA256：

```text
4e9b8809aed0e3ac78ad14fa3a0af533402425d736f0cc9dc75b1c03d381b614
```

该校验值对应本次下载的发行资产，不能作为其他版本或架构文件的校验值。

本功能使用自己的 systemd 服务。**不要另外启动发行包自带的 `sing-box.service`**，以免同时运行第二套核心。

## 路由、DNS 与防直连规则

| 参数 | 本次值 |
| --- | --- |
| TUN 名称 | `xq-tun` |
| TUN 地址 | `172.30.255.1/30` |
| TUN 内地址 / 旧版 TUN DNS | `172.30.255.2`；不再写入 resolver，只作 TUN 内地址和旧版残留的识别标记 |
| 本地 DNS 入口 | `127.0.0.1:1053`，TCP/UDP，仅本地监听 |
| DNS conntrack zone / 标记位 | `20262` / `0x02000000` |
| TUN MTU | `1280` |
| 路由表 | `20260` |
| 策略规则优先级 | `18400`、`18401`、`18402` |
| nftables 自有表 | `inet xq_proxy` |
| SOCKS5 上游 | 启动时探测的 Windows 网关，端口 `4066` |

控制器手动管理策略路由，sing-box 的 `auto_route` 关闭，以便由同一个控制器完整恢复自己的规则。返回 TUN 的流量和专用代理用户使用主路由表，其他流量进入表 `20260`；IPv6 对应路由明确设为不可达。

ON 时，自有 nftables OUTPUT NAT 规则将应用的 IPv4 TCP/UDP 端口 53 查询转交本地 `127.0.0.1:1053`，由 sing-box 的 DNS 入口处理；TUN 内端口 53 接管也保留，处理仍进入 TUN 的 DNS（例如转发流量）。DoH 使用 `1.1.1.1:443`、TLS 名称 `cloudflare-dns.com`，显式通过 Karing SOCKS5 出站，无需系统 DNS 做启动解析。DNS 改写仅匹配连接原方向，回复不会再次改写，并经反向 NAT 还原为原 DNS 服务器地址；专用核心 UID 不参与应用 DNS 改写。ON 时应用的 IPv4 DNS 都由这条 DoH 回答，只存在于 Windows hosts 文件或内网 DNS 的名称不能解析，旧版同样如此。

修复版保留 WSL 自动生成 DNS 和 `/etc/resolv.conf` → `/mnt/wsl/resolv.conf` 的原始链接（本机为 `nameserver 10.255.255.254`），正常 ON/OFF 都不改写该文件。只有 resolver 仍是旧版残留（带本工具管理标记或 `nameserver 172.30.255.2`）时，ON 才恢复一次已校验的原 resolver，OFF 也只在这种情况下恢复；之后不再随 ON 或核心重启写入 TUN DNS。新 WSL 会话即使重建链接，查询也会在网络层被接管；OFF 后继续使用原有 Windows DNS tunneling。首次 ON 仍保存原 resolver 作为恢复基线；ON 时默认 resolver 至少要有一个 IPv4 DNS，只有 IPv6 DNS 的 resolver 不受支持。

DNS 映射使用专用 conntrack zone 和标记，避免复用 UDP 源端口时继承其他身份或上一次 ON 的映射。OFF 精确删除本功能的 DNS 映射；仅删除 NAT 规则不足以清除已有映射。不清空全机 conntrack。因此 ON 和 OFF 都依赖 `/usr/sbin/conntrack`：缺少时 ON 在改动网络前拒绝启用，需要清理 DNS 映射的 OFF 也在改动前报错。ON 前还会拒绝这些冲突：其他 nft 表使用 conntrack mark/zone、zone `20262` 已被占用或含非本功能标记的连接、端口 `1053` 被本功能核心以外的进程占用。

独立防直连规则只放行必要路径：loopback、IPv4 TUN、专用核心用户到准确 Karing 网关的 TCP4066 和动态 SOCKS UDP 中继。未被接管的非 TUN DNS53 仍在 loopback 放行之前被拒绝；本功能已识别的 DNS 回复单独处理，以兼容客户端源端口为 53 的情况。没有对所有旧 `established` 连接无条件放行，也没有给专用代理用户任意公网直连权限。forward 链同样受限制。

## 故障与重启行为

- 核心失败时，独立 guard 保留，普通程序不能自动回落到物理接口直连；被接管的 DNS 查询直接失败，不会改用 WSL 原 DNS。
- 核心重启后，`ExecStartPost` 重新附加策略路由，并等待本地 DNS 入口 TCP/UDP 1053 就绪（约 3 秒内），不再改写 resolver；入口未就绪时这次启动失败，guard 保留。该操作没有与主控制锁形成互锁。
- 已经是 ON 时再次执行 ON，先核对 conntrack 与 DNS 资源，再重新装回 guard；配置相同且完整时保持同一核心进程；核心配置或二进制变化、端点变化或规则不完整时重启核心恢复。从旧控制器升级后的第一次 ON 因尚无运行版本记录，也会重启一次核心。
- OFF 先拒绝新的 DNS 查询、停止新增 DNS 映射并保留 guard，在停止核心前删除 ON 标记，再停止核心、精确清理本功能 DNS 映射、恢复自有路由与必要的旧版 resolver 残留，最后移除 guard。OFF 中途失败时，`xq_proxystatus` 显示 `OFF，但存在残留配置`，排除原因后再次执行 `xq_proxyoff` 会继续清理。
- OFF 在改动网络前仍会核实原 resolver 恢复基线；基线无效时只接受经过检查的 WSL 原始 `/mnt/wsl/resolv.conf`，两者都无法核实则报错并保留保护规则。
- ON 标记写在磁盘上，用于保存当前状态和恢复信息，不表示下次开机自动 ON。启动复位服务在相关用户会话之前无条件执行一次 `boot-off`，清除旧 ON 标记，清理可能残留的本功能 DNS 映射、路由和 guard，恢复普通网络；此动作不会等待 Karing 上游可用。若上次在 ON 状态下终止发行版，`boot-off` 同样需要 conntrack。本页归档的 unit 已与现场该行为一致。
- 同一个 WSL 运行环境中关闭窗口再新开终端，不一定是完整重启，因此不会自动重置已经手动开启的代理。
- `xq-proxy.service` 本身仍未单独设置开机启动；没有 health service、health timer 或 5 秒重试。
- 状态输出区分配置完整性与有时间限制的默认 DNS 探测。核心运行不等于 DNS 或上游正常；resolver 是 WSL 链接也不再单独构成异常。
- 端口 `1053` 的占用者只在 ON 时核对；核心停止或重启的间隙，同机其他程序若监听 `127.0.0.1:1053`，就会收到被接管的应用 DNS。单用户 WSL 风险较低，但不要让其他程序使用该端口。
- 2026-11-13 只通过实际启动复位单元验证了旧控制器的 `boot-off` 动作，以及新终端不改变 ON/OFF；2026-11-14 修复后也未新建 WSL 会话或重启发行版。**现行控制器尚未做完整 WSL 重启验收**，启动默认 OFF 的说明来自现场 unit 和控制器，不把单元测试写成已完成重启实测。

## 2026-11-14 故障与修复验收

19:27:48 用户执行 OFF，19:27:52 再执行 ON，核心正常停止并启动。19:33:41，resolver 又成为 WSL 默认链接，DNS 地址为 `10.255.255.254`。该地址命中 local 路由表、走 `lo`，因此原 guard 在 DNS 进入 TUN 前拒绝请求。

19:45–19:49 宿主对照确认：默认 DNS 的 GitHub、Google 查询被拒绝，curl 返回 `Could not resolve host`；显式 TUN DNS 查询正常，使用解析结果访问两个网站均 HTTP 200，Karing SOCKS 对照也均 HTTP 200。核心保持运行、自动重启次数为 0。因此本次复现的直接故障点是系统 DNS 路径。此前 Karing 上游连接超时属于另一条日志线索，不能与这次 DNS 阻断混为一谈。

20:01 部署后的验收结果：

| 测试 | 当前记录 |
| --- | --- |
| 临时网络命名空间：WSL DNS、loopback stub、普通 DNS 的 TCP/UDP 接管 | 通过 |
| DNS 源端口复用、身份切换、客户端源端口 53、同 UDP socket ON/OFF | 通过，包含核心 UID 的防直连限制 |
| 宿主默认 DNS | 真实 `chris` 用户经 `10.255.255.254` 发起 UDP、TCP 查询均成功 |
| 宿主 GitHub/Google HTTPS | 真实 `chris` 用户普通 curl，禁用应用代理变量，两者均 HTTP 200 |
| 重复 ON | 核心 PID `9824` 不变 |
| 模拟 WSL resolver 重建 | 在 Linux 中替换为相同 WSL 符号链接后，默认 UDP/TCP DNS 和两个网站继续成功，核心 PID 不变 |
| 核心停止时保持防直连，恢复后 DNS 可用 | stop 核心后访问 `https://1.1.1.1` 失败，guard 仍在；执行 ON 后默认 DNS 成功 |
| OFF 恢复原网络 | 默认 Windows DNS 查询成功，自有 nft 表消失；隔离测试验证 DNS 映射清理与同 socket 复用 |
| OFF 后再次 ON | 默认 UDP/TCP DNS、GitHub/Google HTTPS 再次通过，最终状态 ON |
| 无关配置 | 无关 nft 表、策略规则及 `/etc/wsl.conf` 前后不变 |
| 实际新建 WSL 会话、完整 WSL 重启 | 未执行；resolver 替换模拟不能等同这两项验收 |

证据目录：`/home/chris/tun-diagnostics/2026-11-14/`，宿主部署与验收原始输出为 `deployment.txt`。本次备份：`/var/backups/xq-wsl-dns-20261114-195618/`。

修复后，仓库控制器与 `/usr/local/sbin/xq-proxyctl` 的 SHA256 一致：

```text
6bf4c30a0fd4e5bb42d519aa7ddf586a09ebd1fe2ed65eec55d8b6a136880708
```

上面的 PID 和校验值用于本次验收追溯，不是其他机器必须使用的固定值。

## 2026-11-13 历史验收

下表记录初次部署时的旧实现，验收结束保持 ON；其中“ON 改写 resolver、OFF 恢复链接”已经由 2026-11-14 修复替代。当时原 `/etc/resolv.conf` 是指向 `/mnt/wsl/resolv.conf` 的符号链接，ON 只替换发行版自己的链接入口，不写穿共享目标。

| 测试 | 结果 |
| --- | --- |
| 离线网络命名空间中的 nft 拒绝规则 | 通过 |
| 去掉所有应用层代理变量，并使用 curl 的 `--proxy '' --noproxy '*'` | 在 TUN 和 guard 已启用的条件下，出口仍为 `179.255.139.228`，识别为 US |
| DNS UDP 查询 | 已被接管并通过代理 DoH 查询成功 |
| 普通 UDP STUN | 转发成功 |
| 停止核心，再强制绑定物理接口访问 HTTPS | guard 仍在，curl 失败，退出码 7；随后恢复核心并重新附加路由 |
| OFF 恢复原状态 | 在额外保护规则下测试，原 resolv.conf 符号链接恢复，自有策略规则移除；之后恢复 ON |
| 重复 ON | 核心 PID 不变 |
| 普通 `chris` 用户交互 Bash | 正确加载开关，公网 IP 查询成功 |

这些历史测试没有发出不受保护的公网直连请求，也没有调用 Windows 程序。忽略应用代理变量的测试是在网络层接管和直连阻断均生效后执行的，不属于关闭保护后的直连对照。

### 改为完整启动默认 OFF

初次部署时，启动服务会在开机时恢复已保存的 ON。用户随后确认：Ubuntu/WSL 完整启动默认 OFF，同一环境中新开终端不改变既有开关，不需要 5 秒重试或自动恢复 ON。启动服务因此改为一次性执行 `boot-off`，没有安装健康定时器。变更前备份为 `/var/backups/xq-proxy-before-default-off-b7ics53n`，过程见[操作记录](2026-11-13-操作记录.md)第 14 节。

| 测试 | 结果 |
| --- | --- |
| 完整启动所用的 `boot-off` 动作 | 已验证 ON 标记清除、核心停止、原 DNS 链接及路由恢复 |
| 新终端保持既有状态 | 分别在 OFF 和 ON 下验证，新终端均不触发开关 |

这两项是在额外防直连规则保护下实际启动复位单元完成的，没有执行完整 WSL 重启。

### 实际 OFF 联网检查

用户反馈新终端 DNS 失败时，日志显示仍是部署前已启动的同一次 WSL 运行，且 TUN 仍处于此前保留的 ON。随后实际执行 OFF，确认 `ip.sb`、`baidu.com` DNS 正常，`http://ip.sb`、`https://www.baidu.com`、`https://icanhazip.com` 返回 HTTP 200，直连出口 `223.73.5.58`；TUN 设备消失，自有策略路由清除。那次处理后保持 OFF；后续用户又手动开启并完成了 [ON 审查](../WSL_TUN/2026-11-13-ON状态复查.md)。以上为用户要求的普通 OFF 联网验收，不是绕过 ON 保护的测试。

### 状态检查与 DNS 恢复改进

> 2026-11-14 更新：本节是旧控制器的改进记录。现行控制器不再把 resolver 改为 TUN DNS，WSL 重建 resolver 也不再报告为异常；下列恢复校验仍保留，用于迁移旧版 resolver 残留和 OFF 前核实恢复基线。

用户授权后已部署下列改进：

- ON 不会把带有本工具管理标记或 `nameserver 172.30.255.2` 的 resolver 保存成原始 DNS。
- 遇到自有残留时优先使用有效旧备份；否则只检查 WSL 原始 `/mnt/wsl/resolv.conf`，不自行猜测公共 DNS。
- OFF 在 ON 标记和主 guard 均丢失时，仍会识别并清理自有 TUN DNS。
- OFF 找不到安全恢复来源时，会在停止工作中的核心或移除保护前报错。
- 普通文件恢复字节及权限，相对链接保留原始链接文本；自引用、循环、失效链接以及指向 TUN DNS 的恢复来源会被拒绝。
- 已正常 OFF 后用户自行修改的普通 DNS 不会被重复 OFF 覆盖。

本次安装前真实状态检查发现：TUN 和 guard 仍在，但 resolver 已变回 WSL 原 DNS。新命令报告了 `ON，但配置异常` 和具体 DNS 问题。手动重新应用 ON 后恢复。此改进会诊断外部覆盖，不阻止外部组件再次修改 resolver，也没有增加自动重试机制。

验证结果：29 项离线回归测试通过；受保护的实际测试确认错误 DNS 和缺失规则返回异常、损坏的 DNS 备份可安全恢复、无标记/guard 的 DNS 残留可由 OFF 清理、再次 ON 不会误保存残留 DNS。验收结束保持 ON，HTTPS 出口 `179.255.139.228`，地区 US。

控制器更新前备份：`/var/backups/xq-proxy-before-dns-reliability-muj3aj8z`。

## 只读检查与恢复命令

`xq_proxystatus`（即 `sudo /usr/local/sbin/xq-proxyctl status`）区分“开关选择了 ON”与“配置完整”。ON 时检查核心、防直连与 DNS 接管规则（与安装时的摘要比对）、TUN 接口、策略规则中的接口/UID/路由表、IPv4 默认路由、IPv6 阻断路由、默认 resolver（至少一个 IPv4 DNS，且不是旧版 TUN resolver）、本地 DNS 入口 TCP/UDP 1053、conntrack、核心配置及运行中的配置/二进制版本、恢复备份和当前网关。配置完整时，再向默认 resolver 的 IPv4 DNS 发出一次总时限 4 秒的 UDP 查询（`example.com` A 记录）；该查询同样被接管，经代理 DoH 返回。发现配置异常或探测失败都返回退出码 1，正常返回 0。它不自动修改配置，也没有定时运行。

ON 且正常时的关键输出如下，默认 DNS 地址随机器而定：

```text
代理状态：已开启（WSL 全流量）
防直连：已开启
DNS 接管：应用 IPv4 TCP/UDP 53 → 127.0.0.1:1053 → 代理 DoH；WSL 继续管理 resolver
配置检查：DNS 入口、接管规则、路由和运行版本正常
默认 DNS 连通性：成功（默认 DNS 10.255.255.254，example.com A）
```

`DNS 接管：` 一行是固定说明，是否生效以配置检查和默认 DNS 探测为准。配置异常时逐行显示 `检查异常：…`，并显示 `默认 DNS 连通性：未探测（先修复配置异常）`。配置完整但探测失败时，第一行仍为已开启，随后显示 `配置完整，但默认 DNS 探测失败；请检查上游和服务日志。` 并返回 1，`xq_proxyon` 因此不显示公网出口 IP。OFF 时不显示 DNS 行，也不探测。

日常查看状态：

```bash
sudo /usr/local/sbin/xq-proxyctl status
systemctl status xq-proxy.service --no-pager
systemctl is-enabled xq-proxy-boot.service
ip -4 rule show
ip -6 rule show
ip -4 route show table 20260
ip -6 route show table 20260
cat /etc/resolv.conf
ss -H -l -n -t -u sport = :1053
sudo nft list table inet xq_proxy
sudo conntrack -L -f ipv4 --zone 20262
```

ON 时 `/etc/resolv.conf` 仍是 WSL 自己的 resolver（本机为 `nameserver 10.255.255.254`），不是 `172.30.255.2`；`ss` 应显示 `127.0.0.1:1053` 的 TCP LISTEN 和 UDP UNCONN；nft 表含 `dns_zone_output`、`dns_nat_output`、`output`、`forward` 四条链；conntrack 列出的 DNS 连接带 `zone=20262`，标记含 `0x02000000` 位（通常显示为 `mark=33554432`）。OFF 后 nft 表不存在，1053 没有监听，zone `20262` 中没有本功能的 DNS 连接。

核心未工作时先看日志：

```bash
journalctl -u xq-proxy.service -n 80 --no-pager
journalctl -u xq-proxy-boot.service -n 80 --no-pager
journalctl -t xq-proxyctl -n 80 --no-pager
```

`xq-proxyctl` 标签记录控制器启停结果、默认 DNS 探测失败和控制器异常；核心的连接错误仍查看 `xq-proxy.service`。日志不可读时使用 `sudo journalctl`。

需要用户明确恢复普通网络时，直接运行以下根控制命令；即使 shell 函数未加载也可使用：

```bash
sudo /usr/local/sbin/xq-proxyctl off
```

不要通过清空全机 nft 规则、清空全机 conntrack 或直接删除所有策略路由恢复网络。控制器只管理自己的表、规则、DNS 映射和备份。

## 备份与迁移

本机各阶段备份：

```text
/var/backups/xq-proxy-before-deploy-yrrosx1p
/home/chris/.bashrc.before-tun-v_jgsv2s.bak
/var/backups/xq-proxy-before-default-off-b7ics53n
/var/backups/xq-proxy-before-dns-reliability-muj3aj8z
/var/backups/xq-wsl-dns-20261114-195618/
```

前两项是初次部署前的系统与 `.bashrc` 备份；后三项依次是改为启动默认 OFF、状态检查与 DNS 恢复改进、2026-11-14 DNS 接管修复之前的备份。

可复现文件以 [WSL_TUN/scripts/xq-proxy](../WSL_TUN/scripts/xq-proxy/README.md) 为准，其中首次安装器 `install.py` 按 [从零复现指南](../WSL_TUN/WSL-从零复现指南.md) 使用；[VPS_TUN/scripts/xq-proxy](../VPS_TUN/scripts/xq-proxy/README.md) 保留同一版本控制器、DNS 修复说明和隔离测试。2026-11-14 修订以现场较新的控制器为基线，同步 DNS 恢复校验、状态检查和 boot-off 策略，再增加本地 DNS 接管；归档控制器应与上文 SHA256 一致。此前两处归档的旧控制器都落后于现场，不能将旧版本覆盖回去。迁移前需安装 conntrack，并核对当前网关、专用 UID、Karing 端口、本地 DNS 端口及保留路由/conntrack 资源，不能直接复制本机动态状态。

修改或迁移控制器前，可先运行离线回归测试；它只使用临时文件和模拟命令层，不需要 root 或联网（路径与[从零复现指南](../WSL_TUN/WSL-从零复现指南.md)一致，仓库不在 `~/vpsinit` 时按实际位置调整）：

```bash
python3 -I "$HOME/vpsinit/WIKI/WSL_TUN/scripts/xq-proxy/test_dns_reliability.py"
```

普通 VPS 通常没有 Windows 宿主机网关。它需要显式配置真实 SOCKS5 上游；不要把本机的默认网关探测逻辑照搬为 VPS 的代理地址。

本页没有记录密码、API Key、订阅内容或账号令牌。`WSL_TUN` 与 `VPS_TUN` 目录中的本页副本内容相同，修改时两处同步。
