# Mico-system 用户级 TUN：修复后验收

整理日期：2026-11-14（America/Los_Angeles）。本轮保留 Claude 的局域网修复，在服务持续运行的条件下完成检查；没有重新安装核心、切换 OFF、停服务或修改网络规则。

## 最终状态与用法

**用户级代理保持 ON。** `xq_proxyon/off/proxystatus` 管理宿主 `xuqian`（UID 1006）的全部会话，函数执行后仍留在原 shell。其他 UID 不被这些规则接管。

已有终端加载一次更新，新终端会自动加载：

```bash
source ~/.bashrc
xq_proxyon
claude
```

查看状态用 `xq_proxystatus`；明确恢复 `xuqian` 宿主会话原网络时用 `xq_proxyoff`。关闭某个终端不会关闭后台代理，重启服务器后用户级开关默认 OFF。

指定程序模式继续独立工作：

```bash
xq_tun run claude
```

该命令使用另一个网络命名空间与核心，不受用户级 OFF 停止。独立交互环境仍可用 `xq_tun shell` 进入、`exit` 退出；在其中不能操作宿主用户级开关。

## 本轮已完成检查

| 检查 | 结果 |
| --- | --- |
| 用户级服务 | `active`，PID `2607788`；检查前后不变 |
| 独立命名空间服务 | `active`，PID `2460344`；检查前后不变 |
| 控制器与配置 | `check` 成功，源码/安装版控制器和 shell helper 一致 |
| 当前 shell 的 ON | 真实交互调用成功，Bash PID、网络命名空间和工作目录均不变 |
| 现有 UID1006 进程 | 在原宿主 namespace 中，通过代理访问 HTTPS 成功 |
| 新 UID1006 进程 | 自动沿用用户级代理，未进入子 namespace |
| 公网出口 | 忽略代理变量的 HTTPS 返回 `179.255.139.228` |
| 默认 DNS | UDP/TCP 协议查询及 libc `getaddrinfo` 成功 |
| 显式 DNS 查询 | `dig @192.168.5.2 example.com` 与 `dig @1.1.1.1 example.com` 均返回 `NOERROR`；前者按 LAN 例外直连，后者按公网 DNS 规则接管 |
| 局域网 | xuqian ping `192.168.5.34`，1 发 1 收，无丢包 |
| 其他 UID | root、UID65534 的受控本地 HTTP/UDP 和原 DNS 均正常 |
| xuqian 本机服务回复 | root 客户端能访问其受控本地 HTTP/UDP 服务 |
| 旧代理端口兼容 | UID1006 的新 `16791` 连接具有预期 conntrack 标记和 `4066` 回程映射；CONNECT、TLS 校验与 HTTPS 成功。该兼容改写已于同日后续删除，现只使用 `4066`，见[用户级说明](scripts/xq-user-proxy/README.md) |
| 宿主基线 | 排除明确声明的自有表、规则和 TUN 路由后，与用户级安装前一致；resolver、无关 nftables、其他路由和转发参数保持原样 |
| 独立指定程序入口 | `xq_tun run curl ...` 返回同一代理出口；`xq_tun run claude --version` 返回 `2.1.325 (Claude Code)` |
| 回滚定时器 | 相关 timer/service 均 `not-found/inactive`，定时器列表为 0 |
| TUN 接口参数 | `xq-utun` 的 IPv6 已关闭；`rp_filter=2`，宿主 `all.rp_filter=2`；本轮未修改这些参数 |

“其他 UID 正常”是上述受控请求与规则/路由基线的实测结果，不表示已逐一测试所有用户的业务或所有 Docker 容器。

## 本轮完成的代码与文档工作

- `verify.py` 默认改为不停服检查，不调用 ON/OFF、start/stop，也不添加防火墙表。新版已同步到安装位置并通过验收，退出码为 `0`。
- 停核心和 OFF/ON 演练改为显式维护选项 `--exercise-switches`，本轮没有执行。若该演练在停核阶段失败，只恢复它主动停止的核心，防直连规则保持，不自动 OFF。
- 修正维护演练的独立保护表位置，使其位于主 guard 之后的 POSTROUTING，并使用该 hook 支持的 `drop`。
- 安装器适配新的不停服验收流程。安装是显式启用操作，验收失败不会自动恢复直连；没有定时回滚。
- 清理旧文档中仍把 `xq_proxyon/off` 写成进出子 shell 的现行教程，保留历史记录并指向新说明。

验收与备份目录：

```text
/var/backups/xq-user-proxy-live-20261113-KzVGamSt/
```

其中有旧版验收器 `verify-before.py`、安装前宿主基线、ON 状态快照及 `verification.log`。新版验收器源码/安装版 SHA256 一致。

## 边界与未重复测试的内容

保留用户要求的 LAN 直连，包括私网、链路本地、多播/广播及显式 LAN DNS。公网 IPv4 TCP 经代理；普通公网 UDP、ICMP 和 IPv6 主动出站阻断。完整网段见[用户级说明](scripts/xq-user-proxy/README.md)。

未重新执行停核心、OFF 恢复、旧代理长连接跨 OFF、整机重启、远程入站服务或所有私网/IPv6目标测试。此前直接停止核心导致保护性断网的事实见[诊断记录](2026-11-14-用户代理断网诊断.md)；不要将 `systemctl stop xq-user-proxy` 当作正常 OFF。

规则按照宿主 socket UID 和连接标记识别；由 root、其他 UID、容器或共享守护进程代发的请求不能视为已经由这个用户级开关接管。OFF 也不会改写其他已运行程序的代理环境变量；已经建立的旧代理连接保留到自然关闭。
