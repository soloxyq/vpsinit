# 便携用户级 TUN 安装包

这是另一台 VPS 的首次安装入口。提供 SOCKS5 代理的 IPv4 地址和端口，脚本为当前普通用户生成配置并部署用户级 TUN；用户名、UID/GID 不沿用 Mico-system 的数值。

完整流程、故障处理及隔离边界见 [VPS 用户级 TUN 一键部署](../../VPS-用户级TUN一键部署.md)。

## 安装

支持使用 systemd 的 Debian 12+ / Ubuntu 22.04+，CPU 为 x86_64 或 aarch64；安装前需有 Bash 和 Python 3.9+。目标用户须已有 sudo 管理权限，还需要内核 TUN 支持，以及可达的无认证 SOCKS5 TCP 代理。安装器会通过 apt 准备缺少的系统依赖，经给定代理下载 [sing-box 1.14.4 官方发行包](https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4) 并核对内置 SHA256。

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

普通用户运行时自动选择该用户；`sudo bash install.sh ...` 会识别 sudo 前的用户。目标必须是已有的非 root 账号，并已有后续执行开关所需的 sudo 管理权限。root 使用 `--user` 代装不会自动授予目标账号 sudo 权限；安装器不写 sudoers。每台 VPS 只允许本安装包管理一个用户，遇到旧安装或资源冲突会拒绝，不提供原地升级。

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
- 私网、链路本地及多播/广播按宿主路由直连；公网 IPv4 TCP 经代理，公网 UDP、ICMP 和 IPv6 主动出站阻断。DNS 经专用入口及代理 DoH，显式局域网 DNS 保持直连。
- 不全局替换 DNS，不授予 sudoers 免密权限，不创建定时回滚。核心故障时保留阻断规则，不自动恢复公网直连。
- root 及其他 UID 的正常新建连接不被接管，专用 DNS/TUN 入口限制 owner。root 管理员仍能修改规则或切换身份绕过。owner 的 DNS 改写放在专用 conntrack zone `20261`，其他用户复用相同 UDP 源端口时不会再套用它，反之亦然（2026-11-14 修复，`tests/netns-check.py` 含回归测试）。

本目录的便携脚本与现有 Mico-system 安装分开维护；编辑或打包它不会更新正在运行的服务。

## 验证范围

已完成离线身份、安全与配置测试及 `sing-box check`；在隔离的测试网络中验证了 owner 专属入口、root/其他 UID 的普通 DNS/TCP/UDP，以及拒绝访问私有入口。模拟 TUN 消失时，目标用户黑洞路由保留，root 原路由和 DNS 仍可用。尚未在第二台真实 VPS 完整执行安装；这些检查不能替代目标机器的 systemd、软件包、网络和端到端连通性验收。

维护者可从本目录复查。第二条只允许在一个全新的临时网络命名空间运行，拒绝在宿主网络中加载测试规则：

```bash
python3 -I tests/test_portable.py
sudo unshare --net python3 -I tests/netns-check.py
```
