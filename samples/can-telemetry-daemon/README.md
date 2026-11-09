# can-telemetry-daemon (sample)

An original, intentionally Linux-specific sample for QNX Integration Advisor demos.
Reads raw frames from SocketCAN (`can0`), keeps per-ID rates, and serves them over a
UNIX socket. Uses `epoll`, `eventfd`, `signalfd`, `/proc/self/statm`, `fork()`-style
daemonizing, `syslog` and a systemd unit.

License: MIT.
