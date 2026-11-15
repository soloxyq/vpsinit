#!/usr/bin/env bash
# 2026-11-13: exact final proxy functions exported from ~/.bashrc.
# Source this file from Bash; it does not enable the proxy automatically.
# WSL NAT only: the default gateway is the Windows proxy host.
# On a normal VPS, configure an explicit proxy endpoint instead.

_xq_proxy_host_ip() {
  ip -4 route show default 2>/dev/null |
    awk '{for (i = 1; i < NF; i++) if ($i == "via") {print $(i + 1); exit}}'
}

_xq_proxy_status() {
  local mode="$1" proxy_url="${2:-}"
  local host_ip local_ip address proxy_ip proxy_port lookup public_ip peer_ip query_url

  host_ip="$(_xq_proxy_host_ip)"
  local_ip="$(ip -4 route get 1.1.1.1 2>/dev/null |
    awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')"

  if [[ "$mode" == on ]]; then
    printf '代理状态：已开启（环境变量）\n'
  else
    printf '代理状态：已关闭（直连）\n'
  fi
  printf '当前 WSL IP：%s\n' "${local_ip:-无法获取}"
  printf 'Windows 宿主机 IP（WSL 网关）：%s\n' "${host_ip:-无法获取}"

  if [[ -n "$proxy_url" ]]; then
    # 仅显示地址和端口，避免输出 URL 中可能存在的认证信息。
    address="${proxy_url#*://}"
    address="${address%%/*}"
    address="${address##*@}"
    proxy_ip="${address%:*}"
    proxy_port="${address##*:}"
    [[ "$address" == *:* ]] || proxy_port='未指定'
  else
    proxy_ip="${host_ip:-无法获取}"
    proxy_port='16791（默认，未启用）'
  fi
  if [[ "$mode" == off && -n "$proxy_url" ]]; then
    printf '原代理 IP（已关闭）：%s\n原代理端口：%s\n' "$proxy_ip" "$proxy_port"
  else
    printf '代理 IP：%s\n代理端口：%s\n' "$proxy_ip" "$proxy_port"
  fi

  if ! command -v curl >/dev/null 2>&1; then
    printf '公网出口 IP：无法查询（未安装 curl）\n'
    return 0
  fi

  # 使用刚切换的环境变量查询；主服务失败时回退，每个服务最多等待 8 秒。
  for query_url in https://api.ipify.org https://icanhazip.com; do
    if lookup="$(command curl --disable -4 --fail --silent \
      --connect-timeout 3 --max-time 8 --write-out '\n%{remote_ip}' \
      --url "$query_url" 2>/dev/null)"; then
      public_ip="${lookup%%$'\n'*}"
      peer_ip="${lookup##*$'\n'}"
      if [[ "$public_ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
        printf '公网出口 IP：%s\n' "$public_ip"
        if [[ "$mode" == off ]]; then
          printf '连接验证：直连查询成功\n'
        elif [[ "$peer_ip" == "$proxy_ip" ]]; then
          printf '连接验证：通过代理查询成功\n'
        else
          printf '连接验证：查询成功，但连接对端与代理 IP 不一致\n'
        fi
        return 0
      fi
    fi
  done

  printf '公网出口 IP：获取失败（当前连接不可达或查询服务不可用）\n'
  printf '环境变量已切换；公网连接未验证通过。\n'
  return 0
}

xq_proxyon() {
  local port="${1:-16791}" host_ip
  if (( $# > 1 )) || [[ ! "$port" =~ ^0*[0-9]{1,5}$ ]] ||
    (( 10#$port < 1 || 10#$port > 65535 )); then
    printf '用法：xq_proxyon [端口]，端口必须为 1–65535。\n' >&2
    return 2
  fi
  port=$((10#$port))
  host_ip="$(_xq_proxy_host_ip)"
  if [[ -z "$host_ip" ]]; then
    printf '无法获取 Windows 宿主机的 WSL 网关地址，代理设置未修改。\n' >&2
    return 1
  fi

  export TZ="America/Los_Angeles"

  export WIN_HOST="$host_ip"
  export http_proxy="http://${WIN_HOST}:${port}"
  export https_proxy="http://${WIN_HOST}:${port}"
  
  export HTTP_PROXY="$http_proxy"
  export HTTPS_PROXY="$https_proxy"
  export all_proxy="$http_proxy"
  export ALL_PROXY="$http_proxy"

  export no_proxy="127.0.0.1,localhost,${WIN_HOST},::1,192.168.0.0/16,10.0.0.0/8"
  export NO_PROXY="$no_proxy"
  _xq_proxy_status on "$http_proxy"
}

xq_proxyoff() {
  local previous_proxy="${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-${all_proxy:-${ALL_PROXY:-}}}}}}"
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  unset all_proxy ALL_PROXY
  unset no_proxy NO_PROXY
  _xq_proxy_status off "$previous_proxy"
}
