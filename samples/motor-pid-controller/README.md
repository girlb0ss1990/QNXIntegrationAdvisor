# motor-pid-controller (sample)

An original, intentionally Linux-specific sample for QNX Integration Advisor demos.
A 1 kHz PID loop reads an encoder over `/dev/ttyUSB0`, writes PWM through sysfs and
reloads its gains with inotify. Timing uses `timerfd` + `epoll`. A default
(non priority-inheriting) mutex is shared with a low-priority telemetry thread that
holds it while it sleeps, a classic priority-inversion setup.

License: MIT.
