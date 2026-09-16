#!/usr/bin/env bash
# bootstrap-linux.sh — minimal manual prep before Ansible takes over
#
# Run this ONCE on the fresh Ubuntu 24.04 install as root (or with sudo -i).
# It creates the mchellmer user (matching the rest of the cluster), installs SSH,
# and places the CI Pi's public key (pi-to-midi-host) in authorized_keys.
#
# The CI Pi's key is ~/.ssh/pi-to-midi-host.pub on 1972-console-1.
# It already exists if init-pc.yaml has been run before for the Windows side.
#
# Usage:
#   sudo bash bootstrap-linux.sh "<ci-pi-pi-to-midi-host.pub contents>"
#
# To get the key from the console Pi:
#   cat ~/.ssh/pi-to-midi-host.pub    (on 1972-console-1)
#
# After this script completes:
#   1. From the console Pi: ansible -i /etc/ansible/hosts gpu_nodes -m ping
#   2. Run: cd ~/nineteenseventytwo-eightbitsaxlounge/server && make init-gpu
#      (or ansible-playbook directly — see infra/README.md)

set -euo pipefail

ANSIBLE_USER="mchellmer"   # matches the rest of the cluster
CI_PI_PUBKEY="${1:-}"

# -------------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run as root: sudo bash $0 \"<public-key>\""
    exit 1
fi

if [[ -z "$CI_PI_PUBKEY" ]]; then
    echo "WARNING: No public key provided. You must manually add the CI Pi's"
    echo "         public key to /home/$ANSIBLE_USER/.ssh/authorized_keys"
fi

# -------------------------------------------------------------------------
# Base packages
# -------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openssh-server ufw python3 python3-apt

# -------------------------------------------------------------------------
# Ansible user
# -------------------------------------------------------------------------
if ! id "$ANSIBLE_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$ANSIBLE_USER"
    echo "Created user: $ANSIBLE_USER"
else
    echo "User $ANSIBLE_USER already exists, skipping creation"
fi

# Passwordless sudo for Ansible
echo "$ANSIBLE_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ansible
chmod 440 /etc/sudoers.d/ansible

# SSH key setup
SSH_DIR="/home/$ANSIBLE_USER/.ssh"
AUTHORIZED_KEYS="$SSH_DIR/authorized_keys"

mkdir -p "$SSH_DIR"

if [[ -n "$CI_PI_PUBKEY" ]]; then
    # Append only if not already present
    if ! grep -qF "$CI_PI_PUBKEY" "$AUTHORIZED_KEYS" 2>/dev/null; then
        echo "$CI_PI_PUBKEY" >> "$AUTHORIZED_KEYS"
        echo "Added CI Pi public key to authorized_keys"
    else
        echo "CI Pi public key already present, skipping"
    fi
fi

chmod 700 "$SSH_DIR"
chmod 600 "$AUTHORIZED_KEYS"
chown -R "$ANSIBLE_USER:$ANSIBLE_USER" "$SSH_DIR"

# -------------------------------------------------------------------------
# SSH server hardening (minimal — Ansible can do more later)
# -------------------------------------------------------------------------
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
systemctl enable --now ssh

# -------------------------------------------------------------------------
# Firewall — only the minimum to allow Ansible and k3s traffic
# -------------------------------------------------------------------------
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 6443/tcp   # k3s API server
ufw allow 10250/tcp  # kubelet
ufw allow 8472/udp   # Flannel VXLAN
ufw allow 51820/udp  # WireGuard (k3s flannel-wireguard backend)
ufw --force enable

# -------------------------------------------------------------------------
# Report
# -------------------------------------------------------------------------
echo ""
echo "=== Bootstrap complete ==="
IP=$(hostname -I | awk '{print $1}')
echo "  User         : $ANSIBLE_USER"
echo "  SSH key auth : $([ -f "$AUTHORIZED_KEYS" ] && echo 'configured' || echo 'MISSING — add manually')"
echo "  IP address   : $IP  (set DHCP reservation to this MAC in Deco app)"
echo "  UFW status   : $(ufw status | head -1)"
echo ""
echo "Next steps:"
echo "  1. Set a DHCP reservation in the Deco app for this machine's Ethernet MAC -> $IP"
echo "     (same IP as Windows/midi-host so the entry in hosts is shared)"
echo "  2. From 1972-console-1: ansible -i /etc/ansible/hosts gpu_nodes -m ping"
echo "  3. Run the GPU node setup playbook (see infra/README.md in the composer repo)"
