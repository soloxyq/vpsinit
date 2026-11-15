# WSL 全流量代理部署记录

部署日期：2026-11-13（America/Los_Angeles）。本页记录已经安装、启用并完成验收的版本；早先的方案页只代表部署前讨论。

另一台全新 WSL 请执行 [从零复现指南](WSL-从零复现指南.md)。本页的 IP、UID、备份名和 ON/OFF 是原机器在不同测试时点的记录，不是新机器的固定配置或实时状态。

## 当前效果

公网连接路径为：WSL 程序 → `xq-tun` → Windows Karing 全代理端口 `4066` → Karing 所选节点。

- `xq_proxyon` 接管当前 WSL 网络命名空间中的普通程序、其他终端和后台程序的公网连接，不再仅设置当前 shell 的代理变量。
- IPv4 TCP/UDP 经 TUN 转发；DNS 由 TUN 接收，再通过代理上的 DoH 查询。
- 本次实现明确阻断不支持的 IPv6，不回落到物理接口直连。
- 独立 nftables 规则在代理核心停止后仍阻止公网直连；代理恢复后重新附加路由和 DNS。
- `xq_proxyoff` 是用户明确恢复原网络的操作，会停止隧道、恢复原 DNS 和路由，并最后移除本功能自己的防直连规则。
- 初次部署验收结束时曾保持 **ON**；当前实时状态请运行 `xq_proxystatus`。

最新启动策略：**每次 Ubuntu/WSL 完整启动时默认 OFF**，同一个运行环境中新开终端不会改变开关。之后只通过用户手动执行 `xq_proxyon/off` 切换；没有定时检查或自动重试机制。OFF 恢复普通网络，不经过 TUN。

历史 OFF 联网检查：用户反馈新终端 DNS 失败时，日志显示仍是部署前已启动的同一次 WSL 运行，且 TUN 仍处于此前保留的 ON。随后实际执行 OFF，确认 `ip.sb`、`baidu.com` DNS 正常，`http://ip.sb`、`https://www.baidu.com`、`https://icanhazip.com` 返回 HTTP 200，直连出口 `223.73.5.58`；TUN 设备消失，自有策略路由清除。那次处理后保持 OFF；后续用户又手动开启并完成了 ON 审查。以上为用户要求的普通 OFF 联网验收，不是绕过 ON 保护的测试。

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

| 项目 | 已部署内容 |
| --- | --- |
| 代理核心 | 官方 sing-box `1.14.4` |
| 防火墙工具 | nftables |
| 专用账号 | 非登录用户 `xq-proxy`，本机 UID `999` |
| 控制器 | `/usr/local/sbin/xq-proxyctl`，由 root 安装管理 |
| 核心配置 | `/etc/xq-proxy/sing-box.json` |
| 核心服务 | `xq-proxy.service` |
| 启动复位服务 | `xq-proxy-boot.service`，已启用；执行一次 `boot-off`，默认恢复普通网络 |
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
| DNS 地址 | `172.30.255.2` |
| TUN MTU | `1280` |
| 路由表 | `20260` |
| 策略规则优先级 | `18400`、`18401`、`18402` |
| nftables 自有表 | `inet xq_proxy` |
| SOCKS5 上游 | 启动时探测的 Windows 网关，端口 `4066` |

控制器手动管理策略路由，sing-box 的 `auto_route` 关闭，以便由同一个控制器完整恢复自己的规则。返回 TUN 的流量和专用代理用户使用主路由表，其他流量进入表 `20260`；IPv6 对应路由明确设为不可达。

DNS 查询规则将 TUN 中的端口 53 流量交给 sing-box DNS；DoH 使用 `1.1.1.1:443`、TLS 名称 `cloudflare-dns.com`，并显式通过 Karing SOCKS5 出站。没有通过系统 DNS 为 DoH 服务器做启动解析。

原先 `/etc/resolv.conf` 是指向 `/mnt/wsl/resolv.conf` 的符号链接。ON 时只替换发行版自己的链接入口，不写穿共享目标；OFF 恢复原符号链接。

独立防直连规则只放行必要路径：loopback、IPv4 TUN、专用核心用户到准确 Karing 网关的 TCP4066 和动态 SOCKS UDP 中继。非 TUN 的 DNS53 在 loopback 放行之前即被拒绝。没有对所有旧 `established` 连接无条件放行，也没有给专用代理用户任意公网直连权限。forward 链同样受限制。

## 故障与重启行为

- 核心失败时，独立 guard 保留，普通程序不能自动回落到物理接口直连。
- 核心重启后，`ExecStartPost` 重新附加策略路由和 DNS；该操作没有与主控制锁形成互锁。
- 已经是 ON 时再次执行 ON，检查健康后保持同一核心进程；端点变化或规则不完整时进行恢复。
- OFF 会停止核心、恢复原状态，最后删除 guard。
- ON 标记用于保存当前状态和恢复信息，不再表示下次开机自动 ON。启动复位服务无条件执行一次 `boot-off`，清除旧 ON 标记、恢复普通 DNS/路由。此动作不会等待 Karing 上游可用。
- 同一个 WSL 运行环境中关闭窗口再新开终端，不一定是完整重启，因此不会自动重置已经手动开启的代理。
- `xq-proxy.service` 本身仍未单独设置开机启动；没有 health service、health timer 或 5 秒重试。
- 已通过实际启动复位单元验证 `boot-off` 动作，并检查新终端不会改变 ON/OFF。**本次尚未执行完整 WSL 重启**，不把单元测试等同于重启验收。

## 已完成的验收

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
| 完整启动所用的 `boot-off` 动作 | 已验证 ON 标记清除、核心停止、原 DNS 链接及路由恢复 |
| 新终端保持既有状态 | 分别在 OFF 和 ON 下验证，新终端均不触发开关 |

本次测试没有发出不受保护的公网直连请求，也没有调用 Windows 程序。忽略应用代理变量的测试是在网络层接管和直连阻断均生效后执行的，不属于关闭保护后的直连对照。

## 只读检查与恢复命令

`xq_proxystatus` 现已区分“开关选择了 ON”与“配置完整”：检查核心、TUN 接口、策略规则中的接口/UID/路由表、IPv4 默认路由、IPv6 阻断路由、DNS、恢复备份和当前网关。发现异常时显示具体项目并返回退出码 1，正常返回 0。它只读取状态，不自动改配置、不访问公网，也没有定时运行。

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
sudo nft list table inet xq_proxy
```

核心未工作时先看日志：

```bash
journalctl -u xq-proxy.service -n 80 --no-pager
journalctl -u xq-proxy-boot.service -n 80 --no-pager
```

需要用户明确恢复普通网络时，直接运行以下根控制命令；即使 shell 函数未加载也可使用：

```bash
sudo /usr/local/sbin/xq-proxyctl off
```

不要通过清空全机 nft 规则或直接删除所有策略路由恢复网络。控制器只管理自己的表、规则和备份。

## 备份与迁移

本机部署前备份：

```text
/var/backups/xq-proxy-before-deploy-yrrosx1p
/home/chris/.bashrc.before-tun-v_jgsv2s.bak
/var/backups/xq-proxy-before-default-off-b7ics53n
```

可复现文件副本归档于 `scripts/xq-proxy/`。迁移前应核对归档说明；当前网关地址、专用 UID 和 Karing 端口的可达性要在目标机器重新确认，不能直接把本机动态状态复制过去。

普通 VPS 通常没有 Windows 宿主机网关。它需要显式配置真实 SOCKS5 上游；不要把本机的默认网关探测逻辑照搬为 VPS 的代理地址。

本页没有记录密码、API Key、订阅内容或账号令牌。

## 状态检查与 DNS 恢复改进

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

离线回归测试只使用临时文件和模拟命令层，不需要 root 或联网：

```bash
python3 ~/WIKI/scripts/xq-proxy/test_dns_reliability.py
```
