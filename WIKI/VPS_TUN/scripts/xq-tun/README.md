# Mico-system TUN 安装包

> 2026-11-14 更新：下文记录独立命名空间方案。当前已安装的 `xq_proxyon/off/proxystatus` 已升级为用户级入口，影响 xuqian 的全部宿主会话；局域网直连。请以[用户级代理说明](../xq-user-proxy/README.md)为准。`xq_tun run` 仍可用于独立命名空间。

目标：`Mico-system / 192.168.5.173`，应用用户 `xuqian (1006:1006)`，SOCKS5 上游 `192.168.5.34:4066`。原理与范围见 [隔离方案](../../VPS-TUN隔离方案.md)。

**当前状态：2026-11-13 已在宿主安装并完成自动验收，核心保持运行，开机自启未开启。** 用户调整执行权限后，之前的 sudo 认证阻碍已解除。完整结果和备份路径见 [部署记录](../../VPS-TUN部署记录.md)。文件不包含密码或其他凭据，也不修改 sudoers。

## 复现或重新安装

当前已安装，无需重复执行。需要重新安装时，在宿主机的普通终端运行：

```bash
sudo bash /home/xuqian/WIKI/scripts/xq-tun/install.sh
```

安装器会执行这些步骤：

1. 核对用户、TUN、systemd、必要工具及既有资源冲突。
2. 经指定 SOCKS5 代理下载官方 sing-box `1.14.4`，验证固定 SHA256，再运行 `sing-box check`。
3. 把宿主路由、策略规则、DNS、nftables 与转发参数保存到 `/var/backups/xq-tun-时间-随机后缀/`。
4. 安装 root 所有的配置、控制器和服务；只在 `xq-tun` 命名空间建立 TUN、路由和防漏规则。
5. 启动核心，运行自动验收：普通用户身份和权限、独立 DNS、忽略代理变量的 HTTPS、IPv6 阻断、停核心断网、恢复连接、宿主网络基线对比。

只有全部验收通过才输出 `Installation and verification completed`。失败时查看屏幕上的错误和备份目录；已建立的隔离 guard 会保留，不会把应用切回宿主直连。安装器不会升级系统软件包或自动开启开机启动。

重复安装会检查资源归属；有隔离应用运行时拒绝重新安装。相同版本的重复验收也会暂时停止、恢复核心，所以应先退出隔离应用。其他用户的宿主网络和现有 Docker 网络不属于本安装器的修改范围。

## 独立命名空间的交互环境

只想把本终端随后启动的程序放入独立环境时，执行：

```bash
xq_tun shell
```

看到 `[TUN]` 后运行程序，用 `exit` 返回原父 shell。此操作创建子 shell，里面的 `cd` 和新变量不会自动传回父 shell；已运行的程序不会迁移，后台程序仍属于原来的网络环境。

当前 `xq_proxyon/off` 已改成 **xuqian 全部宿主会话** 的用户级开关，不再用于进入/退出这层 shell。在独立环境内请用 `exit` 返回宿主，再管理用户级开关。两种模式的当前用法见[用户级说明](../xq-user-proxy/README.md)。

## 指定程序启动与服务管理

公共命令已从 `xq-tun` 改为 `xq_tun`，旧命令文件已备份并移除。只运行指定程序：

该公共入口仅允许 xuqian（UID1006）使用，不要在它前面再加 `sudo`；它会自行按需申请管理步骤。root 与其他用户直接调用会被拒绝，管理员仍可使用 root 控制器维护服务。权限边界与实测见[访问审计](../../VPS-TUN固定值与访问权限审计.md)。

```bash
xq_tun run claude
xq_tun run curl --disable --proxy '' --noproxy '*' https://api.ipify.org
```

已经在 TUN 内执行 `xq_tun run` 会直接以普通用户运行，不再次 sudo。`xq_tun shell` 仍可作为进入 TUN shell 的入口；在 TUN 内重复执行不再创建新一层。

服务管理在宿主终端执行：

```bash
xq_tun status
xq_tun start
xq_tun stop
```

这里的 `xq_tun stop` 仅停止独立命名空间核心，会使已进入该环境的应用断网；`xq_tun start` 后恢复新连接。单程序入口 `xq_tun run` 要求此核心已就绪。它与宿主用户级 `xq_proxyon/off` 使用不同服务，互不负责开启/关闭对方。隔离应用带 `no_new_privs`，所以服务管理需在宿主执行。

入口采用清洁环境，仅传递 HOME、PATH、语言、终端等必要变量；不会继承代理变量、API Key 环境变量、`SSH_AUTH_SOCK`、`XDG_RUNTIME_DIR` 等。依赖自定义环境变量的应用，应在隔离 shell 中按原有方式设置。HOME 和文件仍为同一用户的目录；这不是文件系统容器。交互 Bash 仍会读取用户自己的 `.bashrc`，不要让其中的自动化连接宿主已有 tmux/daemon 来代启动程序。

首期支持 IPv4 TCP 和经 DoH/SOCKS 的 DNS。普通 UDP 与 ICMP由配置拒绝，IPv6 公网被 guard 阻断。普通 UDP/ICMP 的实际数据测试未包含在当前自动验收中；需要 UDP 时应先验证上游能力再调整。

本次已在 `xuqian` 的 `.bashrc` 末尾加入受管理的 helper 加载块，覆盖旧版代理环境变量函数。其他用户的 shell 配置未改动。查看独立服务用 `xq_tun status`；宿主用户级状态用 `xq_proxystatus`。

开机自启保持关闭；需要时在宿主执行：

```bash
sudo systemctl enable xq-tun.service
```

## 检查与移除

查看日志：

```bash
sudo journalctl -u xq-tun.service -u xq-tun-netns.service -n 80 --no-pager
```

重新验收需先退出隔离应用，然后在宿主执行：

```bash
sudo /usr/bin/python3 -I /usr/local/lib/xq-tun/verify.py
```

验收与初次安装保存的宿主基线对比；如果期间管理员或 Docker 修改了宿主网络，也会报告差异，需检查快照，不能直接归因于 TUN。

停用并删除运行中的 namespace：先退出里面的应用，再执行：

```bash
xq_tun stop
sudo systemctl disable xq-tun.service
sudo systemctl stop xq-tun-netns.service
```

若 namespace 仍有应用，控制器会报告 PID 并拒绝删除；它不会强杀进程。停止成功后，安装文件保留供重用。彻底移除时仅删除本功能专属文件并 `systemctl daemon-reload`，保留备份供审计；不要清空宿主 nftables、路由或重启 Docker。

## 独立模式的历史验证

- 官方 `sing-box-1.14.4-linux-amd64.tar.gz` SHA256：`699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968`。来源：[官方发行资产](https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.14.4)。
- 使用该实际二进制执行本目录 `sing-box.json` 的 `sing-box check`，退出码 `0`。
- Bash、Python 及内嵌验收程序语法检查通过。
- 运行时的 11 项无特权测试覆盖拒绝错误命名空间、缺少核心、DNS 挂载失败、清理危险环境与降权参数。
- systemd 单元在临时替代执行路径下的静态检查退出码 `0`；执行沙箱有连接限制警告，这不等同于已在宿主启动服务。
- 安装器、控制器和验收程序完成独立复核。随后已在宿主完成真实的 TUN、DNS、停核心断网、恢复及宿主网络基线对照，全部通过；详见 [部署记录](../../VPS-TUN部署记录.md)。
- 早期终端子 shell 开关曾完成双终端测试，随后同名 `xq_proxyon/off` 已替换为用户级开关。当前独立模式使用 `xq_tun shell` / `exit`；指定程序入口在修复后再次实测成功。
