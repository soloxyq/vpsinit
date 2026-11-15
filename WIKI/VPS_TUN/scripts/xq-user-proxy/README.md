# Mico-system 用户级 TUN 代理

**新 VPS 请使用 [便携一键部署指南](../../VPS-用户级TUN一键部署.md)。** 本目录保留 Mico-system 的历史部署及安装器，不用于在其他机器首次安装。

当前安装：`xq-user-proxy.service` 接管宿主 xuqian（UID 1006）的所有会话；`xq-tun.service` 是另一个用于 `xq_tun run` 的独立命名空间服务。

2026-11-14 已完成[固定值与权限审计](../../VPS-TUN固定值与访问权限审计.md)：本机地址/接口和出口动态获取，私有 DNS 与 TUN 出口限制 owner 使用；root/其他 UID 的普通入口调用被拒。真正的 root 管理员仍可修改规则或切换 UID，不能据此声称可防管理员绕过。

修复后已完成不停服验收，保持 ON，出口为 `179.255.139.228`。真实交互测试确认 `xq_proxyon` 返回原 shell，PID、namespace 和工作目录不变，新终端自动沿用用户状态。其他 UID 不被本功能接管；结果与限制见[最终验收记录](../../VPS-用户级TUN验收记录.md)。

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
