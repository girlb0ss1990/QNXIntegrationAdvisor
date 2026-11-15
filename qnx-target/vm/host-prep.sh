#!/bin/sh
# One-time-per-boot host preparation for the QNX QEMU target (run as root: sudo host-prep.sh [user]).
# Linux and WSL2 forget both of these on restart:
#   1. the KVM module, so QEMU runs at full speed instead of emulating every instruction;
#   2. the br0 bridge with DHCP that mkqnximage's QEMU images use (via the SDP's own qemu/net.sh).
# Needs: qemu-system-x86, bridge-utils, dnsmasq (sudo apt install qemu-system-x86 bridge-utils dnsmasq).
set -u
USER_NAME=${1:-${SUDO_USER:-}}
[ "$(id -u)" = 0 ] || { echo "run as root: sudo $0" >&2; exit 1; }

# 1. KVM
if [ ! -e /dev/kvm ]; then
    if grep -qw vmx /proc/cpuinfo; then modprobe kvm_intel 2>/dev/null; else modprobe kvm_amd 2>/dev/null; fi
fi
if [ -e /dev/kvm ]; then
    getent group kvm >/dev/null || groupadd -r kvm
    chgrp kvm /dev/kvm && chmod 660 /dev/kvm
    [ -n "$USER_NAME" ] && usermod -aG kvm "$USER_NAME" 2>/dev/null
    # group membership only applies to new logins; make the device usable right away for this user
    [ -n "$USER_NAME" ] && command -v setfacl >/dev/null && setfacl -m "u:$USER_NAME:rw" /dev/kvm
    echo "kvm: ready"
else
    echo "kvm: not available (the VM will still run, but slowly). On WSL2 enable nested virtualization." >&2
fi

# 2. Networking: reuse the SDP's own helper so the setup matches what mkqnximage expects
QNX_ROOT=${QNX_HOST:-}
if [ -z "$QNX_ROOT" ] && [ -n "$USER_NAME" ]; then
    for d in /home/"$USER_NAME"/qnx*/host/linux/x86_64; do [ -d "$d" ] && QNX_ROOT=$d && break; done
fi
NET_SH=$(dirname "$QNX_ROOT")/../common/mkqnximage/qemu/net.sh
[ -f "$NET_SH" ] || NET_SH=$QNX_ROOT/../../common/mkqnximage/qemu/net.sh
QEMU=$(command -v qemu-system-x86_64) || { echo "qemu-system-x86_64 not installed" >&2; exit 1; }
HELPER=$("$QEMU" --help | grep qemu-bridge-helper | head -n 1 | sed 's/.*default=\([^)]*\)).*/\1/')
CONF=$(strings "$HELPER" | grep /bridge.conf | head -n 1)
[ -f "$NET_SH" ] || { echo "cannot find the SDP's mkqnximage/qemu/net.sh (QNX_HOST=$QNX_ROOT)" >&2; exit 1; }
PATH=$PATH:/sbin:/usr/sbin bash "$NET_SH" "$HELPER" "$CONF" nat && echo "network: br0 ready"
