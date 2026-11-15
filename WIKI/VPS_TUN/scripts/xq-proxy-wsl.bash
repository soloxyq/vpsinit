# WSL-wide proxy controls. Source from ~/.bashrc.
_xq_proxy_clear_env() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
}

_xq_proxy_public_ip() {
  local query_url public_ip
  for query_url in https://api.ipify.org https://icanhazip.com; do
    if public_ip="$(command curl --disable -4 --silent --fail --connect-timeout 3 --max-time 8 "$query_url" 2>/dev/null)" &&
      [[ "$public_ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
      printf '公网出口 IP：%s\n' "$public_ip"
      return 0
    fi
  done
  printf '公网出口 IP：获取失败，请检查隧道或上游代理。\n' >&2
  return 1
}

xq_proxyon() {
  if (( $# )); then
    printf '用法：xq_proxyon（使用 Karing 全代理端口 4066）\n' >&2
    return 2
  fi
  if sudo /usr/local/sbin/xq-proxyctl on; then
    _xq_proxy_clear_env
    _xq_proxy_public_ip
  else
    return 1
  fi
}

xq_proxyoff() {
  if (( $# )); then return 2; fi
  if sudo /usr/local/sbin/xq-proxyctl off; then
    _xq_proxy_clear_env
    _xq_proxy_public_ip
  else
    return 1
  fi
}

xq_proxystatus() {
  sudo /usr/local/sbin/xq-proxyctl status
}

# Discard legacy per-process proxy URLs after reloading a shell while TUN mode is ON.
if [[ -r /run/xq-proxy-enabled ]]; then
  _xq_proxy_clear_env
fi
