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

# 系统检测 (简单检测是否为 Debian/Ubuntu)
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" != "debian" && "$ID" != "ubuntu" ]]; then
        echo -e "${YELLOW}警告: 此脚本主要针对 Debian/Ubuntu 设计，检测到系统为 $ID，部分功能可能无法正常工作。${PLAIN}"
        read -p "是否继续？(y/n): " confirm
        [[ "$confirm" != "y" ]] && exit 1
    fi
else
    echo -e "${YELLOW}无法检测操作系统，建议在 Debian/Ubuntu 下使用。${PLAIN}"
fi

# 1. 配置 Root 密钥登录
setup_ssh_key() {
    echo -e "${SKYBLUE}正在配置 SSH 密钥登录...${PLAIN}"
    
    # 确保 .ssh 目录存在
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh

    echo -e "${YELLOW}请输入您的 SSH 公钥 (以 ssh-rsa, ssh-ed25519 等开头):${PLAIN}"
    read -r ssh_key

    if [[ -z "$ssh_key" ]]; then
        echo -e "${RED}未输入公钥，跳过配置。${PLAIN}"
        return
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
        echo -e "${YELLOW}保留密码登录。${PLAIN}"
    fi
}

# 2. 安装 UFW 防火墙
install_ufw() {
    echo -e "${SKYBLUE}正在安装并配置 UFW 防火墙...${PLAIN}"
    apt update
    apt install ufw -y

    read -p "请输入您的 SSH 端口 (默认 22): " ssh_port
    ssh_port=${ssh_port:-22}

    ufw allow "$ssh_port"/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    
    echo -e "${YELLOW}已预设放行端口: $ssh_port (SSH), 80 (HTTP), 443 (HTTPS)${PLAIN}"
    
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

# 5. BBR 优化
enable_bbr() {
    echo -e "${SKYBLUE}正在开启 BBR 优化...${PLAIN}"
    
    # 备份 sysctl.conf
    cp /etc/sysctl.conf /etc/sysctl.conf.bak

    # 移除旧的配置
    sed -i '/net.core.default_qdisc/d' /etc/sysctl.conf
    sed -i '/net.ipv4.tcp_congestion_control/d' /etc/sysctl.conf

    # 添加新配置
    echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
    echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf

    sysctl -p
    
    echo -e "${GREEN}BBR 优化配置已应用。验证如下:${PLAIN}"
    sysctl net.ipv4.tcp_congestion_control
}

# 菜单函数
show_menu() {
    echo -e "
${GREEN}============================================
       VPS 初始化脚本 (Debian/Ubuntu)
============================================${PLAIN}
${GREEN}1.${PLAIN} 配置 Root 密钥登录 (并可选禁用密码)
${GREEN}2.${PLAIN} 安装 UFW 防火墙 (基本安全设置)
${GREEN}3.${PLAIN} 安装 Fail2ban (防暴力破解)
${GREEN}4.${PLAIN} 设置 Swap 内存
${GREEN}5.${PLAIN} 开启 BBR 拥塞控制
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
    read -p "请输入数字选择 [0-5]: " num
    case "$num" in
        1) setup_ssh_key ;;
        2) install_ufw ;;
        3) install_fail2ban ;;
        4) setup_swap ;;
        5) enable_bbr ;;
        0) exit 0 ;;
        *) echo -e "${RED}请输入正确的数字 [0-5]${PLAIN}" ;;
    esac
    
    echo -e ""
    read -p "按回车键返回主菜单..."
done
