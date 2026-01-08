#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
SKYBLUE='\033[0;36m'
PLAIN='\033[0m'

# 检查是否为 root 用户
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}错误: 必须使用 root 用户运行此脚本！${PLAIN}"
    exit 1
fi

# 系统检测 (推荐 Debian 12+ / Ubuntu 22.04+)
VERSION_WARNING=0
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" != "debian" && "$ID" != "ubuntu" ]]; then
        echo -e "${YELLOW}警告: 此脚本主要针对 Debian/Ubuntu 设计，检测到系统为 $ID${PLAIN}"
        VERSION_WARNING=1
    else
        # 检查版本号
        if [[ "$ID" == "debian" ]]; then
            # 提取 Debian 版本号 (如 12)
            VERSION_ID_NUM=$(echo "$VERSION_ID" | cut -d. -f1)
            if [[ "$VERSION_ID_NUM" -lt 12 ]]; then
                echo -e "${YELLOW}警告: 此脚本推荐 Debian 12+ 版本，当前检测到 $VERSION_ID${PLAIN}"
                echo -e "${YELLOW}部分功能可能无法正常工作，请确认是否继续。${PLAIN}"
                VERSION_WARNING=1
            fi
        elif [[ "$ID" == "ubuntu" ]]; then
            VERSION_ID_NUM=$(echo "$VERSION_ID" | cut -d. -f1)
            if [[ "$VERSION_ID_NUM" -lt 22 ]]; then
                echo -e "${YELLOW}警告: 此脚本推荐 Ubuntu 22.04+ 版本，当前检测到 $VERSION_ID${PLAIN}"
                echo -e "${YELLOW}部分功能可能无法正常工作，请确认是否继续。${PLAIN}"
                VERSION_WARNING=1
            fi
        fi
        
        if [[ "$VERSION_WARNING" -eq 0 ]]; then
            echo -e "${GREEN}检测到系统: $PRETTY_NAME (版本兼容)${PLAIN}"
        fi
    fi
else
    echo -e "${YELLOW}无法检测操作系统版本，请确保使用 Debian 12+ 或 Ubuntu 22.04+${PLAIN}"
    VERSION_WARNING=1
fi

if [[ "$VERSION_WARNING" -eq 1 ]]; then
    read -p "是否继续运行脚本? [y/n]: " confirm
    [[ "$confirm" != "y" ]] && exit 1
fi

# 1. 配置 Root 密钥登录
setup_ssh_key() {
    echo -e "${SKYBLUE}正在配置 SSH 密钥登录...${PLAIN}"
    
    # 确保 .ssh 目录存在
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    
    # 交互式询问 SSH 端口
    read -p "请输入 SSH 端口 (默认 22): " ssh_port_input
    ssh_port=${ssh_port_input:-22}
    
    # 修改 sshd_config 中的端口配置
    if grep -q "^Port" /etc/ssh/sshd_config; then
        sed -i "s/^Port.*/Port $ssh_port/g" /etc/ssh/sshd_config
    else
        # 如果配置文件里没有 Port 这一行，则添加
        echo "Port $ssh_port" >> /etc/ssh/sshd_config
    fi
    echo -e "${GREEN}SSH 端口已配置为: $ssh_port${PLAIN}"

    # 默认公钥
    default_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCp3ORPYIfDP7xXP/brTqXf2RKyJ21u+fH1ffqbTEmBXvbPjIXTOlNH9c/FrPydG04D4RtbVXcL1C22ZUNWTuMcyKU8RBersn6tmzVGrG224ML9rg9uvt56gnAbenxt7haHqebBdWDsco+Er4Zie4KqviWk91C78l2Ovm4dqCwSXzI0+091DTxvRmn49gVijQV9uLACHxwFVNTGsy6nRkNO67dp3jY+4NW8+QvHE5hoxnj2pxOoPi5D5xSjoLG9+fhC1spCwAJ5bQ06SURN+beeNwUCpbm5bSRX6j6nVPNgNEaXd30+JfMxOyXwc99wLoy8jIBfqwBgAGRGnI+26qMkvaBd2XzYpv1U4pQUN2ed2gksRElSPpnJKNXfQzSsEfq4q4mK0DAtPTl+yBEdi9psOYuFCLQ9IYzgY13MRJgVgxcfbjV2So4+7zJmiLDyyrzu1kC3SvQUe1qaBLT3hxMNQ9iePn6i44LZo75EPXY42H/YZD6aduWL34qzpD2+Q3yHiCT7ADQrADg7k2yywtEduWbfOK6mc1TqftNszSKSSYlQyW2ieFex9EJvI+kRWS/cV4IuXas6JN46OIhOg+TBH1vtvUge+dE1pa+2YuCAUuhLvB9NsuVRu4qQZGZC4ZeBG3yAUmYyJczLhAWSmtdIHxLZb9wDeULK6u5wWwunMQ== soloxyq@foxmail.com"

    echo -e "${YELLOW}请输入您的 SSH 公钥 (直接回车将使用默认预置公钥):${PLAIN}"
    read -r ssh_key_input

    if [[ -z "$ssh_key_input" ]]; then
        ssh_key="$default_key"
        echo -e "${GREEN}使用预置默认公钥。${PLAIN}"
    else
        ssh_key="$ssh_key_input"
    fi

    # 写入 authorized_keys
    echo "$ssh_key" >> ~/.ssh/authorized_keys
    chmod 600 ~/.ssh/authorized_keys
    echo -e "${GREEN}公钥已添加。${PLAIN}"

    # 询问是否禁用密码登录
    read -p "是否禁用 SSH 密码登录 (提高安全性)? [y/n]: " disable_pwd
    if [[ "$disable_pwd" == "y" ]]; then
        sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/g' /etc/ssh/sshd_config
        sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config
        # 针对某些云厂商的配置
        if [ -d /etc/ssh/sshd_config.d ]; then
             echo "PasswordAuthentication no" > /etc/ssh/sshd_config.d/disable_password.conf
        fi
        
        systemctl restart ssh
        systemctl restart sshd
        echo -e "${GREEN}密码登录已禁用，SSH 服务已重启。请确保您可以使用密钥登录！${PLAIN}"
    else
        echo -e "${YELLOW}保留密码登录。SSH 服务重启以应用端口变更...${PLAIN}"
        systemctl restart ssh
        systemctl restart sshd
    fi
}

# 2. 安装 UFW 防火墙
install_ufw() {
    echo -e "${SKYBLUE}正在安装并配置 UFW 防火墙...${PLAIN}"
    apt update
    apt install ufw -y

    # 尝试从 sshd_config 获取当前 SSH 端口，默认为 22
    ssh_port_current=$(grep "^Port" /etc/ssh/sshd_config | head -n 1 | awk '{print $2}')
    ssh_port=${ssh_port_current:-22}
    
    echo -e "${YELLOW}检测到 SSH 端口为: $ssh_port (若检测失败则默认为 22)${PLAIN}"
    read -p "请输入要放行的 SSH 端口 (默认 $ssh_port): " ufw_ssh_port
    ufw_ssh_port=${ufw_ssh_port:-$ssh_port}

    ufw allow "$ufw_ssh_port"/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 16790:16799/tcp
    ufw allow 16790:16799/udp
    
    echo -e "${YELLOW}已预设放行端口: $ufw_ssh_port (SSH), 80, 443, 16790-16799 (TCP/UDP)${PLAIN}"
    
    read -p "是否启用 UFW? (这可能会断开当前的 SSH 连接，如果端口配置错误) [y/n]: " enable_ufw
    if [[ "$enable_ufw" == "y" ]]; then
        echo "y" | ufw enable
        echo -e "${GREEN}UFW 已启用。${PLAIN}"
        ufw status
    fi
}

# 3. 安装 Fail2ban
install_fail2ban() {
    echo -e "${SKYBLUE}正在安装 Fail2ban...${PLAIN}"
    apt update
    apt install fail2ban -y
    
    # 复制默认配置
    if [ ! -f /etc/fail2ban/jail.local ]; then
        cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
        echo -e "${GREEN}已创建 jail.local 配置文件。${PLAIN}"
    fi

    systemctl enable fail2ban
    systemctl start fail2ban
    echo -e "${GREEN}Fail2ban 安装并启动成功。${PLAIN}"
    systemctl status fail2ban --no-pager | head -n 10
}

# 4. 设置 Swap 内存
setup_swap() {
    echo -e "${SKYBLUE}正在设置 Swap 内存...${PLAIN}"
    
    current_swap=$(free -m | grep Swap | awk '{print $2}')
    if [[ "$current_swap" -gt 0 ]]; then
        echo -e "${YELLOW}检测到系统已有 Swap: ${current_swap}MB。是否重新设置？[y/n]${PLAIN}"
        read -r reset_swap
        if [[ "$reset_swap" != "y" ]]; then
            return
        fi
        # 关闭现有 swap (如果是文件)
        swapoff -a
        sed -i '/swap/d' /etc/fstab
        rm -f /swapfile
        echo -e "${YELLOW}旧 Swap 已清除。${PLAIN}"
    fi

    read -p "请输入 Swap 大小 (单位 MB, 例如 1024): " swap_size
    if [[ ! "$swap_size" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}请输入有效的数字！${PLAIN}"
        return
    fi

    echo -e "正在创建 /swapfile ..."
    dd if=/dev/zero of=/swapfile bs=1M count="$swap_size"
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    
    # 写入 fstab
    echo "/swapfile swap swap defaults 0 0" >> /etc/fstab
    
    echo -e "${GREEN}Swap 设置成功！${PLAIN}"
    free -h
}

# 5. BBR 优化 (高级脚本)
enable_bbr() {
    echo -e "${SKYBLUE}正在启动高级 TCP/BBR 调优脚本 (Eric86777)...${PLAIN}"
    echo -e "${YELLOW}提示: 该脚本可能包含独立的菜单。${PLAIN}"
    bash <(curl -fsSL "https://raw.githubusercontent.com/Eric86777/vps-tcp-tune/main/install-alias.sh?$(date +%s)")
}

# 6. NodeQuality 系统测试
run_nq_test() {
    echo -e "${SKYBLUE}正在运行 NodeQuality 系统综合测试...${PLAIN}"
    bash <(curl -sL https://run.NodeQuality.com)
}

# 7. 安装 VLESS 代理服务
install_vless() {
    echo -e "${SKYBLUE}正在下载并运行 VLESS All-in-One 脚本...${PLAIN}"
    # 下载到临时目录或当前目录均可，这里为了保持干净下载到 /tmp 并执行
    wget -O /tmp/vless-server.sh https://raw.githubusercontent.com/Chil30/vless-all-in-one/main/vless-server.sh
    if [ $? -eq 0 ]; then
        chmod +x /tmp/vless-server.sh
        bash /tmp/vless-server.sh
    else
        echo -e "${RED}下载 VLESS 脚本失败，请检查网络连接。${PLAIN}"
    fi
}

# 8. 设置时区
setup_timezone() {
    echo -e "${SKYBLUE}正在设置时区为 Asia/Shanghai...${PLAIN}"
    timedatectl set-timezone Asia/Shanghai
    echo -e "${GREEN}当前时间: $(date -R)${PLAIN}"
}

# 9. 安装 Docker
install_docker() {
    echo -e "${SKYBLUE}正在安装 Docker...${PLAIN}"
    if command -v docker >/dev/null 2>&1; then
        echo -e "${YELLOW}Docker 已安装。${PLAIN}"
    else
        curl -fsSL https://get.docker.com | bash
        systemctl start docker
        systemctl enable docker
        echo -e "${GREEN}Docker 安装完成。${PLAIN}"
    fi
}

# 10. DNS 净化与安全加固
purify_dns() {
    echo -e "${SKYBLUE}正在执行 DNS 净化与安全加固...${PLAIN}"
    
    # 目标 DNS
    TARGET_DNS="8.8.8.8#dns.google 1.1.1.1#cloudflare-dns.com"
    SECURE_RESOLVED_CONFIG="[Resolve]
DNS=${TARGET_DNS}
LLMNR=no
MulticastDNS=no
DNSSEC=allow-downgrade
DNSOverTLS=yes/opportunistic
"

    # 1. 净化 dhclient
    local dhclient_conf="/etc/dhcp/dhclient.conf"
    if [[ -f "$dhclient_conf" ]]; then
        if ! grep -q "ignore domain-name-servers;" "$dhclient_conf"; then
            echo "" >> "$dhclient_conf"
            echo "ignore domain-name-servers;" >> "$dhclient_conf"
            echo "ignore domain-search;" >> "$dhclient_conf"
            echo -e "${GREEN}已修正 dhclient 配置。${PLAIN}"
        fi
    fi
    
    # 2. 移除 if-up.d 冲突脚本
    local ifup_script="/etc/network/if-up.d/resolved"
    if [[ -f "$ifup_script" ]] && [[ -x "$ifup_script" ]]; then
        chmod -x "$ifup_script"
        echo -e "${GREEN}已禁用冲突的 if-up.d/resolved 脚本。${PLAIN}"
    fi

    # 3. 净化 /etc/network/interfaces
    local interfaces_file="/etc/network/interfaces"
    if [[ -f "$interfaces_file" ]]; then
        sed -i -E 's/^[[:space:]]*(dns-(nameservers|search|domain).*)/# \1/' "$interfaces_file"
    fi

    # 4. 配置 systemd-resolved
    apt-get install -y systemd-resolved > /dev/null 2>&1
    systemctl enable systemd-resolved
    systemctl start systemd-resolved
    
    echo -e "$SECURE_RESOLVED_CONFIG" > /etc/systemd/resolved.conf
    ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
    systemctl restart systemd-resolved
    
    echo -e "${GREEN}DNS 净化完成。当前状态：${PLAIN}"
    resolvectl status | grep "DNS Servers"
}

# 11. 安装 1Panel 面板
install_1panel() {
    echo -e "${SKYBLUE}正在安装 1Panel 面板...${PLAIN}"
    curl -sSL https://resource.1panel.pro/quick_start.sh -o quick_start.sh && bash quick_start.sh
}

# 12. 安装 NextTrace
install_nexttrace() {
    echo -e "${SKYBLUE}正在安装 NextTrace...${PLAIN}"
    curl nxtrace.org/nt | bash
}

# 13. 安装哪吒探针 Agent
install_nezha() {
    echo -e "${SKYBLUE}正在准备安装哪吒探针 (Nezha Agent)...${PLAIN}"
    
    # 默认配置
    DEFAULT_SERVER="dashboard.7879710.xyz:443"
    DEFAULT_SECRET="24naSa4QDIS7kaEEtYntEKc7K84Yb31b"
    DEFAULT_TLS="true"
    
    echo -e "请选择安装模式:"
    echo -e "1) 使用默认配置 (${YELLOW}$DEFAULT_SERVER${PLAIN})"
    echo -e "2) 自定义配置 (手动输入服务器地址和密钥)"
    read -p "请输入 [1-2] (默认 1): " choice
    choice=${choice:-1}
    
    local server
    local secret
    local tls

    if [[ "$choice" == "1" ]]; then
        server="$DEFAULT_SERVER"
        secret="$DEFAULT_SECRET"
        tls="$DEFAULT_TLS"
    else
        read -p "请输入面板服务器地址 (例如 dashboard.example.com:443): " server
        read -p "请输入 Agent 密钥 (Secret): " secret
        read -p "是否启用 TLS? [y/n] (默认 y): " tls_input
        if [[ "$tls_input" == "n" ]]; then
            tls="false"
        else
            tls="true"
        fi
        
        if [[ -z "$server" || -z "$secret" ]]; then
            echo -e "${RED}服务器地址或密钥不能为空！${PLAIN}"
            return
        fi
    fi
    
    echo -e "${GREEN}正在安装 Agent...${PLAIN}"
    echo -e "Server: $server"
    echo -e "TLS: $tls"
    
    curl -L https://raw.githubusercontent.com/nezhahq/scripts/main/agent/install.sh -o /tmp/nezha_install.sh && chmod +x /tmp/nezha_install.sh
    if [ $? -eq 0 ]; then
        # 执行安装
        env NZ_SERVER="$server" NZ_TLS="$tls" NZ_CLIENT_SECRET="$secret" bash /tmp/nezha_install.sh
        rm -f /tmp/nezha_install.sh
    else
         echo -e "${RED}下载哪吒探针安装脚本失败，请检查网络连接。${PLAIN}"
    fi
}

# 菜单函数
show_menu() {
    echo -e "
${GREEN}============================================
       VPS 初始化脚本 (Debian 12+ / Ubuntu 22.04+)
         仅支持 Debian 12 及以上版本
============================================${PLAIN}
${GREEN}1.${PLAIN} 配置 Root 密钥登录 (默认端口与公钥)
${GREEN}2.${PLAIN} 安装 UFW 防火墙 (预设端口开放)
${GREEN}3.${PLAIN} 安装 Fail2ban (防暴力破解)
${GREEN}4.${PLAIN} 设置 Swap 内存
${GREEN}5.${PLAIN} TCP/BBR 网络调优 (高级脚本)
${GREEN}6.${PLAIN} 系统综合测试 (NodeQuality)
${GREEN}7.${PLAIN} 安装 VLESS 代理服务
${GREEN}8.${PLAIN} 设置时区 (Asia/Shanghai)
${GREEN}9.${PLAIN} 安装 Docker 环境
${GREEN}10.${PLAIN} DNS 净化与安全加固 (Google/CF DNS)
${GREEN}11.${PLAIN} 安装 1Panel 服务器面板
${GREEN}12.${PLAIN} 安装 NextTrace 路由追踪
${GREEN}13.${PLAIN} 安装哪吒探针 Agent (默认/自定义)
${GREEN}0.${PLAIN} 退出脚本
"
}

# 检查并设置别名
setup_alias() {
    # 动态获取当前脚本的绝对路径
    local script_path
    script_path=$(readlink -f "${BASH_SOURCE[0]}")
    
    local alias_cmd="alias xqvinit='$script_path'"
    local added=0

    # 检查 .bashrc
    if [ -f ~/.bashrc ] && ! grep -q "alias xqvinit=" ~/.bashrc; then
        echo "" >> ~/.bashrc
        echo "# VPS Setup Alias" >> ~/.bashrc
        echo "$alias_cmd" >> ~/.bashrc
        added=1
    fi

    # 检查 .zshrc
    if [ -f ~/.zshrc ] && ! grep -q "alias xqvinit=" ~/.zshrc; then
        echo "" >> ~/.zshrc
        echo "# VPS Setup Alias" >> ~/.zshrc
        echo "$alias_cmd" >> ~/.zshrc
        added=1
    fi

    if [[ $added -eq 1 ]]; then
        echo -e "${GREEN}已为您创建别名命令: xqvinit${PLAIN}"
        echo -e "${YELLOW}指向路径: $script_path${PLAIN}"
        echo -e "${YELLOW}请执行 'source ~/.zshrc' (或 ~/.bashrc) 或重新登录后直接使用 'xqvinit' 运行本脚本。${PLAIN}"
    fi
}

# 主逻辑
setup_alias

while true; do
    show_menu
    read -p "请输入数字选择 [0-13]: " num
    case "$num" in
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
        *) echo -e "${RED}请输入正确的数字 [0-13]${PLAIN}" ;;
    esac
    
    echo -e ""
    read -p "按回车键返回主菜单..."
done