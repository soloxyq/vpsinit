# WSL 全流量代理

本目录对应 WSL 中的 `xq-proxy.service`，作用于当前 WSL 网络命名空间中的全部普通程序。它与另一个 VPS 使用的用户级 `xq-user-proxy`、独立命名空间 `xq-tun` 不同，不能混用服务或控制器。

2026-11-14 20:01 DNS 修复已部署，隔离测试和宿主 DNS、HTTPS、重复开关、核心停止、resolver 重建模拟验收通过，最终保持 ON。实际新建 WSL 会话及完整发行版重启尚未执行，详见[部署记录](../../WSL-全流量代理部署记录.md)。本次以已安装的新版 `/usr/local/sbin/xq-proxyctl` 为基线同步归档，保留现场已有的 DNS 恢复校验、完整状态检查和每次 WSL 启动默认 OFF 的行为。

新 WSL 的安装入口在 [WSL_TUN/scripts/xq-proxy](../../../WSL_TUN/scripts/xq-proxy/README.md)：那里的首次安装器 `install.py` 按 [WSL 从零复现指南](../../../WSL_TUN/WSL-从零复现指南.md) 安装同一版本控制器、两个 unit 和 `proxy.bash`。本目录保留相同的控制器与隔离测试，供 VPS_TUN 文档引用，不单独作为安装入口。

## 使用

```bash
xq_proxyon
xq_proxystatus
xq_proxyoff
```

明确的控制器入口为：

```bash
sudo /usr/local/sbin/xq-proxyctl on
sudo /usr/local/sbin/xq-proxyctl status
sudo /usr/local/sbin/xq-proxyctl off
```

完整关闭必须使用 `off`。单独停止核心会留下防直连规则，普通程序不会自动恢复公网直连。`xq-proxy-boot.service` 使用 `boot-off`，每次发行版启动都先恢复 OFF；它不再自动开启上次的 ON 状态。

## DNS 修复

旧实现开启代理时把 `/etc/resolv.conf` 写成 TUN DNS，但 WSL 新建会话可能将其重新链接到 WSL DNS。后者走 loopback，命中防直连规则，于是核心仍运行、网站却无法解析。

修复版保留 WSL 自动 DNS 和原 resolver 链接，控制器不再在每次 attach 时改写该文件。ON 时，自有 nftables 规则将应用 IPv4 TCP/UDP 53 查询转交本地 `127.0.0.1:1053`，sing-box 通过既有 Karing SOCKS5 上游发起 DoH 查询。普通 IPv4 TCP/UDP 仍走 TUN；IPv6 保持明确阻断。

DNS 使用专用 conntrack zone `20262` 和标记位 `0x02000000`。OFF 先停止新建 DNS 改写、保留 guard，再停止核心并精确清理本功能的 DNS 映射，最后移除自有路由和 guard，恢复 Windows DNS。专用核心 UID 仅不参与应用 DNS 改写，没有任意公网直连权限。

依赖：Python 3、systemd、iproute2、nftables、`conntrack`、sing-box `1.14.4`。本次已在本机安装 conntrack 及其库依赖。这是本机配套文件归档，不是独立的一键安装器；复制到其他 WSL 前需核对账号、端口占用、网关、保留路由与 conntrack 资源冲突。

## 检查

状态检查会区分配置完整性与有时间限制的系统默认 DNS 探测，不再仅凭 resolver 是否为链接来判定正常与否。

```bash
sudo /usr/local/sbin/xq-proxyctl status
sudo journalctl -u xq-proxy.service -u xq-proxy-boot.service -n 80 --no-pager
sudo journalctl -t xq-proxyctl -n 80 --no-pager
sudo nft list table inet xq_proxy
```

`xq-proxyctl` 标签包含启停结果、默认 DNS 探测失败及控制器异常，核心连接日志仍在服务 journal 中。

隔离规则测试只允许在新建的临时网络命名空间运行，不能用它替代宿主 ON/OFF 与新会话验收。在本目录运行；首次运行可能在宿主留下一个未启用、无地址的 `dummy0`，原本没有时可用 `sudo ip link del dummy0` 删除：

```bash
sudo unshare --net python3 -I tests/netns-check.py
```

不要通过放开非 TUN DNS、全局清空 nftables 或清空全机 conntrack 来解决异常。OFF 清理范围仅为本功能拥有的资源。
