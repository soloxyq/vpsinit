# US 风格开发环境配置记录

记录日期：2026-11-13（America/Los_Angeles）。目标是使用美式英语、洛杉矶时区，以及可明确验证的网络连接方式。

2026-11-14：`scripts/xq-proxy/` 的控制器已更新为与原机器安装版相同的本地 DNS 接管版本，不再在 ON 时改写 `/etc/resolv.conf`；说明见 [WSL 全流量代理脚本说明](scripts/xq-proxy/README.md)。

**另一台 WSL 请从 [WSL 从零复现指南](WSL-从零复现指南.md) 开始。** 它是当前按顺序执行的流程；历史记录用于理解变更和排错。已经安装本方案的原机器不要再次运行首次安装器。

| 文档 | 用途 |
| --- | --- |
| [WSL 从零复现指南](WSL-从零复现指南.md) | 新 WSL 的获取材料、前置检查、安装下载、用户及服务安装、ON/OFF、DNS 接管和完整重启验收 |
| [WSL 开发工具配置](WSL-开发工具配置.md) | 可选 Linux Node/npx、uvx、Codex、Claude Code、登录和 MCP 配置 |
| [WSL 全流量代理脚本说明](scripts/xq-proxy/README.md) | 配套文件清单、本地 DNS 透明接管、ON/OFF 顺序、conntrack 清理、依赖、检查命令、测试入口与已知限制 |
| [首次安装器](scripts/xq-proxy/install.py) | `--check` 只读检查，检查和安装都需 `sudo`；首次安装后保持 OFF，拒绝覆盖旧部署 |
| [核心下载校验器](scripts/xq-proxy/download-core.py) | 通过指定 Karing 代理下载固定版本 amd64 包并校验 SHA256，不安装 |
| [UDP 出口诊断](scripts/xq-proxy/check-udp.py) | 普通 UDP 的 STUN 出口查询，供新机 ON 状态验收使用，不修改网络 |
| [离线回归测试](scripts/xq-proxy/test_dns_reliability.py) | 临时文件和模拟命令层的控制器回归测试；无需 root、不联网 |
| [隔离命名空间测试](scripts/xq-proxy/tests/netns-check.py) | 需要 root，只在新建的临时网络命名空间中验证 DNS 接管、DNS 映射清理与防直连规则；不改宿主路由和 resolver（首次运行可能留下未启用的 `dummy0`，见指南第 7 节） |
| [当天操作记录](2026-11-13-操作记录.md) | 2026-11-13 实际执行的主要命令、最终配置、验证结果、备份位置和排错记录 |
| [再次复查报告](2026-11-13-复查报告.md) | 部署前复查：已解决的问题、当时的网络出口、启动方式建议及互操作检查标准更正 |
| [2026-11-13 ON 状态复查](2026-11-13-ON状态复查.md) | 初次部署（旧版 TUN DNS）后的 TCP/UDP 出口、no-proxy 测试和防直连检查；其中的 DNS 恢复改进已实施 |
| [WSL 全流量代理部署记录](WSL-全流量代理部署记录.md) | 已部署的 TUN、本地 DNS 接管与防直连规则；2026-11-14 DNS 故障修复与验收、完整启动默认 OFF、手动开关及恢复方法 |
| [WSL 全流量代理方案](WSL-全流量代理方案.md) | 部署前方案和前置检查记录；当前状态以部署记录为准 |
| [VPS 复现指南](VPS-复现指南.md) | 在另一台 Ubuntu/Debian VPS 上按顺序复现；已经排除 WSL 专用步骤 |
| [WSL 代理函数最终版](scripts/xq-proxy-wsl.bash) | 当前由 `.bashrc` 加载的 TUN 开关，与 `scripts/xq-proxy/proxy.bash` 相同；需配套控制器与服务 |

在另一台 VPS 上，先阅读 **VPS 复现指南**；需要复现 Codex、Context7 配置时，再参照当天操作记录。

记录没有包含密码、API Key、登录令牌或完整认证文件。示例中的占位符需要在新机器上自行填写；本机配置备份可能包含密钥，不要把这些备份直接作为 Wiki 附件传播。

`SHA256SUMS` 用于核对本目录文件的完整性，其中路径相对本目录，需在 `WIKI/WSL_TUN` 中执行 `sha256sum -c SHA256SUMS`。当前控制器已在原机器部署，完成隔离测试和宿主 DNS、HTTPS、重复开关等验收；原机器尚未实际新建 WSL 会话或完整重启，首次安装器和整套流程也尚未在另一台全新 WSL 上完整执行，目标机需要按指南完成实际安装和重启验收。

时区、语言和代理设置不会改变实际所在地，也不保证第三方账号的地区资格或风控结果。服务使用地区应以提供方的规则和真实使用情况为准。
