# VPS 初始化与工具脚本

这是一个用于 Debian 12+ / Ubuntu 22.04+ VPS 的全能初始化脚本。它集成了系统安全配置、网络优化、环境安装以及常用的代理和测试工具。

## 特点

*   **交互式菜单**：简单易用的数字菜单。
*   **智能别名**：首次运行时自动创建 `xqvinit` 别名，指向脚本当前路径。
*   **安全加固**：SSH 密钥/端口配置、UFW 防火墙、Fail2ban、DNS 净化。
*   **改动可回滚**：修改 SSH、DNS 配置前先备份到 `/root/xqvinit-backup/`，校验失败自动恢复。
*   **一键集成**：集成 BBR、Docker、1Panel、VLESS 等常用脚本。

## 快速开始

### 1. 克隆仓库

```bash
cd /root
git clone https://github.com/soloxyq/vpsinit.git
cd vpsinit
```

### 2. 运行脚本

```bash
chmod +x vps_setup.sh
./vps_setup.sh
```

### 3. 使用别名

脚本首次运行后，会自动在您的 shell 配置文件 (`.bashrc` 或 `.zshrc`) 中添加别名。
重新登录或执行 `source ~/.bashrc` (或 `~/.zshrc`) 后，您可以在任意目录下输入以下命令启动脚本：

```bash
xqvinit
```

## 功能列表

1.  **配置 Root 密钥登录**
    *   交互式修改 SSH 端口 (默认保持当前端口)；端口被其他程序占用时拒绝修改。sshd 配置了多个端口时只保留输入的一个，会先提示。
    *   添加 SSH 公钥 (支持预置默认 Key)；写入前用 `ssh-keygen` 校验格式，同一把密钥不会重复添加。
    *   **默认 Key 是仓库作者 (soloxyq@foxmail.com) 的公钥**，脚本会显示其指纹；其他人使用时请粘贴自己的公钥。覆盖模式下使用默认 Key，或 `authorized_keys` 里只剩默认 Key 又要禁用密码时，需要二次确认。
    *   可选禁用密码登录：同时关闭键盘交互认证，root 改为仅允许密钥登录 (`PermitRootLogin prohibit-password`)。`authorized_keys` 中没有有效公钥时拒绝禁用；公钥都带 `command=`/`from=` 等限制时需要确认；其他配置让 `PermitRootLogin` 实际为 `no` 时撤销修改。
    *   重启前用 `sshd -t` 校验语法并核对生效端口，失败时自动恢复原 sshd 配置和 `authorized_keys`，并显示备份位置。
    *   兼容 Ubuntu 24.04+ 默认的 `ssh.socket` 端口监听；Ubuntu 22.10–23.10 的 `ssh.socket` 不读取 sshd_config 中的端口，脚本会拒绝改端口并提示改用 `systemctl edit ssh.socket`。
    *   UFW 已启用时先放行新端口，放行失败则撤销修改；Fail2ban 已由本脚本配置时同步监控端口。

2.  **安装 UFW 防火墙**
    *   自动识别并放行当前 SSH 端口：sshd 配置的端口、sshd 实际监听的端口，以及 `ssh.socket` 的监听端口。
    *   默认放行: 80, 443, 16790-16799 (TCP/UDP)。
    *   防止把自己锁在外面：任一 SSH 端口放行失败时不启用 UFW。

3.  **安装 Fail2ban**
    *   安装并启动 Fail2ban，防止 SSH 暴力破解。
    *   从 journald 读取 sshd 日志 (`backend = systemd`)：Debian 12 默认不安装 rsyslog，没有 `/var/log/auth.log`。

4.  **设置 Swap 内存**
    *   交互式创建或重建 `/swapfile`，可以调大也可以调小；其他 Swap 文件/分区保持不变。
    *   创建前检查磁盘空间 (至少预留 256MB)；启用成功后才写入 `/etc/fstab`，不会重复写入。

5.  **TCP/BBR 网络调优**
    *   集成 `Eric86777` 的高级 TCP 调优脚本。

6.  **系统综合测试 (NodeQuality)**
    *   集成 `NodeQuality` 脚本，测试 VPS 性能、流媒体解锁等。

7.  **安装 VLESS 代理服务**
    *   集成 `mozisen/surge` 的 `vless-server.sh` 多协议代理部署脚本，快速搭建 VLESS 等节点。
    *   与上游用法一致，脚本保存到 `/root/vless-server.sh` 后运行 (它会把自身路径写进 cron 定时任务)；安装完成后可用 `vless` 命令管理。

8.  **设置时区**
    *   一键将系统时区设置为 `Asia/Shanghai`。

9.  **安装 Docker 环境**
    *   使用官方脚本一键安装 Docker Engine。

10. **DNS 净化与安全加固**
    *   阻止 dhclient 用 DHCP 下发的 DNS 改写解析配置 (写入 `dhclient-enter-hooks.d` hook，并清理旧版本写入的无效 `ignore domain-name-servers;`)。
    *   禁用冲突的 `if-up.d/resolved` 脚本 (存在时)。
    *   注释 `/etc/network/interfaces` 及 `interfaces.d/` 中残留的 `dns-*` 配置。
    *   配置 `systemd-resolved` 使用 Google (8.8.8.8) 和 Cloudflare (1.1.1.1) DNS，启用 DoT。
    *   先用严格 DoT 验证解析 (`resolvectl query` 直接向上游查询，再经 `127.0.0.53` stub 只走 DNS 查一次，都不受 `/etc/hosts` 影响)；失败时 (例如 853 端口被封) 自动降级为 opportunistic，仍失败则恢复原配置。
    *   Debian 12 上安装 systemd-resolved 会卸载 `resolvconf` 等冲突软件包，脚本会先列出并要求确认；回滚只恢复配置文件，不会重装软件包，但会保证 `/etc/resolv.conf` 仍有修改前的 DNS 内容。
    *   Ubuntu 上由 netplan/systemd-networkd 下发的网卡 DNS 不在处理范围内，脚本结束时会列出这些网卡。

11. **安装 1Panel 服务器面板**
    *   快速部署 1Panel 现代化运维面板；安装包在临时目录中下载解压，不会留在当前目录。

12. **安装 NextTrace 路由追踪**
    *   安装 `nxtrace` 工具，可视化路由追踪。

13. **安装哪吒探针 Agent**
    *   使用默认面板配置，或自定义服务器地址、密钥和 TLS。**默认面板是仓库作者的哪吒面板**，其他人请选择自定义配置。

## 第三方脚本

第 5、6、7、9、11、12、13 项会运行第三方脚本。脚本先通过 HTTPS (含跳转) 完整下载再执行 (第 7 项保存到 `/root/vless-server.sh`，其余为临时文件)：下载失败或返回错误页时不会执行任何内容，网络中断也不会执行下载了一半的脚本；下载卡住 (60 秒内低于 1KB/s) 会自动放弃，按 Ctrl-C 中断时会清理临时文件并回到菜单。脚本内容仍由第三方维护，运行前请确认来源可信。

## 兼容性

*   **操作系统**: Debian 12+ (Bookworm) 或 Ubuntu 22.04+ (Jammy)
*   **用户**: 必须以 `root` 用户运行。
