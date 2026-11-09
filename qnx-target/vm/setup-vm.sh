#!/bin/sh
# Create and boot the reference QNX 8.0 QEMU target with mkqnximage, then install the agent.
# Prerequisites: QNX SDP 8.0 (source qnxsdp-env.sh), QEMU (with KVM on Linux/WSL2), an SSH key.
# Check `mkqnximage --help` for the options available in your SDP patch level.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ARCH=${ARCH:-x86_64}
VM_DIR=${VM_DIR:-$HERE/local}           # gitignored: VM images are QNX software, never commit them
SSH_PUB=${SSH_PUB:-$HOME/.ssh/id_ed25519.pub}

command -v mkqnximage >/dev/null || { echo "mkqnximage not found: source qnxsdp-env.sh" >&2; exit 1; }
[ -f "$SSH_PUB" ] || { echo "no SSH public key at $SSH_PUB (ssh-keygen -t ed25519)" >&2; exit 1; }

mkdir -p "$VM_DIR"
cd "$VM_DIR"
if [ ! -d output ]; then
    mkqnximage --type=qemu --arch="$ARCH" --ssh-ident="$SSH_PUB"
fi
mkqnximage --run=-h &
echo "waiting for the VM to get an address..."
IP=""
for _ in $(seq 1 60); do
    IP=$(mkqnximage --getip 2>/dev/null || true)
    [ -n "$IP" ] && break
    sleep 2
done
[ -n "$IP" ] || { echo "VM did not report an IP" >&2; exit 1; }
echo "$IP" > "$VM_DIR/ip"
echo "VM is at $IP (saved to $VM_DIR/ip)"
"$HERE/install-agent.sh" "$IP"
