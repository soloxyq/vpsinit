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

# 1. 配置 Root 密钥登录
setup_ssh_key() {
    echo -e "\n${GREEN}>>> 1. 配置 SSH 密钥登录${PLAIN}"
    
    # === 获取当前状态 ===
    local curr_port=$(sshd -T 2>/dev/null | grep "^port " | awk '{print $2}')
    local curr_root_login=$(sshd -T 2>/dev/null | grep "^permitrootlogin " | awk '{print $2}')
    local curr_pwd_auth=$(sshd -T 2>/dev/null | grep "^passwordauthentication " | awk '{print $2}')
    local curr_pubkey_auth=$(sshd -T 2>/dev/null | grep "^pubkeyauthentication " | awk '{print $2}')
    
    echo -e "${YELLOW}当前 SSH 服务状态:${PLAIN}"
    echo -e "  端口 (Port):                  ${SKYBLUE}${curr_port:-未知}${PLAIN}"
    echo -e "  Root 登录 (PermitRootLogin):  ${SKYBLUE}${curr_root_login:-未知}${PLAIN}"
    echo -e "  密码验证 (PasswordAuth):      ${SKYBLUE}${curr_pwd_auth:-未知}${PLAIN}"
    echo -e "  公钥验证 (PubkeyAuth):        ${SKYBLUE}${curr_pubkey_auth:-未知}${PLAIN}"
    echo -e "------------------------------------------------"
    
    mkdir -p ~/.ssh && chmod 700 ~/.ssh
    
    # 智能侦测当前 SSH 端口
    local current_port=${curr_port:-22}
    
    read -p "请输入 SSH 端口 (当前: $current_port): " ssh_port
    ssh_port=${ssh_port:-$current_port}
    
    # 修改端口逻辑优化
    # 1. 修改主配置文件
    sed -i '/^#\?Port /d' /etc/ssh/sshd_config
    echo "Port $ssh_port" >> /etc/ssh/sshd_config
    
    # 2. 检查 .d 目录是否有覆盖配置，如果有则清理或更新
    if [ -d /etc/ssh/sshd_config.d ]; then
        grep -l "^Port " /etc/ssh/sshd_config.d/*.conf 2>/dev/null | xargs -r sed -i '/^Port /d'
    fi
    
    log_info "SSH 端口配置为: $ssh_port"

    # 密钥管理逻辑
    local auth_file="$HOME/.ssh/authorized_keys"
    local default_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCp3ORPYIfDP7xXP/brTqXf2RKyJ21u+fH1ffqbTEmBXvbPjIXTOlNH9c/FrPydG04D4RtbVXcL1C22ZUNWTuMcyKU8RBersn6tmzVGrG224ML9rg9uvt56gnAbenxt7haHqebBdWDsco+Er4Zie4KqviWk91C78lOvm4dqCwSXzI0+091DTxvRmn49gVijQV9uLACHxwFVNTGsy6nRkNO67dp3jY+4NW8+QvHE5hoxnj2pxOoPi5D5xSjoLG9+fhC1spCwAJ5bQ06SURN+beeNwUCpbm5bSRX6j6nVPNgNEaXd30+JfMxOyXwc99wLoy8jIBfqwBgAGRGnI+26qMkvaBd2XzYpv1U4pQUN2ed2gksRElSPpnJKNXfQzSsEfq4q4mK0DAtPTl+yBEdi9psOYuFCLQ9IYzgY13MRJgVgxcfbjV2So4+7zJmiLDyyrzu1kC3SvQUe1qaBLT3hxMNQ9iePn6i44LZo75EPXY42H/YZD6aduWL34qzpD2+Q3yHiCT7ADQrADg7k2yywtEduWbfOK6mc1TqftNszSKSSYlQyW2ieFex9EJvI+kRWS/cV4IuXas6JN46OIhOg+TBH1vtvUge+dE1pa+2YuCAUuhLvB9NsuVRu4qQZGZC4ZeBG3yAUmYyJczLhAWSmtdIHxLZb9wDeULK6u5wWwunMQ== soloxyq@foxmail.com"

    if [ -s "$auth_file" ]; then
        echo -e "\n${YELLOW}检测到已有 SSH 密钥:${PLAIN}"
        local i=1
        while IFS= read -r line; do
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
    else
        key_opt=1
    fi

    if [[ "$key_opt" == "3" ]]; then
        log_info "跳过密钥修改。"
    else
        echo -en "\n${YELLOW}请输入新公钥 (回车使用默认Key): ${PLAIN}"
        read -r ssh_key_input
        local new_key=${ssh_key_input:-$default_key}

        if [[ "$key_opt" == "2" ]]; then
            echo "$new_key" > "$auth_file"
            log_success "原有密钥已清空，新密钥已写入。"
        else
            if ! grep -q "$new_key" "$auth_file" 2>/dev/null; then
                echo "$new_key" >> "$auth_file"
                log_success "新密钥已追加。"
            else
                log_info "该密钥已存在，无需重复添加。"
            fi
        fi
        chmod 600 "$auth_file"
    fi

    # 检测当前是否已经禁用密码
    local current_pwd_auth=${curr_pwd_auth:-yes} # 使用之前获取的状态
    local pwd_hint="推荐 y"
    if [[ "$current_pwd_auth" == "no" ]]; then
        pwd_hint="当前已禁用"
    fi

    read -p "是否禁用密码登录 ($pwd_hint)? [y/N]: " disable_pwd
    if [[ "$disable_pwd" =~ ^[Yy]$ ]]; then
        sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/g' /etc/ssh/sshd_config
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config
        # 处理可能的 Include 目录
        [ -d /etc/ssh/sshd_config.d ] && echo "PasswordAuthentication no" > /etc/ssh/sshd_config.d/01-disable-password.conf
        log_info "已配置禁用密码登录。"
    fi

    log_info "正在重启 SSH 服务..."
    systemctl restart ssh || systemctl restart sshd
    log_success "SSH 配置完成！"
}

# 2. 安装 UFW
install_ufw() {
    echo -e "\n${GREEN}>>> 2. 安装并配置 UFW 防火墙${PLAIN}"
    apt update && apt install ufw -y
    
    local current_ssh_port=$(sshd -T 2>/dev/null | grep "^port " | awk '{print $2}')
    current_ssh_port=${current_ssh_port:-22}
    
    log_info "将自动放行 SSH 端口: $current_ssh_port"
    ufw allow "$current_ssh_port"/tcp
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
    apt update && apt install fail2ban -y
    
    # 智能检测 SSH 端口
    local ssh_port=$(sshd -T 2>/dev/null | grep "^port " | awk '{print $2}')
    ssh_port=${ssh_port:-22}
    log_info "检测到 SSH 端口为: $ssh_port，正在配置 Fail2ban 监控..."

    # 创建 jail.local 并显式指定端口
    cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
port = $ssh_port
EOF

    systemctl enable --now fail2ban
    systemctl restart fail2ban
    log_success "Fail2ban 已启动，监控 SSH 端口: $ssh_port"
    log_info "查看状态: fail2ban-client status sshd"
}

# 4. Swap 优化
setup_swap() {
    echo -e "\n${GREEN}>>> 4. 设置 Swap 内存${PLAIN}"
    if free | grep -q "Swap:" && [[ $(free -m | grep Swap | awk '{print $2}') -gt 0 ]]; then
        log_warn "检测到已有 Swap。重新设置将清除旧文件。"
        read -p "确认继续? [y/N]: " confirm
        [[ ! "$confirm" =~ ^[Yy]$ ]] && return
        swapoff -a
        sed -i '/swapfile/d' /etc/fstab
    fi

    read -p "输入大小 (MB, 如 1024): " size
    [[ ! "$size" =~ ^[0-9]+$ ]] && { log_err "非法输入"; return; }

    log_info "创建 Swap 文件中..."
    if ! fallocate -l "${size}M" /swapfile 2>/dev/null; then
        log_warn "fallocate 失败，回退到 dd (较慢)..."
        dd if=/dev/zero of=/swapfile bs=1M count="$size" status=progress
    fi

    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile swap swap defaults 0 0" >> /etc/fstab
    log_success "Swap 设置成功:"
    free -h
}

# 5. BBR 优化
enable_bbr() {
    echo -e "\n${GREEN}>>> 5. TCP/BBR 网络优化${PLAIN}"
    bash <(curl -fsSL "https://raw.githubusercontent.com/Eric86777/vps-tcp-tune/main/install-alias.sh?$(date +%s)")
}

# 6. NodeQuality
run_nq_test() {
    echo -e "\n${GREEN}>>> 6. NodeQuality 系统测试${PLAIN}"
    bash <(curl -sL https://run.NodeQuality.com)
}

# 7. VLESS
install_vless() {
    echo -e "\n${GREEN}>>> 7. VLESS 代理服务${PLAIN}"
    wget -qO- https://raw.githubusercontent.com/Chil30/vless-all-in-one/main/vless-server.sh | bash
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
    else
        curl -fsSL https://get.docker.com | bash
        systemctl enable --now docker
        log_success "Docker 安装完成。"
    fi
}

# 10. DNS 净化优化
purify_dns() {
    echo -e "\n${GREEN}>>> 10. DNS 净化与安全加固${PLAIN}"
    log_info "正在配置 DoT (DNS over TLS)..."
    
    apt update && apt install systemd-resolved -y
    
    cat > /etc/systemd/resolved.conf <<EOF
[Resolve]
DNS=8.8.8.8#dns.google 1.1.1.1#cloudflare-dns.com
DNSSEC=allow-downgrade
DNSOverTLS=yes
LLMNR=no
MulticastDNS=no
EOF

    # 净化 dhclient
    [ -f /etc/dhcp/dhclient.conf ] && sed -i '/ignore domain-name-servers/d' /etc/dhcp/dhclient.conf
    echo "ignore domain-name-servers;" >> /etc/dhcp/dhclient.conf

    systemctl enable --now systemd-resolved
    ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
    systemctl restart systemd-resolved
    log_success "DNS 净化完成，DoT 已启用。"
}

# 11. 1Panel
install_1panel() {
    echo -e "\n${GREEN}>>> 11. 安装 1Panel${PLAIN}"
    curl -sSL https://resource.1panel.pro/quick_start.sh -o quick_start.sh && bash quick_start.sh
}

# 12. NextTrace
install_nexttrace() {
    echo -e "\n${GREEN}>>> 12. 安装 NextTrace${PLAIN}"
    curl nxtrace.org/nt | bash
}

# 13. 哪吒探针优化
install_nezha() {
    echo -e "\n${GREEN}>>> 13. 安装哪吒探针 Agent${PLAIN}"
    local default_server="dashboard.7879710.xyz:443"
    local default_secret="24naSa4QDIS7kaEEtYntEKc7K84Yb31b"

    echo -e "1) 使用默认配置 (${YELLOW}$default_server${PLAIN})"
    echo -e "2) 自定义配置"
    read -p "选择 [1-2, 默认 1]: " choice
    choice=${choice:-1}

    if [[ "$choice" == "1" ]]; then
        local srv=$default_server; local sec=$default_secret; local tls="true"
    else
        read -p "服务器地址: " srv
        read -p "密钥: " sec
        read -p "启用 TLS? [Y/n]: " tls_in
        tls="true"; [[ "$tls_in" =~ ^[Nn]$ ]] && tls="false"
    fi

    [ -z "$srv" ] || [ -z "$sec" ] && { log_err "参数不全"; return; }

    log_info "下载安装脚本..."
    wget -qO /tmp/nezha_agent.sh https://raw.githubusercontent.com/nezhahq/scripts/main/agent/install.sh
    chmod +x /tmp/nezha_agent.sh
    NZ_SERVER="$srv" NZ_TLS="$tls" NZ_CLIENT_SECRET="$sec" bash /tmp/nezha_agent.sh
    rm -f /tmp/nezha_agent.sh
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