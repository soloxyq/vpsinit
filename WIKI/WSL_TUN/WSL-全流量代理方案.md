# WSL 全流量代理：方案与前置检查

记录日期：2026-11-13。本页保留部署前的方案讨论；用户随后授权并完成部署，当前状态及操作方法见 [部署记录](WSL-全流量代理部署记录.md)。另一台 WSL 请按 [从零复现指南](../WSL_TUN/WSL-从零复现指南.md) 操作；本页下文的“尚未部署”均为历史描述，不能当作当前实施状态。

## 已确认

- Windows 端使用 Karing。
- WSL 实际网络模式为 NAT。
- 实际运行环境存在 `/dev/net/tun` 字符设备；工具沙箱中不可见不代表主机不存在。
- 对当前 Windows 网关 `172.21.32.1:16791` 仅执行了 SOCKS5 无认证握手，响应 `0500`，确认该入口支持 SOCKS5。
- 这次未发送 SOCKS 目标请求，未执行公网直连测试，也未运行 Windows 程序。
- SOCKS 握手不证明 UDP 可用，也不证明该端口所有目标都经代理节点转发。
- 用户随后确认 Karing 的全代理端口是 `4066`。已验证 `172.21.32.1:4066` 的 SOCKS5 无认证握手成功，UDP ASSOCIATE 协商返回成功，给出宿主机上的临时 UDP 中继端口；没有发送公网 UDP 数据，尚不能据此保证端到端 UDP 可用。

## 更符合当前需求的方案

在 WSL 内运行 TUN 代理核心（例如 sing-box），配合 DNS 配置和独立防火墙规则，再由 `xq_proxyon/off` 控制。公网连接路径为：WSL 程序 → WSL TUN → Karing 全代理端口 4066 → 所选节点。宿主机地址在启动时读取，不固定依赖本次的 172.21.32.1。

ON 的目标行为：

- 接管整个 WSL 发行版的普通应用公网流量，不依赖应用是否读取 HTTP_PROXY。
- DNS 也通过选定代理路径；不能直接沿用 WSL 的虚拟化 DNS 通道并假设它已被 TUN 接管。
- UDP/IPv6 能支持时纳入转发；不能支持时明确阻断，不能静默改为直连。
- 代理核心停止或上游故障时，独立防火墙仍阻止公网直连。仅设置 strict_route 不能当作完整的故障断网保护。
- 保留 loopback、连接 Karing 本身及维持本地网络所需的明确例外，避免代理递归。

OFF 的目标行为：停止接管，并恢复启用前保存的路由、DNS和防火墙设置。它将影响整个 WSL，而不再只是当前终端。

这属于网络层控制，普通程序的 `--noproxy` 等参数不会移除路由或防火墙规则。具有管理员权限并修改这些规则的程序不在这个保证内。

## 尚待确认

Karing 的“设置 → 端口”区分规则、全代理和全直连入口。用户确认本机全代理端口为 4066；不再用未确认模式的 16791 作为新方案的上游，也不套用官方教程中的示例默认端口。还需在实际部署前验证端到端 UDP、DNS 接管及代理故障时的阻断行为。

当前 `xq_proxyon/off` 仍是原先的环境变量开关，尚未改造成网络层开关，也尚未切换其默认端口。本页记录可行性与目标行为，不表示已实现全流量代理。

## 为什么不直接改 Windows TUN

Karing 官方支持 Windows TUN，需管理员启动。但 Windows TUN 是否完整接管 WSL 流量还要验证，且它的开启/关闭不等于 Linux `xq_proxyon/off` 的开关。WSL 内单独实现更便于保留 Linux 开关语义，也无需从 WSL 启动 Windows 程序。

来源：[Karing 端口共享](https://karing.app/en/tutorial/lan)、[Karing 设置](https://karing.app/app-manual/settings)、[sing-box TUN](https://sing-box.sagernet.org/configuration/inbound/tun/)、[SOCKS 出站](https://sing-box.sagernet.org/configuration/outbound/socks/)。
