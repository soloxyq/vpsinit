# vpsinit

自用服务器和自建服务的脚本、源码与部署记录。每个主题一份文档或一个目录，这里是入口。

| 文档 | 内容 |
| --- | --- |
| [vpsinit.md](vpsinit.md) | VPS 初始化脚本 `vps_setup.sh`，适用于 Debian 12+ / Ubuntu 22.04+：用法和 13 项功能的说明，包括 Root 密钥登录、UFW、Fail2ban、Swap、BBR、Docker、DNS 加固等 |
| [email.md](email.md) | 个人域名邮箱：用 MoeMail 和 Cloudflare 搭的网页邮箱。工作原理、日常使用、更新部署、换机器恢复和从零重建；源码在 `moemail/` |
| [WIKI/VPS_TUN/](WIKI/VPS_TUN/README.md) | Linux 主机上的用户级 TUN 代理：一键部署、便携安装包、验收和排错记录；也收着一份和 WSL_TUN 相同的 WSL 全流量代理部署记录，新装 WSL 看 WSL_TUN |
| [WIKI/WSL_TUN/](WIKI/WSL_TUN/README.md) | WSL 全流量代理：从零复现指南、开发工具配置和配套脚本 |

## VPS 初始化脚本：快速开始

用 root 登录 VPS，执行：

```bash
cd /root
git clone https://github.com/soloxyq/vpsinit.git
cd vpsinit
chmod +x vps_setup.sh
./vps_setup.sh
```

首次运行后会添加别名 `xqvinit`，重新登录后在任意目录输入它就能启动脚本。

运行前先读 [vpsinit.md](vpsinit.md)，尤其是这几处：

- 第 1 项“配置 Root 密钥登录”的**默认公钥是仓库作者的**，别人使用时要换成自己的公钥。
- 第 13 项“安装哪吒探针 Agent”的**默认面板是仓库作者的**，别人使用时要选自定义配置。
- 有 7 项会下载并运行第三方脚本，见 vpsinit.md 的“第三方脚本”一节。
