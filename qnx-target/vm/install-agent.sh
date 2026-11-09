#!/bin/sh
# Build the agent with qcc, copy it to the target and start it.
#   install-agent.sh <ip> [arch]
# The agent must start as root (to register /dev/advisor); it then drops to uid 1000.
set -eu

IP=${1:?usage: install-agent.sh <ip> [x86_64|aarch64le]}
ARCH=${2:-x86_64}
HERE=$(cd "$(dirname "$0")/.." && pwd)
SSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

make -C "$HERE" ARCH="$ARCH"
scp -o StrictHostKeyChecking=accept-new "$HERE/build/$ARCH/qnx-advisor-agent" "$HERE/build/$ARCH/advisorctl" \
    qnxuser@"$IP":/data/home/qnxuser/

# advisorctl must be on qnxuser's PATH for the host tool.
$SSH qnxuser@"$IP" 'mkdir -p /data/home/qnxuser/bin && mv -f /data/home/qnxuser/advisorctl /data/home/qnxuser/bin/ \
    && grep -q "qnxuser/bin" /data/home/qnxuser/.profile 2>/dev/null || echo "export PATH=/data/home/qnxuser/bin:\$PATH" >> /data/home/qnxuser/.profile'

# Start the agent as root (key-based root login is set up by mkqnximage --ssh-ident in the
# default images; otherwise log in and run the same command with su).
$SSH root@"$IP" 'slay -f qnx-advisor-agent 2>/dev/null; /data/home/qnxuser/qnx-advisor-agent -u 1000 -d' \
    || echo "could not start the agent as root; run on the target: su -c '/data/home/qnxuser/qnx-advisor-agent -u 1000 -d'"

$SSH qnxuser@"$IP" 'PATH=/data/home/qnxuser/bin:$PATH advisorctl info'
