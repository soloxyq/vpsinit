# VPS 初始化与工具脚本

这是一个用于 Debian/Ubuntu VPS 的全能初始化脚本。它集成了系统安全配置、网络优化、环境安装以及常用的代理和测试工具。

## 特点

*   **交互式菜单**：简单易用的数字菜单。
*   **智能别名**：首次运行时自动创建 `xqvinit` 别名，指向脚本当前路径。
*   **安全加固**：SSH 密钥/端口配置、UFW 防火墙、Fail2ban、DNS 净化。
*   **一键集成**：集成 BBR、Docker、1Panel、VLESS 等常用脚本。

## 快速开始

### 1. 克隆仓库

```bash
cd /root
git clone https://github.com/YourUsername/vpsinit.git
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
    *   交互式修改 SSH 端口 (默认 22)。
    *   添加 SSH 公钥 (支持预置默认 Key)。
    *   可选禁用密码登录，提高安全性。

2.  **安装 UFW 防火墙**
    *   自动识别并放行当前 SSH 端口。
    *   默认放行: 80, 443, 16790-16799 (TCP/UDP)。
    *   防止把自己锁在外面。

3.  **安装 Fail2ban**
    *   安装并启动 Fail2ban，防止 SSH 暴力破解。

4.  **设置 Swap 内存**
    *   交互式创建 Swap 文件。
    *   自动写入 `/etc/fstab` 实现开机挂载。

5.  **TCP/BBR 网络调优**
    *   集成 `Eric86777` 的高级 TCP 调优脚本。

6.  **系统综合测试 (NodeQuality)**
    *   集成 `NodeQuality` 脚本，测试 VPS 性能、流媒体解锁等。

7.  **安装 VLESS 代理服务**
    *   集成 `Chil30/vless-all-in-one` 脚本，快速搭建 VLESS 节点。

8.  **设置时区**
    *   一键将系统时区设置为 `Asia/Shanghai`。

9.  **安装 Docker 环境**
    *   使用官方脚本一键安装 Docker Engine。

10. **DNS 净化与安全加固**
    *   修正 `dhclient` 配置。
    *   禁用冲突的 `if-up.d` 脚本。
    *   清理 `/etc/network/interfaces` 中的残留 DNS。
    *   配置 `systemd-resolved` 使用 Google (8.8.8.8) 和 Cloudflare (1.1.1.1) DNS，启用 DoT。

11. **安装 1Panel 服务器面板**
    *   快速部署 1Panel 现代化运维面板。

12. **安装 NextTrace 路由追踪**
    *   安装 `nxtrace` 工具，可视化路由追踪。

## 兼容性

*   **操作系统**: Debian 10+, Ubuntu 20.04+
*   **用户**: 必须以 `root` 用户运行。