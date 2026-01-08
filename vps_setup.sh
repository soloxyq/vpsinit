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
    
    mkdir -p ~/.ssh && chmod 700 ~/.ssh
    
    read -p "请输入 SSH 端口 (默认 22): " ssh_port
    ssh_port=${ssh_port:-22}
    
    # 修改端口逻辑优化
    sed -i '/^#\?Port /d' /etc/ssh/sshd_config
    echo "Port $ssh_port" >> /etc/ssh/sshd_config
    log_info "SSH 端口已设为: $ssh_port"

    local default_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCp3ORPYIfDP7xXP/brTqXf2RKyJ21u+fH1ffqbTEmBXvbPjIXTOlNH9c/FrPydG04D4RtbVXcL1C22ZUNWTuMcyKU8RBersn6tmzVGrG224ML9rg9uvt56gnAbenxt7haHqebBdWDsco+Er4Zie4KqviWk91C78l2Ovm4dqCwSXzI0+091DTxvRmn49gVijQV9uLACHxwFVNTGsy6nRkNO67dp3jY+4NW8+QvHE5hoxnj2pxOoPi5D5xSjoLG9+fhC1spCwAJ5bQ06SURN+beeNwUCpbm5bSRX6j6nVPNgNEaXd30+JfMxOyXwc99wLoy8jIBfqwBgAGRGnI+26qMkvaBd2XzYpv1U4pQUN2ed2gksRElSPpnJKNXfQzSsEfq4q4mK0DAtPTl+yBEdi9psOYuFCLQ9IYzgY13MRJgVgxcfbjV2So4+7zJmiLDyyrzu1kC3SvQUe1qaBLT3hxMNQ9iePn6i44LZo75EPXY42H/YZD6aduWL34qzpD2+Q3yHiCT7ADQrADg7k2yywtEduWbfOK6mc1TqftNszSKSSYlQyW2ieFex9EJvI+kRWS/cV4IuXas6JN46OIhOg+TBH1vtvUge+dE1pa+2YuCAUuhLvB9NsuVRu4qQZGZC4ZeBG3yAUmYyJczLhAWSmtdIHxLZb9wDeULK6u5wWwunMQ== soloxyq@foxmail.com"

    echo -en "${YELLOW}请输入公钥 (回车使用默认Key): ${PLAIN}"
    read -r ssh_key_input
    ssh_key=${ssh_key_input:-$default_key}

    if ! grep -q "$ssh_key" ~/.ssh/authorized_keys 2>/dev/null; then
        echo "$ssh_key" >> ~/.ssh/authorized_keys
        chmod 600 ~/.ssh/authorized_keys
        log_success "公钥已成功写入 authorized_keys"
    else
        log_info "公钥已存在，无需重复添加。"
    fi

    read -p "是否禁用密码登录 (推荐 y)? [y/N]: " disable_pwd
    if [[ "$disable_pwd" =~ ^[Yy]$ ]]; then
        sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/g' /etc/ssh/sshd_config
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config
        # 处理可能的 Include 目录
        [ -d /etc/ssh/sshd_config.d ] && echo "PasswordAuthentication no" > /etc/ssh/sshd_config.d/01-disable-password.conf
        log_info "已配置禁用密码登录。"
    fi

    log_info "正在重启 SSH 服务..."
    systemctl restart ssh || systemctl restart sshd
    log_success "SSH 配置完成！请确保能通过密钥登录后再关闭当前窗口。"
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
    [ ! -f /etc/fail2ban/jail.local ] && cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
    systemctl enable --now fail2ban
    log_success "Fail2ban 已安装并在后台保护 SSH。"
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

# 其他功能简单封装
run_external_script() {
    local name=$1; local cmd=$2
    echo -e "\n${GREEN}>>> 运行 $name${PLAIN}"
    eval "$cmd"
}

# 菜单
show_menu() {
    echo -e "
${GREEN}====================================================
       VPS 初始化工具箱 (Debian 12+ / Ubuntu 22.04+)
====================================================${PLAIN}
${GREEN} 1.${PLAIN} 配置 SSH 密钥登录 (端口/Key/禁用密码)
${GREEN} 2.${PLAIN} 安装 UFW 防火墙 (预设常用端口)
${GREEN} 3.${PLAIN} 安装 Fail2ban 防护
${GREEN} 4.${PLAIN} 设置 Swap 虚拟内存
${GREEN} 5.${PLAIN} TCP/BBR 网络优化 (高级脚本)
${GREEN} 6.${PLAIN} 系统综合测试 (NodeQuality)
${GREEN} 7.${PLAIN} 安装 VLESS 代理服务
${GREEN} 8.${PLAIN} 设置时区 (Asia/Shanghai)
${GREEN} 9.${PLAIN} 安装 Docker 环境
${GREEN}10.${PLAIN} DNS 净化与 DoT 安全加固
${GREEN}11.${PLAIN} 安装 1Panel 服务器面板
${GREEN}12.${PLAIN} 安装 NextTrace 路由追踪
${GREEN}13.${PLAIN} 安装哪吒探针 Agent
${GREEN} 0.${PLAIN} 退出
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
            5) run_external_script "BBR调优" "bash <(curl -fsSL 'https://raw.githubusercontent.com/Eric86777/vps-tcp-tune/main/install-alias.sh?$(date +%s)')" ;;
            6) run_external_script "NodeQuality测试" "bash <(curl -sL https://run.NodeQuality.com)" ;;
            7) run_external_script "VLESS安装" "wget -qO- https://raw.githubusercontent.com/Chil30/vless-all-in-one/main/vless-server.sh | bash" ;;
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
