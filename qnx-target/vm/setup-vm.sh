#!/bin/sh
# Create (first time) and boot the reference QNX 8.0 QEMU target with mkqnximage, then install the agent.
# Safe to run again: an already-running VM is reused, an existing image is not rebuilt.
# Prerequisites: QNX SDP 8.0 (source qnxsdp-env.sh), QEMU, an SSH key, and once per host boot:
#   sudo qnx-target/vm/host-prep.sh      (KVM + the br0 bridge; forgotten when Linux/WSL restarts)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ARCH=${ARCH:-x86_64}
# VM images are QNX software: they live outside the repository (and outside any synced folder).
VM_DIR=${VM_DIR:-${QNX_ADVISOR_VM_DIR:-$HOME/.qnx-advisor/vm}}
SSH_PUB=${SSH_PUB:-$HOME/.ssh/id_ed25519.pub}
export MKQNXIMAGE_NOPROMPT=1            # never stop to ask for a sudo password

command -v mkqnximage >/dev/null || { echo "mkqnximage not found: source ~/qnx800/qnxsdp-env.sh" >&2; exit 1; }
if [ ! -f "$SSH_PUB" ]; then
    echo "no SSH key yet: creating one at ${SSH_PUB%.pub}"
    mkdir -p "$(dirname "$SSH_PUB")" && ssh-keygen -q -t ed25519 -N "" -f "${SSH_PUB%.pub}"
fi
if ! ip link show br0 >/dev/null 2>&1 && ! ip link show virbr0 >/dev/null 2>&1; then
    echo "QEMU networking is not set up. Run once (needs your password):  sudo $HERE/host-prep.sh $(id -un)" >&2
    exit 2
fi
[ -w /dev/kvm ] || echo "note: KVM is not available, the VM will run slowly (sudo $HERE/host-prep.sh $(id -un))"

mkdir -p "$VM_DIR"
cd "$VM_DIR"
if [ ! -d output ]; then
    echo "building the QNX 8.0 image (first time only, about a minute)..."
    mkqnximage --type=qemu --arch="$ARCH" --ssh-ident="$SSH_PUB"
fi
if [ -f output/qemu.pid ] && kill -0 "$(cat output/qemu.pid)" 2>/dev/null; then
    echo "the VM is already running"
else
    echo "booting the VM..."
    nohup mkqnximage --run=-h > "$VM_DIR/run.log" 2>&1 &
fi
echo "waiting for the VM to get an address..."
IP=""
for _ in $(seq 1 60); do
    IP=$(mkqnximage --getip 2>/dev/null || true)
    [ -n "$IP" ] && ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new \
        qnxuser@"$IP" true 2>/dev/null && break
    IP=""
    sleep 2
done
[ -n "$IP" ] || { echo "the VM did not come up; see $VM_DIR/run.log and $VM_DIR/output/qemu.out" >&2; exit 1; }
echo "$IP" > "$VM_DIR/ip"
echo "VM is at $IP (saved to $VM_DIR/ip)"
"$HERE/install-agent.sh" "$IP"
echo "READY qnxuser@$IP"
