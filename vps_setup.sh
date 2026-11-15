#!/bin/bash

# ====================================================
#       VPS 初始化与工具脚本 (Debian 12+ / Ubuntu 22.04+)
# ====================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
SKYBLUE='\033[0;36m'
PLAIN='\033[0m'

# 修改 SSH / DNS 配置前，原文件按原路径结构备份到这里
BACKUP_ROOT="/root/xqvinit-backup"
# DNS 净化写入的 dhclient hook
DHCP_DNS_HOOK="/etc/dhcp/dhclient-enter-hooks.d/00-xqvinit-ignore-dns"
# 验证 DNS 是否可用时解析的域名（任一成功即可）
DNS_TEST_DOMAINS="github.com deb.debian.org"

# 日志函数
log_info() { echo -e "${SKYBLUE}[信息]${PLAIN} $1"; }
log_success() { echo -e "${GREEN}[成功]${PLAIN} $1"; }
log_warn() { echo -e "${YELLOW}[警告]${PLAIN} $1"; }
log_err() { echo -e "${RED}[错误]${PLAIN} $1"; }

# 检查是否为 root 用户
if [[ $EUID -ne 0 ]]; then
    log_err "必须使用 root 用户运行此脚本！"
    exit 1
fi

# 0. 基础依赖检查
check_dependencies() {
    local dependencies=("curl" "wget" "grep" "awk" "sed")
    local missing=()

    for dep in "${dependencies[@]}"; do
        if ! command -v "$dep" >/dev/null 2>&1; then
            missing+=("$dep")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        log_info "正在安装缺失的依赖: ${missing[*]} ..."
        apt update -y && apt install -y "${missing[@]}"
    fi
}

# 系统检测 (推荐 Debian 12+ / Ubuntu 22.04+)
check_sys_version() {
    local version_warning=0
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" != "debian" && "$ID" != "ubuntu" ]]; then
            log_warn "检测到系统为 $ID，脚本主要针对 Debian/Ubuntu 设计。"
            version_warning=1
        else
            local version_id_num=$(echo "$VERSION_ID" | cut -d. -f1)
            if [[ "$ID" == "debian" && "$version_id_num" -lt 12 ]]; then
                log_warn "推荐 Debian 12+，当前为 $VERSION_ID，部分功能可能失效。"
                version_warning=1
            elif [[ "$ID" == "ubuntu" && "$version_id_num" -lt 22 ]]; then
                log_warn "推荐 Ubuntu 22.04+，当前为 $VERSION_ID，部分功能可能失效。"
                version_warning=1
            fi
        fi
    else
        log_warn "无法检测操作系统版本。"
        version_warning=1
    fi

    if [[ "$version_warning" -eq 1 ]]; then
        read -p "是否强制继续运行? [y/N]: " confirm
        [[ ! "$confirm" =~ ^[Yy]$ ]] && exit 1
    else
        log_success "系统环境兼容: $PRETTY_NAME"
    fi
}

# ---------------- 通用工具 ----------------

# 新建带时间戳的备份目录，输出其路径
make_backup_dir() {
    local dir
    dir="$BACKUP_ROOT/$1-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$dir" && chmod 700 "$BACKUP_ROOT" "$dir" && echo "$dir"
}

# 按原路径结构备份文件或目录；符号链接保存链接本身，不存在的路径跳过
backup_paths() {
    local dir="$1" path
    shift
    for path in "$@"; do
        if [ -e "$path" ] || [ -L "$path" ]; then
            cp -a --parents "$path" "$dir/"
        fi
    done
}

# 用备份覆盖回原位置；备份里没有的路径保持不动
restore_paths() {
    local dir="$1" path
    shift
    for path in "$@"; do
        if [ -e "$dir$path" ] || [ -L "$dir$path" ]; then
            rm -rf "$path"
            cp -a "$dir$path" "$path"
        fi
    done
}

# 通过 HTTPS（含跳转）把 URL 完整下载到指定文件；HTTP 错误、下载中断或内容为空都算失败。
# 连接后 60 秒内平均速度低于 1KB/s 视为卡住并放弃，避免无限等待。
download_https() {
    local url="$1" dest="$2"
    if ! curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 15 \
            --speed-limit 1024 --speed-time 60 -o "$dest" "$url" \
            || [ ! -s "$dest" ]; then
        log_err "下载失败: $url"
        return 1
    fi
}

# 先把远程脚本完整下载到临时文件再执行：
# 下载失败或返回错误页时不执行任何内容，网络中断也不会执行半截脚本，交互式脚本仍从终端读取输入。
# 用法: run_remote_script [--in-tmpdir] URL [参数...]
#   --in-tmpdir  在临时目录里执行，供会在当前目录落地文件的脚本使用，结束后一并清理
run_remote_script() {
    local in_tmpdir=0
    if [[ "$1" == "--in-tmpdir" ]]; then
        in_tmpdir=1
        shift
    fi
    local url="$1"
    shift
    local tmp_dir rc
    tmp_dir=$(mktemp -d) || { log_err "无法创建临时目录。"; return 1; }
    # Ctrl-C 中断下载或安装脚本时也清理临时目录，然后回到菜单
    trap 'rm -rf "$tmp_dir"' INT TERM
    if ! download_https "$url" "$tmp_dir/script.sh"; then
        trap - INT TERM
        rm -rf "$tmp_dir"
        return 1
    fi
    if (( in_tmpdir )); then
        (cd "$tmp_dir" && bash ./script.sh "$@")
    else
        bash "$tmp_dir/script.sh" "$@"
    fi
    rc=$?
    trap - INT TERM
    rm -rf "$tmp_dir"
    return $rc
}

# ---------------- SSH 工具 ----------------

# 读取 sshd 实际生效的配置项，每个值一行（Port 可能有多行）。
# socket 激活且 sshd 还没启动过时 /run/sshd 可能不存在，sshd -t/-T 会因此报错，先补上。
sshd_effective() {
    command -v sshd >/dev/null 2>&1 || return 0
    mkdir -p /run/sshd
    sshd -T 2>/dev/null | awk -v key="$1" '$1 == key { $1 = ""; sub(/^ /, ""); print }'
}

# sshd 配置的全部端口（空格分隔），读取失败时按 22 处理
get_ssh_ports() {
    local ports
    ports=$(sshd_effective port | sort -un | paste -sd ' ')
    echo "${ports:-22}"
}

# SSH 实际可能在用的全部端口（空格分隔），供防火墙放行和 Fail2ban 监控：sshd 配置的 Port、
# sshd 正在监听的端口，以及 ssh.socket 的监听地址（Ubuntu 上可能被 systemctl edit ssh.socket 单独改过）
get_ssh_listen_ports() {
    local ports main_pid
    # 只认 sshd 主进程的监听：OpenSSH 9.8 之前每个会话进程也叫 sshd，它们持有 X11 转发（6010+）
    # 和 ssh -R 的监听端口，不能当成 SSH 端口放行；回环地址也不需要防火墙规则
    main_pid=$(systemctl show -p MainPID --value ssh.service 2>/dev/null)
    [[ "$main_pid" =~ ^[1-9][0-9]*$ ]] || main_pid=$(systemctl show -p MainPID --value sshd.service 2>/dev/null)
    ports=$({
        sshd_effective port
        if [[ "$main_pid" =~ ^[1-9][0-9]*$ ]]; then
            ss -Hltnp 2>/dev/null | awk -v pid="pid=$main_pid," 'index($0, pid) && $4 !~ /^(127\.|\[::1\])/ {
                n = split($4, a, ":"); print a[n] }'
        fi
        if systemctl is-active --quiet ssh.socket 2>/dev/null; then
            systemctl show -p Listen --value ssh.socket 2>/dev/null | grep -oE ':[0-9]+ \(' | grep -oE '[0-9]+'
        fi
    } | grep -E '^[0-9]+$' | sort -un | paste -sd ' ')
    echo "${ports:-22}"
}

# 设置 sshd 端口。Port 可以出现多次且全部生效，所以先删掉主配置和 sshd_config.d 中已有的 Port 行；
# 新的 Port 写在主配置第一个 Match 块之前（写在 Match 之后会被当成 Match 内的配置，sshd 拒绝启动）。
sshd_set_port() {
    local conf="$1" port="$2" dropin_dir="$3" tmp rc
    sed -i -E '/^[[:space:]]*#?Port[[:space:]]/Id' "$conf" || return 1
    if [ -d "$dropin_dir" ]; then
        find "$dropin_dir" -maxdepth 1 -type f -name '*.conf' \
            -exec sed -i -E '/^[[:space:]]*Port[[:space:]]/Id' {} +
    fi
    tmp=$(mktemp) || return 1
    awk -v line="Port $port" '
        !done && tolower($0) ~ /^[ \t]*match[ \t]/ { print line; done = 1 }
        { print }
        END { if (!done) print line }
    ' "$conf" > "$tmp" && cat "$tmp" > "$conf"
    rc=$?
    rm -f "$tmp"
    return $rc
}

# 追加公钥；同一把密钥（按 base64 主体判断，不看注释）已存在时返回 1
append_authorized_key() {
    local file="$1" key="$2" blob
    blob=$(awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^AAAA/) { print $i; exit } }' <<<"$key")
    if [ -n "$blob" ] && grep -qF -- "$blob" "$file" 2>/dev/null; then
        return 1
    fi
    # 文件末尾没有换行时先补一个，否则新密钥会接在上一行末尾，两把都失效
    if [ -s "$file" ] && [ -n "$(tail -c 1 "$file")" ]; then
        echo >> "$file"
    fi
    printf '%s\n' "$key" >> "$file"
}

# authorized_keys 中是否有不带选项的有效公钥。带 command=、from= 等选项的公钥可能无法正常登录
# （例如云镜像给 root 写入的 "Please login as the user ..." 强制命令）
has_unrestricted_key() {
    local file="$1" line
    [ -f "$file" ] || return 1
    # 最后一行可能没有换行；sshd 也接受行首空白
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line#"${line%%[![:space:]]*}"}
        case "$line" in
            ssh-*|ecdsa-*|sk-*)
                printf '%s\n' "$line" | ssh-keygen -lf - >/dev/null 2>&1 && return 0 ;;
        esac
    done < "$file"
    return 1
}

# authorized_keys 中的有效公钥是否只有给定的那一把（按 base64 主体比较）
only_this_key() {
    local file="$1" key_blob blobs
    key_blob=$(awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^AAAA/) { print $i; exit } }' <<<"$2")
    blobs=$(awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^AAAA/) { print $i; break } }' "$file" 2>/dev/null | sort -u)
    [ -n "$key_blob" ] && [ "$blobs" = "$key_blob" ]
}

# 撤销 setup_ssh_key 的修改：恢复 sshd 配置和 authorized_keys（本次才新建的 authorized_keys 直接删除）
ssh_rollback() {
    local backup_dir="$1" auth_file="$2" auth_existed="$3"
    restore_paths "$backup_dir" /etc/ssh/sshd_config /etc/ssh/sshd_config.d
    if [[ "$auth_existed" == "yes" ]]; then
        restore_paths "$backup_dir" "$auth_file"
    else
        rm -f "$auth_file"
    fi
    log_info "已恢复修改前的 sshd 配置和公钥，备份在: $backup_dir"
}

# 重启 sshd。Ubuntu 24.04+ 默认由 ssh.socket 监听端口，sshd-socket-generator 会把 sshd_config 里的 Port
# 转成 socket 配置：要先 daemon-reload 重新生成，再重启 ssh.socket 才生效，只重启 ssh.service 端口不会变。
restart_sshd() {
    systemctl daemon-reload
    if systemctl is-active --quiet ssh.socket 2>/dev/null; then
        systemctl restart ssh.socket || return 1
    fi
    if systemctl is-active --quiet ssh.service 2>/dev/null || ! systemctl is-active --quiet ssh.socket 2>/dev/null; then
        systemctl restart ssh 2>/dev/null || systemctl restart sshd
    fi
}

# 1. 配置 Root 密钥登录
setup_ssh_key() {
    echo -e "\n${GREEN}>>> 1. 配置 SSH 密钥登录${PLAIN}"

    if ! command -v sshd >/dev/null 2>&1; then
        log_err "未找到 sshd，请先安装 openssh-server。"
        return 1
    fi

    local sshd_conf="/etc/ssh/sshd_config"
    local dropin_dir="/etc/ssh/sshd_config.d"
    local auth_file="$HOME/.ssh/authorized_keys"

    # === 获取当前状态 ===
    local curr_ports curr_root_login curr_pwd_auth curr_pubkey_auth
    curr_ports=$(get_ssh_ports)
    curr_root_login=$(sshd_effective permitrootlogin)
    curr_pwd_auth=$(sshd_effective passwordauthentication)
    curr_pubkey_auth=$(sshd_effective pubkeyauthentication)

    echo -e "${YELLOW}当前 SSH 服务状态:${PLAIN}"
    echo -e "  端口 (Port):                  ${SKYBLUE}${curr_ports}${PLAIN}"
    echo -e "  Root 登录 (PermitRootLogin):  ${SKYBLUE}${curr_root_login:-未知}${PLAIN}"
    echo -e "  密码验证 (PasswordAuth):      ${SKYBLUE}${curr_pwd_auth:-未知}${PLAIN}"
    echo -e "  公钥验证 (PubkeyAuth):        ${SKYBLUE}${curr_pubkey_auth:-未知}${PLAIN}"
    echo -e "------------------------------------------------"

    mkdir -p ~/.ssh && chmod 700 ~/.ssh

    # 端口必须合法，且不能被其他程序占用（否则 sshd 重启时绑定失败，新连接全部进不来）
    local current_port=${curr_ports%% *}
    local ssh_port listeners
    if [[ "$curr_ports" == *" "* ]]; then
        log_warn "sshd 当前配置了多个端口 ($curr_ports)；本功能只保留下面输入的一个端口，其余端口会被移除。"
    fi
    while true; do
        read -p "请输入 SSH 端口 (当前: $current_port): " ssh_port
        ssh_port=${ssh_port:-$current_port}
        if ! [[ "$ssh_port" =~ ^[1-9][0-9]{0,4}$ ]] || (( ssh_port > 65535 )); then
            log_err "端口必须是 1-65535 之间的整数。"
            continue
        fi
        listeners=$(ss -Hltnp "sport = :$ssh_port" 2>/dev/null)
        if [ -n "$listeners" ] && ! grep -qE '"(sshd|systemd)"' <<<"$listeners"; then
            log_err "端口 $ssh_port 已被其他程序占用:"
            echo "$listeners"
            continue
        fi
        break
    done
    log_info "SSH 端口将配置为: $ssh_port"

    # Ubuntu 22.10–23.10 的 ssh.socket 不读取 sshd_config 中的 Port（24.04 起才由 sshd-socket-generator 转换）
    if [[ "$ssh_port" != "$curr_ports" ]] && systemctl is-active --quiet ssh.socket 2>/dev/null \
            && [ ! -e /usr/lib/systemd/system-generators/sshd-socket-generator ]; then
        log_err "当前由 ssh.socket 监听端口，且系统没有 sshd-socket-generator，修改 sshd_config 的 Port 不会生效。"
        log_err "请改用 systemctl edit ssh.socket 设置 ListenStream。未做任何修改。"
        return 1
    fi

    # 密钥管理逻辑
    local default_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDK9xDRODH1dnk+p4bwiGgn2yX+adg/D9GksUY2vLaumWJKrpg4nBYeNOaWqPEu9t+vcmN4ObEGdBayXp8IA2VdYnsIjLTmLx/FOjWXs2KuxhxTATFQ4OqNbbLiYYIiXWmwJa3qEaFFpD14MnjH44mDRfubBeZVNlNZId+skhGRZv/PazuVMlI2k+vPJS63E2ozuei/TlG/5t58v53FKGhnFXVNTEUidKH42paQyn4+vyLHgVwGO6gBeJm+qAIuOYSAxEyeAhEurpIIWBF6GrpN9RVQu4pi0qFIavXHFtYPBKt7Z2KWrlq9vAGSeM2Aq6Vs8vSlN7ql67rVtuY146Sx soloxyq@foxmail.com"
    local key_opt=1

    if [ -s "$auth_file" ]; then
        echo -e "\n${YELLOW}检测到已有 SSH 密钥:${PLAIN}"
        local i=1
        while IFS= read -r line || [ -n "$line" ]; do
            local comment=$(echo "$line" | awk '{for(i=3;i<=NF;i++) printf $i" "; print ""}')
            [ -z "$comment" ] && comment=$(echo "$line" | cut -c 1-30)...
            echo -e "${SKYBLUE}[$i]${PLAIN} $comment"
            ((i++))
        done < "$auth_file"

        echo -e "\n请选择操作:"
        echo -e "1) ${GREEN}追加${PLAIN} (添加新密钥，保留旧密钥)"
        echo -e "2) ${RED}覆盖${PLAIN} (删除所有旧密钥，仅写入新密钥)"
        echo -e "3) ${YELLOW}保留${PLAIN} (不修改密钥，仅配置端口/密码)"
        read -p "选择 [1-3, 默认 1]: " key_opt
        key_opt=${key_opt:-1}
    fi

    local ssh_key_input new_key="" default_fp overwrite_confirm
    default_fp=$(printf '%s\n' "$default_key" | ssh-keygen -lf - 2>/dev/null | awk '{print $2, $3}')
    if [[ "$key_opt" != "3" ]]; then
        echo -e "\n默认 Key 是仓库作者的公钥 (${SKYBLUE}${default_fp:-格式无效}${PLAIN})；不持有对应私钥时请粘贴自己的公钥。"
        echo -en "${YELLOW}请输入新公钥 (回车使用默认Key): ${PLAIN}"
        read -r ssh_key_input
        new_key=${ssh_key_input:-$default_key}
        # 写入前先校验，避免把无效内容写进 authorized_keys（覆盖模式下会直接把自己锁在外面）
        if ! printf '%s\n' "$new_key" | ssh-keygen -lf - >/dev/null 2>&1; then
            if [ -z "$ssh_key_input" ]; then
                log_err "内置的默认公钥格式已损坏，请重新运行并粘贴你的公钥。未做任何修改。"
            else
                log_err "输入的内容不是有效的 SSH 公钥，未做任何修改。"
            fi
            return 1
        fi
        if [[ "$key_opt" == "2" && -z "$ssh_key_input" ]]; then
            read -p "覆盖后 authorized_keys 只剩默认 Key，确认? [y/N]: " overwrite_confirm
            if [[ ! "$overwrite_confirm" =~ ^[Yy]$ ]]; then
                log_info "已取消，未做任何修改。"
                return 0
            fi
        fi
    fi

    # 检测当前是否已经禁用密码
    local current_pwd_auth=${curr_pwd_auth:-yes} # 使用之前获取的状态
    local pwd_hint="推荐 y"
    if [[ "$current_pwd_auth" == "no" ]]; then
        pwd_hint="当前已禁用"
    fi

    local disable_pwd
    read -p "是否禁用密码登录 ($pwd_hint)? [y/N]: " disable_pwd

    # === 开始修改：先备份，之后任何一步校验失败都恢复 sshd 配置和公钥 ===
    local backup_dir auth_existed=no
    [ -e "$auth_file" ] && auth_existed=yes
    backup_dir=$(make_backup_dir ssh) || { log_err "无法创建备份目录。"; return 1; }
    backup_paths "$backup_dir" "$sshd_conf" "$dropin_dir" "$auth_file"

    if [[ "$key_opt" == "3" ]]; then
        log_info "跳过密钥修改。"
    elif [[ "$key_opt" == "2" ]]; then
        printf '%s\n' "$new_key" > "$auth_file"
        log_success "原有密钥已清空，新密钥已写入。"
    elif append_authorized_key "$auth_file" "$new_key"; then
        log_success "新密钥已追加。"
    else
        log_info "该密钥已存在，无需重复添加。"
    fi
    [ -f "$auth_file" ] && chmod 600 "$auth_file"

    # 没有可用公钥时禁用密码登录，会把自己锁在外面
    local restricted_confirm only_default_confirm
    if [[ "$disable_pwd" =~ ^[Yy]$ ]]; then
        if ! ssh-keygen -lf "$auth_file" >/dev/null 2>&1; then
            log_err "$auth_file 中没有有效公钥，为避免无法登录，本次不禁用密码登录。"
            disable_pwd="n"
        elif only_this_key "$auth_file" "$default_key"; then
            log_warn "$auth_file 中只有默认 Key（仓库作者 ${default_fp:-}）；禁用密码后，只有持有其私钥的人能登录这台服务器。"
            read -p "确认禁用密码登录? [y/N]: " only_default_confirm
            [[ "$only_default_confirm" =~ ^[Yy]$ ]] || disable_pwd="n"
        elif ! has_unrestricted_key "$auth_file"; then
            log_warn "$auth_file 中的公钥都带有 command=/from= 等限制选项，禁用密码后 root 可能无法正常登录。"
            read -p "仍要禁用密码登录? [y/N]: " restricted_confirm
            [[ "$restricted_confirm" =~ ^[Yy]$ ]] || disable_pwd="n"
        fi
    fi

    if ! sshd_set_port "$sshd_conf" "$ssh_port" "$dropin_dir"; then
        log_err "写入 SSH 端口失败。"
        ssh_rollback "$backup_dir" "$auth_file" "$auth_existed"
        return 1
    fi

    if [[ "$disable_pwd" =~ ^[Yy]$ ]]; then
        sed -i -E \
            -e 's/^#?PasswordAuthentication[[:space:]].*/PasswordAuthentication no/I' \
            -e 's/^#?KbdInteractiveAuthentication[[:space:]].*/KbdInteractiveAuthentication no/I' \
            -e 's/^#?PermitRootLogin[[:space:]].*/PermitRootLogin prohibit-password/I' \
            "$sshd_conf"
        # sshd 对同一选项只取第一次出现的值；Include 位于主配置开头，01- 会排在 cloud-init 等 drop-in 之前
        if [ -d "$dropin_dir" ]; then
            cat > "$dropin_dir/01-disable-password.conf" <<'EOF'
# 由 xqvinit 写入：只允许密钥登录，root 也只能用密钥登录
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
        fi
        log_info "已配置禁用密码登录 (root 仅允许密钥登录)。"
    fi

    # 重启前校验语法，并核对实际生效的端口
    local test_out
    mkdir -p /run/sshd
    if ! test_out=$(sshd -t 2>&1); then
        log_err "sshd 配置校验失败:"
        echo "$test_out"
        ssh_rollback "$backup_dir" "$auth_file" "$auth_existed"
        return 1
    fi

    local eff_ports
    eff_ports=$(get_ssh_ports)
    if [[ "$eff_ports" != "$ssh_port" ]]; then
        log_err "生效端口为 [$eff_ports]，与预期的 $ssh_port 不一致（可能被其他 Include 配置覆盖）。"
        ssh_rollback "$backup_dir" "$auth_file" "$auth_existed"
        return 1
    fi
    if [[ "$disable_pwd" =~ ^[Yy]$ ]]; then
        local eff_pwd eff_root
        eff_pwd=$(sshd_effective passwordauthentication)
        eff_root=$(sshd_effective permitrootlogin)
        # sshd -T 把 prohibit-password 显示为 without-password
        if [[ "$eff_root" != "without-password" && "$eff_root" != "prohibit-password" && "$eff_root" != "yes" ]]; then
            log_err "PermitRootLogin 实际为 ${eff_root:-未知}（被其他配置覆盖），root 无法用密钥登录，禁用密码可能导致无法登录。"
            ssh_rollback "$backup_dir" "$auth_file" "$auth_existed"
            return 1
        fi
        if [[ "$eff_pwd" != "no" ]]; then
            log_warn "PasswordAuthentication 实际仍为 ${eff_pwd:-未知}，请检查 $sshd_conf 中 Include 的位置。"
        fi
    fi

    # UFW 已启用时先放行新端口，再重启 sshd；放行失败就不能切换端口
    if command -v ufw >/dev/null 2>&1 && LC_ALL=C ufw status 2>/dev/null | grep -q '^Status: active'; then
        if ! ufw allow "$ssh_port"/tcp >/dev/null; then
            log_err "UFW 放行 $ssh_port/tcp 失败，为避免重启 sshd 后无法连接，撤销本次修改。"
            ssh_rollback "$backup_dir" "$auth_file" "$auth_existed"
            return 1
        fi
        log_info "UFW 已放行 $ssh_port/tcp。旧端口规则保留，确认新端口能登录后可用 ufw delete 删除。"
    fi

    log_info "正在重启 SSH 服务..."
    if ! restart_sshd; then
        log_err "SSH 服务重启失败，正在恢复修改前的配置..."
        ssh_rollback "$backup_dir" "$auth_file" "$auth_existed"
        restart_sshd || log_err "恢复后 sshd 仍未启动。不要断开当前连接，先检查: systemctl status ssh"
        return 1
    fi

    sleep 1
    if ss -Hltn "sport = :$ssh_port" 2>/dev/null | grep -q .; then
        log_success "SSH 已在端口 $ssh_port 监听。"
    else
        log_warn "没有检测到端口 $ssh_port 在监听，请检查: systemctl status ssh ssh.socket"
    fi

    # Fail2ban 由本脚本配置过时，同步监控端口
    if [ -f /etc/fail2ban/jail.local ] && grep -q '^\[sshd\]' /etc/fail2ban/jail.local; then
        sed -i -E "/^\[sshd\]/,/^\[/ s/^port[[:space:]]*=.*/port = $ssh_port/" /etc/fail2ban/jail.local
        systemctl restart fail2ban >/dev/null 2>&1 && log_info "Fail2ban 监控端口已同步为 $ssh_port。"
    fi

    log_success "SSH 配置完成！修改前的配置备份在: $backup_dir"
    log_warn "请保持当前连接，另开一个终端测试 ssh -p $ssh_port root@<服务器IP>，能登录后再断开。"
    if [[ "$ssh_port" != "$curr_ports" ]]; then
        log_warn "如果云厂商控制台有安全组/防火墙，也需要放行 $ssh_port/tcp。"
    fi
}

# 2. 安装 UFW
install_ufw() {
    echo -e "\n${GREEN}>>> 2. 安装并配置 UFW 防火墙${PLAIN}"
    if ! { apt update && apt install ufw -y; }; then
        log_err "UFW 安装失败。"
        return 1
    fi

    local port confirm
    for port in $(get_ssh_listen_ports); do
        log_info "将自动放行 SSH 端口: $port"
        if ! ufw allow "$port"/tcp; then
            log_err "放行 SSH 端口 $port 失败，为避免把自己锁在外面，不启用 UFW。"
            return 1
        fi
    done
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 16790:16799/tcp
    ufw allow 16790:16799/udp

    log_warn "启用 UFW 可能会暂时中断连接。"
    read -p "确定启用? [y/N]: " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "y" | ufw enable
        log_success "UFW 已启动并预设规则。"
    fi
}

# 3. Fail2ban
install_fail2ban() {
    echo -e "\n${GREEN}>>> 3. 安装 Fail2ban${PLAIN}"
    # backend = systemd 需要 python3-systemd
    if ! { apt update && apt install -y fail2ban python3-systemd; }; then
        log_err "Fail2ban 安装失败。"
        return 1
    fi

    # 智能检测 SSH 端口（多个端口用逗号分隔）
    local ssh_ports
    ssh_ports=$(get_ssh_listen_ports | tr ' ' ',')
    log_info "检测到 SSH 端口为: $ssh_ports，正在配置 Fail2ban 监控..."

    # 创建 jail.local 并显式指定端口。
    # Debian 12 默认不装 rsyslog、没有 /var/log/auth.log，按日志文件读取时 sshd jail 起不来，所以直接读 journald。
    cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
port = $ssh_ports
backend = systemd
EOF

    systemctl enable fail2ban >/dev/null 2>&1
    systemctl restart fail2ban
    local i
    for i in 1 2 3 4 5; do
        if fail2ban-client status sshd >/dev/null 2>&1; then
            log_success "Fail2ban 已启动，监控 SSH 端口: $ssh_ports"
            log_info "查看状态: fail2ban-client status sshd"
            return 0
        fi
        sleep 2
    done
    log_err "Fail2ban 的 sshd jail 没有启动，请查看: journalctl -u fail2ban -n 50"
    return 1
}

# 4. Swap 优化
setup_swap() {
    echo -e "\n${GREEN}>>> 4. 设置 Swap 内存${PLAIN}"
    local swapfile="/swapfile" size confirm
    if swapon --show=NAME --noheadings 2>/dev/null | grep -q .; then
        log_warn "检测到已有 Swap:"
        swapon --show
        log_warn "将重建 $swapfile（其他 Swap 文件/分区保持不变）。"
        read -p "确认继续? [y/N]: " confirm
        [[ ! "$confirm" =~ ^[Yy]$ ]] && return
    fi

    read -p "输入大小 (MB, 如 1024): " size
    [[ ! "$size" =~ ^[1-9][0-9]*$ ]] && { log_err "非法输入"; return; }

    # 空间检查：旧 /swapfile 会先删除，把它的大小计入可用空间；至少预留 256MB，避免 dd 回退时把磁盘写满
    local avail_mb old_mb=0
    avail_mb=$(df --output=avail -m / 2>/dev/null | tail -n 1 | tr -d ' ')
    [ -f "$swapfile" ] && old_mb=$(( $(stat -c %s "$swapfile") / 1048576 ))
    if [[ "$avail_mb" =~ ^[0-9]+$ ]] && (( size + 256 > avail_mb + old_mb )); then
        log_err "磁盘空间不足：可用约 $(( avail_mb + old_mb ))MB，需要 ${size}MB 并预留 256MB。"
        return 1
    fi

    # 旧文件必须先删除：fallocate 不会把已有的大文件缩小
    if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$swapfile"; then
        swapoff "$swapfile" || { log_err "关闭旧 Swap 失败（可能内存不足以收回 Swap 中的数据），已中止。"; return 1; }
    fi
    rm -f "$swapfile"
    sed -i '\|^[[:space:]]*/swapfile[[:space:]]|d' /etc/fstab

    log_info "创建 Swap 文件中..."
    if ! fallocate -l "${size}M" "$swapfile" 2>/dev/null; then
        log_warn "fallocate 失败，回退到 dd (较慢)..."
        if ! dd if=/dev/zero of="$swapfile" bs=1M count="$size" status=progress; then
            log_err "创建 Swap 文件失败。"
            rm -f "$swapfile"
            return 1
        fi
    fi

    chmod 600 "$swapfile"
    if ! mkswap "$swapfile" >/dev/null || ! swapon "$swapfile"; then
        log_err "启用 Swap 失败，未写入 /etc/fstab。"
        rm -f "$swapfile"
        return 1
    fi
    # fstab 末尾缺换行时先补一个，否则新条目会接在上一行末尾，两行都会被忽略
    if [ -s /etc/fstab ] && [ -n "$(tail -c 1 /etc/fstab)" ]; then
        echo >> /etc/fstab
    fi
    echo "$swapfile swap swap defaults 0 0" >> /etc/fstab
    log_success "Swap 设置成功:"
    free -h
}

# 5. BBR 优化
enable_bbr() {
    echo -e "\n${GREEN}>>> 5. TCP/BBR 网络优化${PLAIN}"
    run_remote_script "https://raw.githubusercontent.com/Eric86777/vps-tcp-tune/main/install-alias.sh?$(date +%s)"
}

# 6. NodeQuality
run_nq_test() {
    echo -e "\n${GREEN}>>> 6. NodeQuality 系统测试${PLAIN}"
    run_remote_script https://run.NodeQuality.com
}

# 7. VLESS
# 该脚本会把自身路径写进 cron 定时任务（如过期检查），必须像上游用法那样保存在固定位置再运行，
# 不能用运行完即删除的临时文件；用绝对路径启动，cron 里记录的也是绝对路径。
install_vless() {
    echo -e "\n${GREEN}>>> 7. VLESS 代理服务${PLAIN}"
    local url="https://raw.githubusercontent.com/mozisen/surge/main/vless-server.sh"
    local target="$HOME/vless-server.sh" tmp
    tmp=$(mktemp) || { log_err "无法创建临时文件。"; return 1; }
    trap 'rm -f "$tmp"' INT TERM
    if ! download_https "$url" "$tmp" || ! install -m 755 "$tmp" "$target"; then
        trap - INT TERM
        rm -f "$tmp"
        log_err "未能保存脚本到 $target，未执行。"
        return 1
    fi
    trap - INT TERM
    rm -f "$tmp"
    log_info "脚本已保存到 $target"
    # 与其他第三方脚本一致：运行中按 Ctrl-C 只中断该脚本，然后回到菜单
    local rc
    trap ':' INT TERM
    bash "$target"
    rc=$?
    trap - INT TERM
    return $rc
}

# 8. 时区
setup_timezone() {
    echo -e "\n${GREEN}>>> 8. 设置时区${PLAIN}"
    timedatectl set-timezone Asia/Shanghai
    log_success "当前时间: $(date -R)"
}

# 9. Docker
install_docker() {
    echo -e "\n${GREEN}>>> 9. 安装 Docker${PLAIN}"
    if command -v docker >/dev/null 2>&1; then
        log_info "Docker 已安装。"
    elif run_remote_script https://get.docker.com; then
        systemctl enable --now docker
        log_success "Docker 安装完成。"
    else
        log_err "Docker 安装失败。"
    fi
}

# 10. DNS 净化优化
write_resolved_conf() {
    cat > /etc/systemd/resolved.conf <<EOF
[Resolve]
DNS=8.8.8.8#dns.google 1.1.1.1#cloudflare-dns.com
DNSSEC=allow-downgrade
DNSOverTLS=$1
LLMNR=no
MulticastDNS=no
EOF
}

# 验证 DNS 可用，任一域名通过即可。每个域名查两次：
#   1) resolvectl query 绕过 /etc/hosts 和缓存，直接让 systemd-resolved 向上游查询。
#      普通 getent 会先读 /etc/hosts（国内机器常把 github.com 写进去），严格 DoT 实际不通时也会误判为正常。
#   2) getent -s dns 只走 DNS（不读 /etc/hosts），经 /etc/resolv.conf 和 127.0.0.53 stub，即程序实际的解析路径。
dns_resolves() {
    local domain opts=()
    # --cache= 和 --synthesize= 都是 systemd 248 加入的；更早的版本先清缓存再普通查询
    if resolvectl --help 2>/dev/null | grep -q -- '--synthesize='; then
        opts=(--cache=no --synthesize=no)
    else
        resolvectl flush-caches >/dev/null 2>&1
    fi
    for domain in $DNS_TEST_DOMAINS; do
        timeout 15 resolvectl query "${opts[@]}" "$domain" >/dev/null 2>&1 \
            && timeout 15 getent -s dns ahosts "$domain" >/dev/null 2>&1 && return 0
    done
    return 1
}

# 恢复后的 resolv.conf 若是指向不存在文件的链接（例如安装 systemd-resolved 时顺带卸载了 resolvconf），
# 改为写入修改前保存的内容，保证回滚后仍有可用的 DNS
fix_dangling_resolv() {
    local resolv="$1" content="$2"
    if [ -L "$resolv" ] && [ ! -e "$resolv" ] && [ -s "$content" ]; then
        rm -f "$resolv"
        cp "$content" "$resolv"
        chmod 644 "$resolv"
        log_warn "$resolv 原链接的目标已不存在，已改为写入修改前的 DNS 内容。"
    fi
}

# 恢复 purify_dns 修改前的状态
# 用法: dns_rollback 备份目录 resolved原先是否运行(yes/no) 是否禁用过if-up.d钩子(yes/no) 备份过的路径...
dns_rollback() {
    local backup_dir="$1" resolved_was_active="$2" ifup_hook_disabled="$3"
    shift 3
    rm -f "$DHCP_DNS_HOOK"
    restore_paths "$backup_dir" "$@"
    fix_dangling_resolv /etc/resolv.conf "$backup_dir/resolv.conf.content"
    [[ "$ifup_hook_disabled" == "yes" ]] && chmod +x /etc/network/if-up.d/resolved
    if [[ "$resolved_was_active" == "yes" ]]; then
        systemctl restart systemd-resolved
    else
        systemctl disable --now systemd-resolved >/dev/null 2>&1
    fi
}

purify_dns() {
    echo -e "\n${GREEN}>>> 10. DNS 净化与安全加固${PLAIN}"

    local ifup_hook="/etc/network/if-up.d/resolved"
    local ifupdown_files=() f
    for f in /etc/network/interfaces /etc/network/interfaces.d/*; do
        [ -f "$f" ] && ifupdown_files+=("$f")
    done
    local managed=(/etc/resolv.conf /etc/systemd/resolved.conf /etc/dhcp/dhclient.conf "$DHCP_DNS_HOOK" "${ifupdown_files[@]}")

    local backup_dir resolved_was_active=no ifup_hook_disabled=no
    backup_dir=$(make_backup_dir dns) || { log_err "无法创建备份目录。"; return 1; }
    backup_paths "$backup_dir" "${managed[@]}"
    # resolv.conf 若是链接，其目标可能随软件包卸载而消失；另存一份实际内容供回滚使用
    cat /etc/resolv.conf > "$backup_dir/resolv.conf.content" 2>/dev/null
    systemctl is-active --quiet systemd-resolved 2>/dev/null && resolved_was_active=yes

    # Debian 12 的 systemd-resolved 是独立软件包，Ubuntu 已随 systemd 自带
    if ! command -v resolvectl >/dev/null 2>&1; then
        log_info "正在安装 systemd-resolved..."
        if ! apt update; then
            log_err "apt update 失败，未做任何修改。"
            return 1
        fi
        # systemd-resolved 与 resolvconf 等软件包冲突，安装时会把它们卸载；回滚只能恢复配置文件，无法自动重装
        local removals remove_confirm
        removals=$(apt-get -s install -y systemd-resolved 2>/dev/null | awk '/^Remv / { print $2 }' | paste -sd ' ')
        if [ -n "$removals" ]; then
            log_warn "安装 systemd-resolved 会卸载: $removals"
            log_warn "如果后续 DNS 验证失败，脚本只会恢复配置文件，不会自动重装这些软件包。"
            read -p "确认继续? [y/N]: " remove_confirm
            if [[ ! "$remove_confirm" =~ ^[Yy]$ ]]; then
                log_info "已取消，未做任何修改。"
                return 0
            fi
        fi
        if ! apt install -y systemd-resolved; then
            log_err "systemd-resolved 安装失败，正在恢复修改前的配置..."
            dns_rollback "$backup_dir" "$resolved_was_active" "$ifup_hook_disabled" "${managed[@]}"
            return 1
        fi
    fi

    # 1. 净化 dhclient
    #    Debian 的 dhclient-script 在获取/续租 DHCP 时，会把下发的 DNS 写进 /etc/resolv.conf 指向的文件
    #    （即 resolved 的 stub-resolv.conf），程序随后直接用明文查询服务商 DNS，绕过 DoT。
    #    旧版写入的 "ignore domain-name-servers;" 在 ISC dhclient 中只是 bootp 策略语句，并不会忽略 DNS，这里清理掉，
    #    改用 enter hook：dhclient-script 会 source 该目录下的脚本，覆盖 make_resolv_conf 并丢弃下发的 DNS。
    if [ -f /etc/dhcp/dhclient.conf ]; then
        sed -i -E '/^ignore domain-(name-servers|search);$/d' /etc/dhcp/dhclient.conf
    fi
    if [ -d /etc/dhcp ]; then
        mkdir -p "${DHCP_DNS_HOOK%/*}"
        cat > "$DHCP_DNS_HOOK" <<'EOF'
# 由 xqvinit 写入：DNS 统一由 systemd-resolved (DoT) 负责。
# 不让 dhclient 改写 /etc/resolv.conf，也不把 DHCP 下发的 DNS 和搜索域交给后续 hook。
make_resolv_conf() {
    :
}
unset new_domain_name_servers new_domain_search new_dhcp6_name_servers new_dhcp6_domain_search
EOF
        log_success "已阻止 dhclient 用 DHCP 下发的 DNS 覆盖解析配置。"
    fi

    # 2. 禁用 if-up.d 冲突脚本：它会把 interfaces 中的 dns-* 推给 systemd-resolved
    if [ -x "$ifup_hook" ]; then
        chmod -x "$ifup_hook"
        ifup_hook_disabled=yes
        log_success "已禁用冲突的 $ifup_hook 脚本。"
    fi

    # 3. 注释 /etc/network/interfaces(.d) 中残留的 dns-* 配置
    for f in "${ifupdown_files[@]}"; do
        if grep -qE '^[[:space:]]*dns-(nameservers|search|domain)' "$f"; then
            sed -i -E 's/^[[:space:]]*(dns-(nameservers|search|domain).*)/# \1/' "$f"
            log_success "已注释 $f 中的 dns-* 配置。"
        fi
    done

    # 4. 配置 systemd-resolved：先用严格 DoT；解析失败（常见于 853 端口被封）时降级为 opportunistic，仍失败则整体回滚
    log_info "正在配置 DoT (DNS over TLS)..."
    write_resolved_conf yes
    systemctl enable systemd-resolved >/dev/null 2>&1
    systemctl restart systemd-resolved
    # resolv.conf 被锁定（如 chattr +i）时链接会失败；此时程序仍在用旧 DNS，后面的解析测试也测不到 DoT
    if ! ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf; then
        log_err "无法把 /etc/resolv.conf 指向 systemd-resolved（文件可能被锁定），正在恢复修改前的配置..."
        dns_rollback "$backup_dir" "$resolved_was_active" "$ifup_hook_disabled" "${managed[@]}"
        return 1
    fi

    log_info "正在验证 DNS 解析..."
    if dns_resolves; then
        log_success "DNS 净化完成，DoT 严格模式 (DNSOverTLS=yes) 工作正常。"
    else
        log_warn "严格 DoT 下解析失败（可能 853 端口被封），改用 opportunistic 模式重试..."
        write_resolved_conf opportunistic
        systemctl restart systemd-resolved
        if dns_resolves; then
            log_warn "已改为 DNSOverTLS=opportunistic：优先加密，DoT 不可用时会回落为明文 DNS。"
        else
            log_err "DNS 解析仍然失败，正在恢复修改前的配置..."
            dns_rollback "$backup_dir" "$resolved_was_active" "$ifup_hook_disabled" "${managed[@]}"
            return 1
        fi
    fi

    resolvectl status 2>/dev/null | grep -E 'Protocols|DNS Servers' | head -6
    # netplan / systemd-networkd 管理的网卡会把 DHCP 下发的 DNS 设为链路 DNS，resolved 会和 DoT 服务器一起使用
    local link_dns
    link_dns=$(resolvectl dns 2>/dev/null | grep -E '^Link [0-9]+ \([^)]*\): .+')
    if [ -n "$link_dns" ]; then
        log_warn "以下网卡仍有链路级 DNS（多为 netplan/networkd 的 DHCP 下发），systemd-resolved 也会向它们查询:"
        echo "$link_dns"
    fi
    log_info "修改前的配置备份在: $backup_dir"
}

# 11. 1Panel
install_1panel() {
    echo -e "\n${GREEN}>>> 11. 安装 1Panel${PLAIN}"
    # 安装脚本会把安装包下载并解压到当前目录，放在临时目录中执行，结束后清理
    run_remote_script --in-tmpdir https://resource.1panel.pro/quick_start.sh
}

# 12. NextTrace
install_nexttrace() {
    echo -e "\n${GREEN}>>> 12. 安装 NextTrace${PLAIN}"
    run_remote_script https://nxtrace.org/nt
}

# 13. 哪吒探针优化
install_nezha() {
    echo -e "\n${GREEN}>>> 13. 安装哪吒探针 Agent${PLAIN}"
    local default_server="dashboard.7879710.xyz:443"
    local default_secret="24naSa4QDIS7kaEEtYntEKc7K84Yb31b"
    local choice srv sec tls tls_in

    echo -e "1) 使用默认配置 (${YELLOW}$default_server${PLAIN})"
    echo -e "2) 自定义配置"
    read -p "选择 [1-2, 默认 1]: " choice
    choice=${choice:-1}

    if [[ "$choice" == "1" ]]; then
        srv=$default_server; sec=$default_secret; tls="true"
    else
        read -p "服务器地址: " srv
        read -p "密钥: " sec
        read -p "启用 TLS? [Y/n]: " tls_in
        tls="true"; [[ "$tls_in" =~ ^[Nn]$ ]] && tls="false"
    fi

    [ -z "$srv" ] || [ -z "$sec" ] && { log_err "参数不全"; return; }

    log_info "下载安装脚本..."
    NZ_SERVER="$srv" NZ_TLS="$tls" NZ_CLIENT_SECRET="$sec" \
        run_remote_script https://raw.githubusercontent.com/nezhahq/scripts/main/agent/install.sh
}

# 菜单
show_menu() {
    echo -e "
${GREEN}====================================================
       VPS 初始化工具箱 (Debian 12+ / Ubuntu 22.04+)
====================================================${PLAIN}"
    echo -e "${GREEN} 1.${PLAIN} 配置 SSH 密钥登录 (端口/Key/禁用密码)"
    echo -e "${GREEN} 2.${PLAIN} 安装 UFW 防火墙 (预设常用端口)"
    echo -e "${GREEN} 3.${PLAIN} 安装 Fail2ban 防护 (自动适配SSH端口)"
    echo -e "${GREEN} 4.${PLAIN} 设置 Swap 虚拟内存"
    echo -e "${GREEN} 5.${PLAIN} TCP/BBR 网络优化 (高级脚本)"
    echo -e "${GREEN} 6.${PLAIN} 系统综合测试 (NodeQuality)"
    echo -e "${GREEN} 7.${PLAIN} 安装 VLESS 代理服务"
    echo -e "${GREEN} 8.${PLAIN} 设置时区 (Asia/Shanghai)"
    echo -e "${GREEN} 9.${PLAIN} 安装 Docker 环境"
    echo -e "${GREEN}10.${PLAIN} DNS 净化与 DoT 安全加固"
    echo -e "${GREEN}11.${PLAIN} 安装 1Panel 服务器面板"
    echo -e "${GREEN}12.${PLAIN} 安装 NextTrace 路由追踪"
    echo -e "${GREEN}13.${PLAIN} 安装哪吒探针 Agent"
    echo -e "${GREEN} 0.${PLAIN} 退出
"
}

# 别名设置
setup_alias() {
    local script_path=$(readlink -f "$0")
    local alias_cmd="alias xqvinit='$script_path'"
    for rc in ~/.bashrc ~/.zshrc; do
        if [ -f "$rc" ] && ! grep -q "xqvinit" "$rc"; then
            echo -e "\n$alias_cmd" >> "$rc"
            log_success "别名已添加到 $rc，下次可直接输入 xqvinit 运行。"
        fi
    done
}

# 主循环
main() {
    check_dependencies
    check_sys_version
    setup_alias
    while true; do
        show_menu
        read -p "请输入选项 [0-13]: " opt
        case "$opt" in
            1) setup_ssh_key ;;
            2) install_ufw ;;
            3) install_fail2ban ;;
            4) setup_swap ;;
            5) enable_bbr ;;
            6) run_nq_test ;;
            7) install_vless ;;
            8) setup_timezone ;;
            9) install_docker ;;
            10) purify_dns ;;
            11) install_1panel ;;
            12) install_nexttrace ;;
            13) install_nezha ;;
            0) exit 0 ;;
            *) log_err "无效选项，请重新输入。" ;;
        esac
        echo -en "\n${YELLOW}任务完成，按回车键返回菜单...${PLAIN}"
        read
    done
}

main
