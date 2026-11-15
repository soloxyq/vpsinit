# Source from ~/.bashrc after legacy proxy functions. This file defines helpers;
# it never starts a service merely by being sourced.
_xq_tun_in_namespace() {
  [[ /proc/self/ns/net -ef /run/netns/xq-tun ]]
}

_xq_tun_clear_proxy_env() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  unset all_proxy ALL_PROXY no_proxy NO_PROXY ftp_proxy FTP_PROXY
}

_xq_proxy_require_owner() {
  if (( EUID != 1006 )); then
    printf '这些代理入口仅允许 xuqian（UID 1006）使用。\n' >&2
    return 1
  fi
}

_xq_tun_prompt() {
  if [[ $- == *i* ]] && _xq_tun_in_namespace; then
    case "${PS1-}" in
      '[TUN] '*) ;;
      *) PS1="[TUN] ${PS1-\u@\h:\w\$ }" ;;
    esac
  fi
}

xq_tun() {
  /usr/local/bin/xq_tun "$@"
}

xq_proxyon() {
  _xq_proxy_require_owner || return 1
  if (( $# != 0 )); then
    printf '用法：xq_proxyon（开启 xuqian 全部宿主会话的用户级 TUN）\n' >&2
    return 2
  fi
  if _xq_tun_in_namespace; then
    printf '当前是独立 xq_tun 环境；请先 exit 回到宿主，再管理用户级开关。\n' >&2
    return 2
  fi
  if /usr/bin/sudo /usr/local/sbin/xq-user-proxyctl on; then
    _xq_tun_clear_proxy_env
    local public_ip
    if public_ip=$(/usr/bin/curl --disable -4 --fail --silent --show-error \
      --proxy '' --noproxy '*' --connect-timeout 4 --max-time 12 https://api.ipify.org); then
      printf '公网出口 IP：%s\n' "$public_ip"
    else
      printf '公网出口查询失败；用户级防直连规则仍保持开启。\n' >&2
      return 1
    fi
    return 0
  fi
  return 1
}

xq_proxyoff() {
  _xq_proxy_require_owner || return 1
  if (( $# != 0 )); then
    printf '用法：xq_proxyoff（关闭 xuqian 全部宿主会话的用户级 TUN）\n' >&2
    return 2
  fi
  if _xq_tun_in_namespace; then
    printf '当前是独立 xq_tun 环境；请先 exit 回到宿主，再管理用户级开关。\n' >&2
    return 2
  fi
  if /usr/bin/sudo /usr/local/sbin/xq-user-proxyctl off; then
    _xq_tun_clear_proxy_env
    return 0
  fi
  return 1
}

xq_proxystatus() {
  _xq_proxy_require_owner || return 1
  if (( $# != 0 )); then return 2; fi
  if _xq_tun_in_namespace; then
    /usr/local/bin/xq_tun status
  else
    /usr/bin/sudo /usr/local/sbin/xq-user-proxyctl status
  fi
}

# Nested interactive Bash shells get the same visible network indicator, but
# do not inherit the entry shell's permission to return to its host parent.
if _xq_tun_in_namespace; then
  _xq_tun_clear_proxy_env
  _xq_tun_prompt
fi
