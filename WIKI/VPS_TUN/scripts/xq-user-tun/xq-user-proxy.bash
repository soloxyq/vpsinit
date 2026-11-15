# Generated for @USER@ (UID @UID@). Source this file from that user's ~/.bashrc.
# Loading helpers never starts a service or changes routing/DNS.
_xq_proxy_require_owner() {
  if (( EUID != @UID@ )); then
    printf '这些代理入口仅允许 @USER@（UID @UID@）使用。\n' >&2
    return 1
  fi
}

_xq_proxy_clear_env() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  unset all_proxy ALL_PROXY no_proxy NO_PROXY ftp_proxy FTP_PROXY
}

xq_proxyon() {
  _xq_proxy_require_owner || return 1
  if (( $# != 0 )); then
    printf '用法：xq_proxyon（开启 @USER@ 全部宿主会话的用户级 TUN）\n' >&2
    return 2
  fi
  if /usr/bin/sudo /usr/local/sbin/xq-user-proxyctl on; then
    _xq_proxy_clear_env
    local public_ip
    if public_ip=$(/usr/bin/curl --disable -4 --fail --silent --show-error \
      --proxy '' --noproxy '*' --connect-timeout 4 --max-time 12 https://api.ipify.org); then
      printf '公网出口 IP：%s\n' "$public_ip"
      return 0
    fi
    printf '公网出口查询失败；用户级防直连规则仍保持开启。\n' >&2
    return 1
  fi
  return 1
}

xq_proxyoff() {
  _xq_proxy_require_owner || return 1
  if (( $# != 0 )); then
    printf '用法：xq_proxyoff（关闭 @USER@ 全部宿主会话的用户级 TUN）\n' >&2
    return 2
  fi
  if /usr/bin/sudo /usr/local/sbin/xq-user-proxyctl off; then
    _xq_proxy_clear_env
    return 0
  fi
  return 1
}

xq_proxystatus() {
  _xq_proxy_require_owner || return 1
  if (( $# != 0 )); then
    printf '用法：xq_proxystatus\n' >&2
    return 2
  fi
  /usr/bin/sudo /usr/local/sbin/xq-user-proxyctl status
}
