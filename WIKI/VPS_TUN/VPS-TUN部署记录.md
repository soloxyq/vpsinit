# Mico-system TUN 部署记录

> 2026-11-14 更新：下文记录独立命名空间方案。当前已安装的 `xq_proxyon/off/proxystatus` 已升级为用户级入口，影响 xuqian 的全部宿主会话；局域网直连。请以[用户级代理说明](scripts/xq-user-proxy/README.md)为准。`xq_tun run` 仍可用于独立命名空间。

部署日期：2026-11-13。目标：`Mico-system / 192.168.5.173`，用户 `xuqian (1006:1006)`，上游 `192.168.5.34:4066`。

**独立命名空间核心已安装并完成验收。** 当前用 `xq_tun shell` / `exit` 进出子 shell，用 `xq_tun run` 启动指定程序。早期同名 `xq_proxyon/off` 的子 shell 语义仅保留在下方历史记录中；现已改为用户级开关。

此前工具策略阻止了 sudo 认证输入；用户调整权限后，已通过宿主交互 sudo 完成安装。本记录替代早先“待交互安装”的状态说明。密码未写入安装文件或配置。

## 使用

独立命名空间模式：

```bash
xq_tun shell
```

看到 `[TUN]` 后启动程序，用 `exit` 返回；或只运行指定程序：

```bash
xq_tun run claude
```

当前宿主用户级开关使用 `xq_proxyon/off/proxystatus`，保留原 shell，影响 xuqian 全部宿主会话，详见[用户级说明](scripts/xq-user-proxy/README.md)。

管理命令在宿主终端执行：

```bash
xq_tun stop
xq_tun start
```

`stop` 停止核心并保留命名空间与防漏规则；已有隔离应用会断网，`start` 后恢复新连接。入口不会在代理失败时把应用改到宿主网络执行。

入口使用清洁环境并清除附加组、管理能力，设置 `no_new_privs`。依赖 API Key 等自定义环境变量的应用，需要在隔离 shell 内按原有方式配置。HOME 和工作目录仍属于 `xuqian`，这不是文件系统容器。完整说明见 [安装包 README](scripts/xq-tun/README.md)。

## 已完成的验收

安装器和自动验收均以退出码 `0` 结束。

| 项目 | 实测结果 |
| --- | --- |
| 核心与应用网络边界 | 核心处于宿主网络；应用进入独立 namespace，其中只有 `lo` 和 `xq-tun0` |
| 应用权限 | UID/GID `1006:1006`，没有额外附加组，capabilities 清空，`NoNewPrivs=1` |
| 应用 DNS 文件 | 专属 resolver/NSS 生效，DNS 指向 `172.30.255.2` |
| DNS UDP/TCP | Python 协议查询均成功，经 sing-box DoH/SOCKS 出站 |
| 系统域名解析 | 隔离应用的 `socket.getaddrinfo` 成功 |
| 忽略代理变量的 HTTPS | 成功，公网出口 `179.255.139.228` |
| IPv6 | 隔离应用 IPv6 公网连接失败，符合首期设计 |
| 停止核心 | 同一个已运行的隔离进程无法建立公网 TCP 连接，DNS UDP/TCP 查询均失败 |
| 恢复核心 | 同一个隔离进程的新 HTTPS 和 DNS 查询恢复成功 |
| 宿主前后对照 | IPv4/IPv6 路由、策略规则、resolver 内容和链接、nftables 及转发参数均未改变 |
| 普通用户入口 | 实际执行 `xq_tun run /usr/bin/id` 成功，输出 `uid=1006(xuqian) gid=1006(xuqian) groups=1006(xuqian)` |
| 最终服务状态 | `xq-tun.service` 为 `active/running`；`xq-tun-netns.service` 为 `active/exited` |
| 开机状态 | 两个单元均为 `disabled` |

核心停机验收用数字 IP 访问 HTTPS，避免把“仅 DNS 不通”误当作 TCP 也已阻断。宿主对照使用安装前后的结构化快照，忽略 nftables 流量计数变化。

安装期间 `systemd-analyze verify` 对本机已有 `snapd.service` 的 `RestartMode` 字段发出兼容性提示；命令退出码为 `0`，该已有服务未被本次修改。

## 安装内容与备份

| 内容 | 路径或值 |
| --- | --- |
| 固定核心 | `/usr/local/lib/xq-tun/sing-box-1.14.4/sing-box` |
| 核心配置 | `/etc/xq-tun/sing-box.json` |
| 固定用户与上游设置 | `/etc/xq-tun/settings.json` |
| 管理器 / 用户入口 | `/usr/local/sbin/xq-tunctl`、`/usr/local/bin/xq_tun` |
| DNS/NSS | `/etc/netns/xq-tun/` |
| systemd 单元 | `/etc/systemd/system/xq-tun.service`、`xq-tun-netns.service` |
| 本次备份 | `/var/backups/xq-tun-20261113-220104-FlesCo4Q/` |
| 基线对照 | 上述目录内的 `host-before.json`、`host-after.json` |
| 最新备份指针 | `/var/lib/xq-tun/latest-backup` |

使用官方 sing-box `1.14.4` Linux amd64 归档，下载经指定 SOCKS5 代理。SHA256 已验证为：

```text
699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968
```

首次部署没有修改 `.bashrc`。后续按用户要求，仅给 `xuqian` 的 `.bashrc` 加载新的终端函数；sudoers、宿主默认网络、其他用户配置和 Docker 配置保持原状。可执行安装包保存在 [scripts/xq-tun](scripts/xq-tun/README.md)。

## 历史阶段：终端子 shell 开关与实测（已被用户级开关替代）

2026-11-13 将公开命令改为 `xq_tun`，新增受管理的交互 shell 启动文件，并让 `xq_proxyon/off` 通过进入/退出子 shell 改变本终端后续程序的网络环境。旧 `xq-tun` 命令文件经摘要校验后备份移除；内部 namespace、服务和控制器继续沿用原名称。

升级只更新入口文件和本用户 `.bashrc`，没有重启核心或修改网络。升级与测试前后核心 PID 均为 `2460344`；结构化宿主网络快照一致。

| 实测 | 结果 |
| --- | --- |
| A 开启、B 保持普通终端 | A 进入 TUN，B 仍在宿主 namespace |
| A 重复 ON、在其中执行 `xq_tun shell` | shell PID 不变，没有嵌套 |
| A 内 `xq_tun run /usr/bin/id` | 正常执行，UID/GID 为 `1006:1006` |
| A 内忽略代理变量的 HTTPS | 出口为 `179.255.139.228` |
| 手动嵌套 Bash 和括号子 shell 中 OFF | 拒绝，外层 TUN shell 保留 |
| 有运行或暂停作业时 OFF | 拒绝退出，不终止任务 |
| A 切换工作目录后 OFF | 返回原宿主 namespace 与进入前工作目录，旧代理变量已清空 |
| B 独立 ON，随后 A OFF | B 的 shell PID 和 TUN namespace 保持，HTTPS 仍经 `179.255.139.228` |
| 宿主误执行 OFF | 终端保留，核心继续运行 |
| 新指定程序入口 | `xq_tun run claude --version` 返回 `2.1.325 (Claude Code)` |

本轮系统文件备份与快照：`/var/backups/xq-tun-shell-20261113-223304-VwiWiJhs/`。

本轮个人 shell 备份：`/home/xuqian/.bashrc.before-xq-tun-20261113-223304-pl7cz8oj`。

以上测试记录的是当时的子 shell 开关，不能作为现在同名函数的操作说明。当前执行 `source ~/.bashrc` 会加载用户级开关；独立环境的现行入口见[独立模式说明](scripts/xq-tun/README.md)。

## 尚未覆盖的测试

首期普通 UDP 和 ICMP由配置拒绝，尚未做独立数据验收；上游 UDP 能力也未确认。没有模拟上游服务器故障、执行整机重启或单独测试各 Docker 容器的业务请求。已确认的是 Docker 相关宿主 nftables 和路由保持原状。

若需要开机启动，可在完成业务使用确认后执行 `sudo systemctl enable xq-tun.service`。完整停用与移除步骤见 [安装包 README](scripts/xq-tun/README.md#检查与移除)；不要清空全机路由或防火墙。
