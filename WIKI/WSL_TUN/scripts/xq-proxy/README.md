# WSL 全流量代理脚本说明

本目录是 [WSL 从零复现指南](../../WSL-从零复现指南.md) 使用的全部程序副本，对应 WSL 中的 `xq-proxy.service`，作用于当前 WSL 网络命名空间中的全部普通程序。它与 VPS 方案中的用户级 `xq-user-proxy`、独立命名空间 `xq-tun` 不同，不能混用服务或控制器。

本目录的控制器是 2026-11-15 修订版，**尚未部署**；原机器 `/usr/local/sbin/xq-proxyctl` 仍是 2026-11-14 20:01 部署的本地 DNS 接管版本：

| 版本 | SHA256 | 状态 |
| --- | --- | --- |
| 本目录 `xq-proxyctl`（2026-11-15 修订） | `73c988924fb669fa28512e2b0153d7e996c5a3708105dbc4311ae8ace282e1f3` | 待部署 |
| 原机器 `/usr/local/sbin/xq-proxyctl`（2026-11-14） | `6bf4c30a0fd4e5bb42d519aa7ddf586a09ebd1fe2ed65eec55d8b6a136880708` | 已部署 |

2026-11-15 修订在 2026-11-14 版本上改了两处行为，防直连与 DNS 接管规则、两个 unit、`proxy.bash` 和状态文件格式都没有变：

- 从干净的 OFF 开启时，先完成只读检查、resolver 预检、Karing 握手和核心配置校验，全部通过后才改动网络；任一步失败都保持原样。已是 ON 或有残留时仍然先装防直连规则。见“ON 与 OFF 的顺序”。
- 只有迁移旧版 TUN resolver 时才依赖原 DNS 备份；resolver 不是旧版残留时，失效的旧备份不再阻塞 ON、重复 ON、OFF 和 `boot-off`。见“DNS 接管”。

原机器对 2026-11-14 版本完成了隔离测试，以及宿主 DNS、HTTPS、重复开关、核心停止和 resolver 重建模拟验收，详见 [部署记录](../../WSL-全流量代理部署记录.md)；实际新建 WSL 会话和完整发行版重启尚未执行，新机器须按指南第 9 节补做。2026-11-15 修订只通过了离线回归测试，以及在无特权的一次性网络命名空间中对真实内核的演练（范围见“测试”），没有在任何宿主上执行过 ON/OFF。旧版控制器在 ON 时改写 `/etc/resolv.conf`，已被替换；不要用旧归档或 2026-11-13 的迁移包覆盖本目录。

## 文件

| 文件 | 作用 | 安装位置 |
| --- | --- | --- |
| [install.py](install.py) | 首次安装器；`--check` 为只读前置检查，检查和安装都需 `sudo`；安装后保持 OFF，拒绝覆盖已有部署 | 不安装，在本目录原地运行 |
| [download-core.py](download-core.py) | 通过指定 Karing 代理下载 sing-box `1.14.4` amd64 包，校验 SHA256 与包信息；不安装 | 下载到 `~/.cache/xq-proxy-deploy/` |
| [xq-proxyctl](xq-proxyctl) | root 控制器：`on`、`off`、`status`，以及只供 systemd 调用的 `attach`、`boot-off` | `/usr/local/sbin/xq-proxyctl` |
| [xq-proxy.service](xq-proxy.service) | 以 `xq-proxy` 用户运行 sing-box；启动后由 `attach` 附加路由并等待本地 DNS 入口 | `/etc/systemd/system/`，不单独开机启动 |
| [xq-proxy-boot.service](xq-proxy-boot.service) | 每次发行版启动执行一次 `boot-off`，默认恢复 OFF | `/etc/systemd/system/`，安装器只启用这一项 |
| [proxy.bash](proxy.bash) | `xq_proxyon`、`xq_proxyoff`、`xq_proxystatus` | `~/.config/xq/proxy.bash`，由 `.bashrc` 加载 |
| [check-udp.py](check-udp.py) | 普通 UDP 的 STUN 出口诊断；不修改网络 | 不安装 |
| [test_dns_reliability.py](test_dns_reliability.py) | 离线回归测试：临时文件和模拟命令层，无需 root、不联网 | 不安装 |
| [tests/netns-check.py](tests/netns-check.py) | 数据包级规则测试：需要 root，只在新建的临时网络命名空间中运行 | 不安装 |

首次安装器从本目录读取控制器、两个单元和 `proxy.bash`，并把它们的 SHA256 写入安装清单。已经安装本方案的机器不要再次运行首次安装器。

## 使用

```bash
xq_proxyon
xq_proxystatus
xq_proxyoff
```

明确的控制器入口为：

```bash
sudo /usr/local/sbin/xq-proxyctl on
sudo /usr/local/sbin/xq-proxyctl status
sudo /usr/local/sbin/xq-proxyctl off
```

完整关闭必须使用 `off`。单独停止核心会留下防直连规则，普通程序不会自动恢复公网直连。`xq-proxy-boot.service` 使用 `boot-off`，每次发行版启动都先恢复 OFF；它不会自动开启上次的 ON 状态。

三个命令最后都输出状态。`xq_proxyon` 只有在控制器报告配置完整且默认 DNS 探测成功时，才清理旧代理变量并查询公网出口；否则返回 1。

## DNS 接管

旧实现开启代理时把 `/etc/resolv.conf` 写成 TUN DNS `172.30.255.2`，但 WSL 新建会话可能将其重新链接到 WSL DNS（如 `10.255.255.254`）。后者走 loopback，命中防直连规则中“非 TUN DNS 拒绝”一条，于是核心仍运行、网站却无法解析。这就是原机器 2026-11-14 的断网原因。

当前版本保留 WSL 自动 DNS 和原 resolver 链接：attach 和核心重启不再写该文件，正常 ON/OFF 也不改动它，ON 前后它保持 WSL 原样。ON 时：

1. `inet xq_proxy` 表的 `dns_zone_output` 链（`raw` 优先级，早于连接跟踪）把非核心用户的 IPv4 TCP/UDP 53 查询放入专用 conntrack zone `20262`。
2. `dns_nat_output` 链只处理连接原方向：为这些连接设置标记位 `0x02000000`，并 DNAT 到本地 `127.0.0.1:1053`。
3. sing-box 的 `dns-in` 入站（TCP/UDP，仅监听 `127.0.0.1`）把查询交给 DNS 模块，经 Karing SOCKS5 向 `1.1.1.1:443`（TLS 名称 `cloudflare-dns.com`）发起 DoH，策略为 `ipv4_only`。
4. 回复经反向 NAT 还原为原 DNS 服务器地址，应用看到的仍是 resolver 中那个服务器的回答。本功能识别的 DNS 回复单独放行，兼容客户端源端口为 53 的情况。
5. 仍进入 TUN 的端口 53 查询（例如转发流量）由 TUN 入站继续接管；`172.30.255.2` 只作为 TUN 内地址和旧版残留的识别标记。

专用核心 UID 不参与应用 DNS 改写，也没有任意公网直连权限。IPv6 DNS 不接管、直接拒绝，IPv6 路由保持不可达。本地入口或核心停止时，应用 DNS 失败关闭，不会回落到 WSL 原 DNS；只存在于 Windows hosts 文件或内网 DNS 的名称在 ON 时不能解析。

只有迁移旧版残留时才写 resolver：若 `/etc/resolv.conf` 仍带旧版管理标记或 `nameserver 172.30.255.2`，ON 恢复一次已校验的原 resolver，OFF 也只在这种情况下恢复。首次 ON 仍会保存原 resolver 作为恢复基线，并拒绝把本功能自己的 DNS 当作原 DNS。

这份基线只用于上述迁移：

- resolver 不是旧版残留时，控制器不会改写它，基线是否可用也就不影响 ON、重复 ON、OFF 和 `boot-off`，状态检查不把失效的基线报告为异常。重复 ON 遇到失效的基线时，按“WSL 原始 `/mnt/wsl/resolv.conf`（经校验）→ 当前正在使用的 resolver”的顺序换成能核实的一份；都不可用就保持不动。
- resolver 仍是旧版残留时照旧从严：已保存的基线和 WSL 原始文件都无法核实，就报 `原 DNS 备份无效，且无法核实 WSL 原 DNS；保留保护规则，拒绝误恢复 TUN DNS`，不恢复错误的 DNS，防直连规则保留；ON 时的状态检查会同时报告 `仍残留旧版 TUN resolver` 和 `原 DNS 恢复备份不可用`。

## ON 与 OFF 的顺序

ON 先判断起点。没有 ON 标记，并且没有任何残留——核心未运行、没有 `inet xq_proxy` 表、resolver 不是旧版 TUN resolver、策略优先级 `18400`–`18402` 上没有规则——才算干净的 OFF；这与 OFF 状态下 `status` 报告残留用的是同一个判定。其余情况（已是 ON，或 OFF 但有残留）都按“先保护”的顺序处理。

从干净的 OFF 开启（先证明，后改动）：

1. 只读检查依赖和 DNS 接管资源：`/usr/sbin/conntrack` 可执行；其他 nft 表没有使用 conntrack mark/zone；zone `20262` 中没有不属于本功能的连接；端口 `1053` 没有被占用。
2. resolver 预检：`/etc/resolv.conf` 可读，且至少有一个 IPv4 nameserver。
3. 只读检查路由资源和账号：有物理默认网关；路由表 `20260` 和 TUN 子网 `172.30.255.0/30` 未被占用；专用账号 `xq-proxy` 存在。
4. 以 `xq-proxy` 用户对 Windows 网关 `4066` 做 SOCKS5 握手。此时还没有防直连规则，这次连接只到 Windows 网关。
5. 生成核心配置，写成 `/etc/xq-proxy/` 中的临时候选文件（该目录不存在时用系统临时目录）交给 `sing-box check`，随后删除候选文件；已安装的 `sing-box.json` 此时不动。
6. 以上全部通过，才保存原 resolver 基线和状态、写入 ON 标记、安装防直连和 DNS 接管规则、写入刚通过校验的配置，并启动 `xq-proxy.service`。核心启动后，`attach` 附加策略路由，等待 `127.0.0.1:1053` 的 TCP 和 UDP 监听（约 3 秒内），并记录运行中的配置与核心二进制摘要。
7. 输出状态并探测默认 DNS；配置不完整或探测失败时返回 1，防直连规则保留。

第 1–5 步任何一步失败，系统与执行前完全相同：没有 ON 标记和 `/run` 标记，没有防直连表，状态文件、路由、核心和已安装的配置都未改动。报错以 `；未改变网络` 结尾并写明原因，不提示执行 OFF，退出码为 1。例如 Windows 网关的 4066 端口拒绝连接时（原因部分随情况而变，连接超时则是 `TimeoutError: timed out`）：

```text
xq-proxy: Karing 172.21.32.1:4066 SOCKS5 握手失败：ConnectionRefusedError: [Errno 111] Connection refused；未改变网络
```

握手之后 Karing 才不可用的情况不在这一保证之内：核心照常启动，由第 7 步的默认 DNS 探测报告失败，防直连规则保留。

已是 ON，或 OFF 但有残留（先保护，后检查；与 2026-11-14 版本的顺序相同）：

1. 改动前检查：conntrack、其他 nft 表的 conntrack mark/zone、zone `20262`、端口 `1053`（只允许本功能核心占用）。任一不满足即拒绝，这次执行不改动任何东西，已有的防直连规则原样保留。
2. 已是 ON 时先重新装回已保存的防直连规则。没有 ON 标记但有残留时，检查策略优先级 `18400`–`18402`、路由表 `20260` 和 TUN 子网未被占用，并保存原 resolver；保留优先级上还有规则时在这里以 `Reserved policy routing priority is already in use` 拒绝，不改动任何东西，属于本功能的残留先用 OFF 清理。
3. 写入 ON 标记，安装防直连和 DNS 接管规则，再以 `xq-proxy` 用户对 Windows 网关 `4066` 做 SOCKS5 握手。握手失败时报 `Karing <网关>:4066 SOCKS5 握手失败：…`，并提示 `未自动回退直连。恢复原网络请执行 sudo xq-proxyctl off。`；ON 标记和防直连规则保留，运行中的核心和路由不动。
4. 生成 `/etc/xq-proxy/sing-box.json` 并用 `sing-box check` 校验；resolver 仍是旧版残留时恢复一次原 resolver。
5. 已是 ON、上游端点不变且检查全部正常时保持同一核心进程，否则重启 `xq-proxy.service`，由 `attach` 附加策略路由。
6. 输出状态并探测默认 DNS；配置不完整或探测失败时返回 1，防直连规则保留。

这条路径上的失败不会撤除已有的保护；需要普通网络时明确执行 OFF。

OFF（包括启动时的 `boot-off`）：

1. 需要清理时，先确认 conntrack 可用；resolver 仍是旧版残留时，还要确认原 resolver 备份或 WSL 原始 `/mnt/wsl/resolv.conf` 可验证。任一不满足即报错，不做任何改动。resolver 不是旧版残留时不会被改写，失效的旧备份不影响 OFF。
2. 把防直连规则换成“关闭中”形态：在连接跟踪之前拒绝新的应用 DNS，并去掉 DNS NAT 链，不再产生新映射。
3. 删除 ON 标记，再停止核心；systemd 不会在 OFF 期间重新拉起它。
4. 用 `conntrack -D -f ipv4 --zone 20262 --mark 0x2000000/0x2000000` 精确删除本功能的 DNS 映射。已连接的 UDP socket 因此在 OFF 后改用 WSL 原 DNS，再次 ON 时重新被接管。
5. 移除自有策略路由；仅当 resolver 仍是旧版残留时恢复原 resolver。
6. 删除 `inet xq_proxy` 表。此后查询直接发往 WSL 原 DNS。

只删除 NAT 规则不足以清除已有映射；OFF 不清空全机 conntrack，只删除本功能 zone 和标记位同时匹配的条目。

## 依赖

安装命令见指南第 4 节：

- Python 3、bash、systemd（`systemctl`、`systemd-analyze`）、WSL 提供的 `wslinfo`、curl。
- iproute2：`ip`，以及检查本地 DNS 入口 TCP/UDP 1053 的 `ss`。
- nftables：内核需支持 inet NAT、conntrack zone 和 mark。
- conntrack：控制器固定调用 `/usr/sbin/conntrack`，ON 用它检查 zone 占用，OFF 用它清理本功能的 DNS 映射。
- util-linux（`runuser`，以及隔离测试使用的 `unshare`）、passwd（`useradd`）。
- 官方 sing-box `1.14.4` amd64 包（含 `with_gvisor`），二进制位于 `/usr/bin/sing-box`。

首次安装器的 `--check` 会检查上述命令和 `/usr/sbin/conntrack`，用 `nft --check` 确认内核能加载 ON 与关闭中两种防直连规则，并确认端口 `1053`、conntrack zone `20262` 和 conntrack mark/zone 规则没有冲突。

已在 Ubuntu 24.04 软件源的 conntrack `1.4.8` 上验证。OFF 依赖它在没有匹配条目时返回的 `0 flow entries have been deleted` 提示；换用其他版本前先运行隔离测试。

## 运行时文件与资源

| 项目 | 说明 |
| --- | --- |
| `/etc/xq-proxy/sing-box.json` | 每次 ON 按当前网关和网卡重新生成，含 `tun-in` 和本地 DNS 入口 `dns-in`；不含密钥 |
| `/var/lib/xq-proxy/state.json` | 仅 root 可读：原 resolver 基线、上游端点、规则摘要、运行版本摘要和 DNS zone/标记归属 |
| `/var/lib/xq-proxy/enabled`、`/run/xq-proxy-enabled` | ON 标记与当前启动周期标记 |
| `/run/lock/xq-proxy.lock` | `on`、`off`、`status`、`boot-off` 共用的锁；`attach` 不取锁 |
| 内核资源 | nft 表 `inet xq_proxy`（`dns_zone_output`、`dns_nat_output`、`output`、`forward`）、策略规则 `18400`–`18402`、路由表 `20260`、`xq-tun` `172.30.255.1/30`、conntrack zone `20262` / 标记位 `0x02000000`、`127.0.0.1:1053` |

不要从其他机器复制 `state.json` 或生成的配置；首次 ON 会按目标机器重新生成。

## 检查

状态检查区分配置完整性与有时间限制的系统默认 DNS 探测；resolver 是 WSL 链接或被 WSL 重建，不再单独构成异常。

ON 时依次检查：核心运行；防直连表存在且与安装时摘要一致；TUN 接口；四条策略规则；IPv4 默认路由与 IPv6 不可达路由；resolver 至少有一个 IPv4 DNS 且不是旧版残留；`127.0.0.1:1053` 的 TCP 和 UDP 监听；conntrack 可执行；核心配置与预期一致，运行中的核心已加载当前配置和二进制；resolver 仍是旧版残留时的原 DNS 恢复备份；Windows 网关和网卡未变化。全部通过后，再用 UDP 向 resolver 中的 IPv4 DNS 查询 `example.com` 的 A 记录，总计最多 4 秒。

OFF 时只检查残留：核心仍在运行、`inet xq_proxy` 表仍在、resolver 仍是旧版 TUN resolver，或策略优先级 `18400`–`18402` 上仍有规则。有残留时显示 `OFF，但存在残留配置`、返回 1，并建议执行 `xq_proxyoff`；没有残留时显示 `已关闭（恢复原网络）`、返回 0。ON 用同一个判定区分干净的 OFF。

正常 ON 的关键输出如下，默认 DNS 地址取自目标机的 `/etc/resolv.conf`：

```text
代理状态：已开启（WSL 全流量）
防直连：已开启
DNS 接管：应用 IPv4 TCP/UDP 53 → 127.0.0.1:1053 → 代理 DoH；WSL 继续管理 resolver
配置检查：DNS 入口、接管规则、路由和运行版本正常
默认 DNS 连通性：成功（默认 DNS 10.255.255.254，example.com A）
```

配置异常时逐行显示 `检查异常：…`，并以 `默认 DNS 连通性：未探测（先修复配置异常）` 跳过探测；配置完整但探测失败时显示 `配置完整，但默认 DNS 探测失败；请检查上游和服务日志。`。两种情况都返回 1。`DNS 接管：` 一行是固定说明，不是实时检测结果。

```bash
sudo /usr/local/sbin/xq-proxyctl status
sudo journalctl -u xq-proxy.service -u xq-proxy-boot.service -n 80 --no-pager
sudo journalctl -t xq-proxyctl -n 80 --no-pager
sudo nft list table inet xq_proxy
ss -H -l -n -t -u sport = :1053
sudo conntrack -L -f ipv4 --zone 20262
```

`xq-proxyctl` 标签记录启停结果（如 `attach completed: …; resolver unchanged`、`on completed: configuration and default DNS healthy`、`off completed: …`）、默认 DNS 探测失败、控制器异常，以及 systemd 运行 `boot-off` 时的状态输出；核心的连接日志仍在服务 journal 中。被拒绝的 ON 记在控制器异常里，内容与终端报错相同，例如 `controller failed: Karing 172.21.32.1:4066 SOCKS5 握手失败：…；未改变网络`。

## 测试

以下命令在本目录运行。离线回归测试只使用临时文件和模拟命令层，无需 root、不联网：

```bash
python3 -I test_dns_reliability.py
```

其中 2026-11-15 修订对应的用例包括：干净 OFF 的 ON 在握手失败、核心拒绝配置、resolver 不可用或资源冲突时不留下任何改动，报错和日志内容；通过预检时握手与配置校验先于第一次加载防直连规则；已是 ON 或有残留时仍先保护，失败不撤除保护；失效的旧 DNS 备份不阻塞 resolver 不是旧版残留的 ON、重复 ON、OFF 和 `boot-off`，旧版残留仍能迁移、无法核实时仍然拒绝；以及首次安装器仍能用本控制器渲染内核探测规则。这些用例对 2026-11-14 版本的控制器运行时会失败或报错，属于预期。

隔离规则测试只允许在新建的临时网络命名空间运行，不能用它替代宿主 ON/OFF 与新会话验收：

```bash
sudo unshare --net python3 -I tests/netns-check.py
```

它拒绝在宿主网络命名空间或非全新命名空间中运行，把控制器的文件路径全部重定向到临时目录，不改 resolver，也不启停宿主服务。首次运行可能加载 dummy 内核模块，在宿主留下一个未启用、无地址的 `dummy0`（不影响流量；原本没有时可用 `sudo ip link del dummy0` 删除）。命名空间内用本目录控制器安装真实规则，验证多种用户和目标的 TCP/UDP DNS 接管、客户端源端口 53、核心 UID 无旁路、源端口复用不继承映射、同一 UDP socket 经 ON → 关闭中 → OFF → ON 的切换，以及本地入口或 TUN 丢失时保持防直连。每组通过输出一行 `PASS:`；需要 `/usr/sbin/ip`、`/usr/sbin/nft` 和 `/usr/sbin/conntrack`。2026-11-15 修订没有改动防直连和 DNS 接管规则，这个测试的内容不变。

2026-11-15 修订另在无特权的一次性网络命名空间（`unshare --user --map-root-user --net`，只映射一个 UID）中对真实内核做过一次演练，没有接触宿主网络。真实执行的是控制器的 `on`、`off`、`status`、`attach`，以及它们发出的 `ip`、`nft`、`ss`、`conntrack` 和 `sing-box check` 命令；systemd、核心进程和 Karing 用替身，专用核心 UID 用参数代替（把唯一的 UID 当作核心，或当作应用）。演练内容：干净 OFF 的 ON 在端口拒绝连接、无应答、不是 SOCKS5、核心拒绝配置、resolver 只有 IPv6 时，nft 规则集、策略路由、状态文件前后一致；通过预检的 ON 的命令顺序；重复 ON 握手失败时防直连表不变、握手成功时穿过已安装的防直连规则；带失效旧备份的 OFF、`boot-off` 和重复 ON；以及下一节的各项现象。演练脚本和输出没有纳入仓库。需要多个 UID 或真实 systemd 的部分——不同用户之间的隔离、真实 unit 的启动与自动重启、宿主 ON/OFF——不在其中，仍以 `tests/netns-check.py` 和宿主验收为准。2026-11-15 已以 root 运行 `tests/netns-check.py`（WSL_TUN 与 VPS_TUN 两份），5 组均为 PASS；真实 unit 与宿主 ON/OFF 仍待部署后验收。

## nftables 规则集被整体清空

防直连和 DNS 接管都在 `inet xq_proxy` 一张表里。控制器只增删这张表，但管不了别人清空整个规则集：

- `nft flush ruleset` 删除所有表，包括本表。
- `nftables.service` 的 `ExecStop` 是 `nft flush ruleset`：单元已启动时，停止它（包括 `restart` 的停止阶段）就会清空，与配置文件内容无关。
- `nftables.service` 的 `ExecStart` 和 `ExecReload` 是 `nft -f /etc/nftables.conf`：`start`、`reload`、`restart` 是否清空，取决于该文件是否含 `flush ruleset`。Ubuntu 默认文件含这一行，原机器即如此（2026-11-15 核对时该单元在原机器上未启用、未启动）；自己维护、不含 `flush ruleset` 的配置文件被加载时不会删除本表。

ON 期间本表被清空后的结果：

- DNS 接管立即消失。原机器的 resolver 是 WSL 的本地地址 `10.255.255.254`（位于 `lo`），发往它的查询命中 local 路由表，不经过表 `20260` 和 TUN，于是直接回到 WSL/Windows 的 DNS 路径；已连接的 UDP socket 的下一次查询也是如此。resolver 若是非本地地址，按策略路由仍会进入 TUN，这种情形没有单独测试。
- 其余 IPv4 流量在核心存活期间仍按策略路由进入 TUN；但显式绑定物理网卡的程序不再被拦截，可以直连。
- 核心随后停止时，TUN 设备和表 `20260` 中的 IPv4 默认路由一起消失，IPv4 流量经主路由表直连出站；IPv6 仍被表 `20260` 的不可达路由阻断。核心若是异常退出后由 systemd 重启，`attach` 因找不到本表而报错，不会重新附加路由。

检测：`xq_proxystatus` 返回 1，显示 `防直连：缺失` 和 `检查异常：防直连规则表缺失`。没有定时检查，从清空到下一次执行状态命令之间没有任何提示。

恢复：执行 `xq_proxyon`。通过 conntrack、zone 和端口 `1053` 的只读检查后，它做的第一处改动就是重新装回防直连规则，然后才握手；配置完整时保持同一核心进程。也可以执行 `xq_proxyoff` 回到普通网络。

以上现象在 2026-11-15 的无特权网络命名空间演练中用真实内核确认（systemd 自动重启一项只确认了 `attach` 拒绝附加路由），没有在宿主上清空过规则集。这一节只说明保证到哪里为止，不代表清空规则集是安全操作：ON 期间不要执行 `nft flush ruleset`，也不要启动、重载、重启或停止会清空规则集的 `nftables.service`。

## 已知限制

- 干净 OFF 的预检和核心启动之间仍有间隔：握手通过之后 Karing 才不可用时，ON 照常完成，状态报告默认 DNS 探测失败，防直连规则保留；需要普通网络时执行 OFF。
- 清空整个 nftables 规则集会同时删除防直连和 DNS 接管，见上一节；控制器只能在下一次状态检查时发现。
- conntrack 是离开 ON 的必要条件：ON 期间不要卸载它；缺少时 OFF 和 `boot-off` 会在改动前拒绝执行。
- OFF 在删除 ON 标记之后失败时，不再提示 `未自动回退直连…`，状态显示 `OFF，但存在残留配置`；排除原因后再次执行 OFF 会继续清理。
- 端口 `1053` 的占用者只在 ON 时核对；核心停止或重启的间隙，同机其他本地用户理论上可以监听该端口接收应用 DNS。单用户 WSL 风险较低。
- 冲突检测偏保守：其他 nft 表只要使用 conntrack mark/zone，或本功能核心以外的程序在任意地址占用 TCP/UDP 端口 `1053`，ON 都会拒绝。iptables 规则不在检测范围内：包括 iptables-legacy，以及 iptables-nft 兼容层在 `nft -j` 中显示为 `xt` 的 CONNMARK、CT --zone、connmark 等；有这类规则时需自行确认它们不改动 conntrack mark/zone。
- 防直连表摘要按 `nft --stateless list table inet xq_proxy` 的文本计算；nftables 升级或手动修改该表后，状态会报告摘要不匹配，执行 `xq_proxyon` 重新应用即可。
- 首行 `代理状态：已开启（WSL 全流量）` 在 DNS 探测之前输出；探测失败时以退出码 1 为准。

不要通过放开非 TUN DNS、全局清空 nftables 或清空全机 conntrack 来解决异常。OFF 清理范围仅为本功能拥有的资源。
