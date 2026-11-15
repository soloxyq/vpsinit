# 另一台 VPS：用户级 TUN 一键部署

使用 [scripts/xq-user-tun](scripts/xq-user-tun/README.md) 为新 VPS 的当前普通用户部署 TUN。安装时只需提供代理 IP 和端口；用户名、UID/GID 从目标系统获取，本机物理 IP、网卡和公网出口不写死。此入口不依赖之前在 Mico-system 安装的独立命名空间服务。

本指南描述新机器的首次安装。旧的 [Mico-system 部署记录](VPS-TUN部署记录.md)、[用户级验收记录](VPS-用户级TUN验收记录.md) 和 [权限审计](VPS-TUN固定值与访问权限审计.md) 保留历史用途，不能把其中的实测 IP、UID 或备份路径直接套用到新服务器。

## 1. 安装前提

| 项目 | 要求 |
| --- | --- |
| 系统 | Debian 12+ / Ubuntu 22.04+，使用 systemd 管理服务；安装前需有 Bash 和 Python 3.9+ |
| 架构 | x86_64/amd64 或 aarch64/arm64 |
| 权限 | 目标是已有且具备 sudo 管理权限的普通用户；不以 root 作为被代理用户，安装器不授予 sudo 权限 |
| 内核 | 可用的 `/dev/net/tun`、nftables 和策略路由；宿主/容器需授予所需网络管理能力 |
| 上游 | 从新 VPS 可达的 SOCKS5 IPv4 地址及端口，无用户名密码认证，支持 TCP |
| 下载 | 能通过 apt 获取缺少的发行版依赖，并通过给定代理下载 sing-box 1.14.4 官方发行包；可提供对应架构的本地官方 `.tar.gz` |
| 共存 | 单台机器只由此安装包管理一个目标用户；安装前不能存在同名旧部署或占用其专用资源 |

例如，当前机器使用的 `192.168.5.34:4066` 是局域网代理。另一台公网 VPS 只有具备到该私网的网络路径时才能继续使用；否则应提供新 VPS 可达的代理地址。脚本会在改动代理网络规则前验证 SOCKS5 连接和 HTTPS。

若代理实际只支持 HTTP CONNECT，或要求用户名/密码，本安装包不适用；不能把它当作无认证 SOCKS5 端口使用。

自动安装缺少的系统包可能执行软件包维护脚本，因此不能承诺整个安装过程对系统其余部分绝无影响。已有复杂防火墙或其他网络管理服务的 VPS，建议管理员先预装所需依赖（`iproute2`、`nftables`、`iptables`、`conntrack`、`curl`、`util-linux`、`sudo`、`ca-certificates`），核对软件包操作和防火墙状态后再运行安装器。

## 2. 将安装包放到新 VPS

可以复制 WIKI 中的整个 `scripts/xq-user-tun/` 目录，也可以使用打包文件：

- [下载 xq-user-tun.tar.gz](dist/xq-user-tun.tar.gz)
- [下载 SHA256 校验文件](dist/xq-user-tun.tar.gz.sha256)

从持有 WIKI 文件的机器复制到目标 VPS，以下账号和地址需要替换：

```bash
scp dist/xq-user-tun.tar.gz dist/xq-user-tun.tar.gz.sha256 your-user@your-vps:~/
ssh your-user@your-vps
sha256sum -c xq-user-tun.tar.gz.sha256
tar -xzf xq-user-tun.tar.gz
cd xq-user-tun
```

此处没有公开下载站点或 `curl | bash` 地址；使用本 WIKI 中实际生成的文件。只复制 `install.sh` 会缺少配套控制器、配置和服务文件。

## 3. 一键安装

登录将使用 TUN 的普通用户，执行：

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066
```

将示例 IP 和端口替换为新 VPS 的上游。也可以交互输入：

```bash
bash install.sh
```

脚本自动确定当前用户，需要时调用 sudo。若使用 `sudo bash install.sh ...`，目标仍是 sudo 前的普通用户。以 root 直接登录时必须明确指定已有普通账号：

```bash
bash install.sh --user alice --proxy-ip 192.168.5.34 --proxy-port 4066
```

`alice` 仍须事先具备运行开关所需的 sudo 管理权限。root 代装不会为目标账号授予 sudo 权限，安装器不写 sudoers。

安装器准备依赖、获取 [sing-box 1.14.4 官方发行包](https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4) 并核对内置 SHA256、检查资源冲突、生成仅属于该账号的配置、安装 systemd 服务及 Bash 快捷函数。默认随后开启用户级 TUN，不修改全局 `/etc/resolv.conf`。

已有安装，包括当前 Mico-system 的历史部署，会被拒绝；此脚本不用于更新正在运行的服务。检测失败时先处理具体错误，不要用删除未知路由、防火墙规则或安装标记的方式强行通过。

安装完成后，在目标用户的终端执行：

```bash
source ~/.bashrc
xq_proxyon             # 默认已 ON；此命令检查/恢复服务，并清理当前 shell 的旧代理变量
xq_proxystatus
curl --disable --proxy '' --noproxy '*' -4 --fail --max-time 20 https://api.ipify.org
```

安装器无法修改此前打开的终端及其他进程的环境变量；只执行 `source ~/.bashrc` 也不会自动清理旧变量。在要继续使用的终端中执行 `xq_proxyon` 才会清除该 shell 的常见代理变量。其他终端需分别处理，已运行进程可能需要重启。

公网出口是运行时查询结果，换代理节点后可以变化，没有固定的预期 IP。

### 只安装，稍后开启

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066 --no-start
source ~/.bashrc
xq_proxyon
```

`--no-start` 仍会完成安装前的环境及代理检查，但不启用用户 TUN。

### 先查看生成结果

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066 \
  --render-dir /tmp/xq-user-tun-preview
```

目标目录必须尚不存在。此模式只生成配置文件，不包含 sing-box 核心，不提权、不安装依赖、不写系统目录、不改网络。它验证输入和配置生成，不代替目标机器上的内核、权限、资源冲突和实际连通性验收。

### 使用已下载的 sing-box 官方发行包

```bash
bash install.sh --proxy-ip 192.168.5.34 --proxy-port 4066 \
  --archive /path/to/sing-box-1.14.4-linux-amd64.tar.gz
```

arm64 机器使用 `sing-box-1.14.4-linux-arm64.tar.gz`。本地包也必须匹配安装器固定的版本、架构及内置 SHA256，不能自行重新打包。此选项只跳过核心下载，不保证整个安装过程离线：系统依赖可能仍需安装，上游代理也需要实测。

## 4. 日常命令

```bash
xq_proxyon             # 开启或恢复服务，保留当前 shell
xq_proxystatus         # 查看目标用户的代理状态
xq_proxyoff            # 明确关闭，恢复原网络
```

启动 Claude Code：

```bash
xq_proxyon && claude
```

这些命令不会进入新的交互式 shell。开关覆盖目标 UID 的全部宿主会话及新进程，不是单个终端；关闭终端不会关闭服务，新终端沿用当前状态，完整重启后默认 OFF。部分切换前建立的公网长连接可能需要重新连接。

快捷函数会清除调用终端的常见代理环境变量，但无法改写其他已运行进程的环境。程序若自行指定代理，或由 root、其他 UID、容器、共享守护进程代发网络请求，不属于同一用户的宿主 TUN 接管保证。

本包仅安装用户级开关。原机器的 `xq_tun run claude` 属于另一个独立命名空间方案，本次便携安装不会额外创建该命令。

## 5. 转发和阻断范围

```text
目标用户的宿主程序
    → 按 UID 标记的策略路由
    → 私有 TUN / DNS 入口
    → sing-box
    → 指定 SOCKS5 代理
    → 互联网
```

| 流量 | 行为 |
| --- | --- |
| 目标用户主动访问公网 IPv4 TCP | 经 TUN 和 SOCKS5 上游 |
| 默认系统 DNS、显式公网 IPv4 DNS | 转入专用 DNS 入口，通过代理 DoH 查询 |
| 显式局域网 DNS | 按宿主路由直连 |
| IPv4 私网、链路本地、多播/广播 | 直连；不强绑某块物理网卡 |
| IPv6 ULA、链路本地、多播 | 直连；是否可达取决于宿主网络 |
| 公网 UDP、ICMP/ping、IPv6 主动出站 | 阻断；上游 TCP 方案不提供这些传输 |
| root 和其他 UID 的普通新连接 | 不按目标用户规则接管 |

直连例外是 IPv4 `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`224.0.0.0/4`、`255.255.255.255/32`，IPv6 `fc00::/7`、`fe80::/10`、`ff00::/8`。因此“防直连”指对受管公网流量的阻断策略，不代表封掉全部局域网通信。

公网 ping 不通是预期策略，不能据此判断 Claude Code 或 HTTPS 代理失效。

## 6. 出错时的处理

不会创建定时回滚，也不会在检查失败、核心退出或上游断开时自动 OFF。保护规则独立于核心运行；核心故障可能中断目标用户的公网访问，直到明确恢复或关闭。

先检查状态和日志：

```bash
xq_proxystatus
sudo /usr/local/sbin/xq-user-proxyctl check
sudo systemctl status xq-user-proxy.service --no-pager
sudo journalctl -u xq-user-proxy.service -n 80 --no-pager
```

恢复代理使用 `xq_proxyon`。明确要恢复该用户原网络时使用 `xq_proxyoff`。若 Bash 函数还没加载，可调用：

```bash
sudo /usr/local/sbin/xq-user-proxyctl on
sudo /usr/local/sbin/xq-user-proxyctl off
```

不要将 `systemctl stop xq-user-proxy.service` 当作 OFF：它只停止核心，仍会留下防直连保护和黑洞路由。

如果安装在开启阶段失败，按安装输出中的路径检查已写入配置和日志，不要假设系统自动恢复了安装前的网络状态。安装记录及备份路径以该次脚本输出为准。

## 7. 用户隔离的边界

入口和路由按安装时确定的非 root UID 限制，其他普通用户不能借用私有 DNS 或 TUN 出口；root 的正常新建应用连接也不会自动被接管。系统 DNS、主路由和无关用户规则不被全局替换。

这不是防不可信 root 管理员的隔离方案。root 及拥有等价管理权限的人可以修改规则、替换程序或切换到目标 UID，无法在同一台 VPS 内禁止这些管理能力。

共享宿主网络的 conntrack 五元组不包含 UID。为此，目标用户的 DNS 改写及私有 DNS 入口的回复放在专用 conntrack zone `20261`：其他用户即使复用了相同的 UDP 源端口，也只会在默认 zone 中新建自己的连接，不会套用目标用户的映射，反之亦然。目标用户的其他连接仍记录在默认 zone，只带标记、不做地址改写；规则均先按 socket UID 判断。即便如此，也不能承诺任何异常场景下都对其他用户零影响；要求严格隔离时应另外设计独立命名空间或容器方案。

其他用户自行连接远端代理 IP 和端口不属于借用本 TUN。若连远端代理本身也要限制，应在代理服务器上配置访问控制或认证；本包不会顺带封禁其他用户的正常 LAN 连接。

## 8. 保留的配置常量

每次安装动态生成用户名、UID/GID 和上游地址；运行时不固定物理 IP、网卡名或出口 IP。下列项目仍是配套配置，不是从 Mico-system 复制的物理网络信息：

- TUN 名 `xq-utun`、内部地址 `172.30.254.1/32`、私有 DNS `127.0.0.1:1053`。
- 策略路由表 `20261`、conntrack zone `20261`、优先级 `18410`、nftables 表 `xq_user_proxy` 和专用标记位。
- DoH `1.1.1.1:443` / `cloudflare-dns.com`、MTU `1280`。
- systemd 服务及管理路径、固定 sing-box 版本和校验值。

安装时需要检查这些资源的冲突，不会为了迁就新机器而覆盖未知对象。仅自有 TUN 的接口参数会按需设置，例如 `rp_filter=2`，不改物理网卡及全局转发参数。配置主体保存在 `/etc/xq-user-proxy/`，其中 `settings.json` 记录授权用户与上游；不要只修改某一个文件后就假设其他配套设置会自动同步。

## 9. 已验证范围

便携包已通过离线身份、安全与配置测试，以及 sing-box 1.14.4 的配置检查。隔离测试网络已验证 owner 专属 DNS/TUN 访问限制、root/其他 UID 的普通 DNS/TCP/UDP 保持可用，以及其他 UID 访问私有入口被拒绝。模拟 TUN 消失后，目标用户仍受黑洞路由阻断，root 原路由和 DNS 保持可用。

这些测试不需要改动 Mico-system 正在运行的 TUN。尚未在第二台真实 VPS 完整执行安装，因此没有把软件包安装、该机 systemd 启动和实际代理出口宣称为已在新服务器验收。目标机器仍需按安装器结果及本指南的状态、HTTPS 检查完成验证。

修改源码或文档后，可在 WIKI 根目录重新生成部署包及 SHA256 校验文件：

```bash
python3 scripts/build-xq-user-tun.py
```

包内包含独立的 `DEPLOYMENT.md` 和 `CONTENTS.sha256`，不会打入当前服务器的配置、账号凭据或运行备份。
