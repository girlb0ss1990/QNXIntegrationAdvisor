# QNX 8.0 Integration Report: samples/vitals-monitor

Commit `local` · mode M1 · SDP 8.0.0 · generated 2026-11-11T23:31:24Z

**Readiness score: 19/100** (score = max(0, 100 - sum(weight(severity) x min(hits, 3))); blocker 15, high 6, medium 2, low 1; guarded findings weigh 0)

12 finding(s) across 4 file(s): 1 blocker, 3 high, 5 medium, 1 low, 2 info. 3 rule(s) depend on APIs missing from your QNX SDP 8.0.0 sysroot. Detected roles: device service, periodic control loop, daemon, ipc server. Recommended shape on QNX: a /dev/vitals_monitor resource manager driven by a pulse timer. Readiness score 19/100 (deterministic formula).

## Compatibility audit

| Severity | Rule | Sysroot | Locations | Guidance |
| :--- | :--- | :--- | :--- | :--- |
| blocker | LNX-I2C Linux i2c-dev | missing | `src/vitals.c:25`, `src/vitals.c:40` | QNX I2C controllers are served by board-specific resource-manager drivers controlled with devctl() (see <hw/i2c.h> in your SDP for the command set). Wrap sensor access in a HAL and implement the QNX side against your board's I2C driver. |
| high | LNX-EVENTFD eventfd notifier | missing | `src/vitals.c:14`, `src/vitals.c:114` | eventfd is used here as a thread-to-loop wake-up. On QNX a pulse sent to the loop's channel does the same job without a file descriptor, and carries a code and a value. A pipe is the portable fallback. |
| high | LNX-PRCTL-CAPS Root-only daemon / Linux capabilities | available | `src/vitals.c:17`, `src/vitals.c:102`, `src/vitals.c:106`, `src/vitals.c:107` | QNX splits root's power into abilities. Start as root only long enough to do the privileged setup (for example registering a path name), then call procmgr_ability() to keep just the abilities you need, lock the rest, and switch to an unprivileged user. A secpol policy can express the same thing declaratively. |
| high | LNX-SYSFS Linux /sys paths | available | `src/vitals.c:56` | There is no sysfs on QNX. PWM, GPIO and thermal data come from board-specific resource managers. Hide these behind a HAL and implement the QNX backend for your board's drivers. |
| medium | BLD-COMPILER Host-only compiler settings | available | `CMakeLists.txt:5`, `CMakeLists.txt:7` | Cross-compile with qcc/q++ and a -V variant (gcc_ntox86_64, gcc_ntoaarch64le). Remove host-only flags such as -march=native and hardcoded gcc, and do not fail the build when CMAKE_SYSTEM_NAME is not Linux. The kit's toolchain file sets all of this. |
| medium | LNX-FORK fork() in a multithreaded program | available | `src/vitals.c:87` | posix_spawn() is the recommended way to start processes on QNX. fork() in a multithreaded program is unsafe under POSIX on any OS, because only the calling thread is copied and locks held by other threads stay locked in the child. |
| medium | LNX-IOCTL ioctl on device descriptors | available | `src/vitals.c:40` | QNX offers ioctl() as a wrapper over devctl() for common requests, but driver-specific requests must be rewritten against the QNX driver's DCMD_* set. Wrap device access in a small hardware-abstraction layer (HAL) so the Linux and QNX implementations can live side by side. |
| medium | LNX-LIBS Linux-only link libraries | missing | `CMakeLists.txt:13` | On QNX the pthread, real-time and dynamic-loading functions are part of libc. Drop a -l flag only if that library is missing from the sysroot (the audit checks this). In CMake prefer find_package(Threads) + Threads::Threads. |
| medium | LNX-SYSTEMD systemd unit / watchdog script | available | `scripts/vitals-watchdog.sh:1`, `vitals-monitor.service:1` | QNX targets have no systemd. Start the service from the image's startup script (or SLM where available), daemonize with procmgr_daemon(), and supervise daemon processes using procmgr_event_notify_add(PROCMGR_EVENT_DAEMON_DEATH, ...) (or HAM where the optional High Availability package is installed). |
| low | LNX-PERIODIC-SLEEP sleep-based periodic loop | available | `src/vitals.c:79` | A relative sleep inside a loop drifts by the loop body's run time. Use clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ...) with a running deadline, or a pulse timer when the thread also needs to receive other events. |
| info | LNX-LOG syslog logging | available | `src/vitals.c:39`, `src/vitals.c:40`, `src/vitals.c:100` | syslog() works on QNX. slog2 (slog2_register, slog2f) is recommended for structured, low-overhead logs that you can read with slog2info. |
| info | LNX-SHM POSIX shared memory | available | `src/vitals.c:109` | shm_open()/mmap() work on QNX. For memory shared with devices or across a hypervisor boundary, look at typed memory (posix_typed_mem_open). Keep the shared struct layout fixed-size and guard it with a process-shared, priority-inheriting mutex. |

## Why QNX?

**Strong fit: vitals_monitor does the kind of real-time, device or service work QNX is built for.**

### Predictable timing for time-critical work (high evidence)

QNX capability: Hard real-time, priority-preemptive scheduling

vitals_monitor has timing-sensitive code (a periodic control loop; sleep-based periodic loop in src/vitals.c:79). On a general-purpose Linux kernel, exactly when that code runs depends on everything else the system is doing. QNX is a hard real-time OS: the highest-priority ready thread always runs, timers can deliver a pulse straight to the waiting thread, mutexes and message passing use priority inheritance, and run-masks can keep a core free for the critical thread, so timing stays predictable when the system is busy.

Evidence: `src/vitals.c:79`

### A driver or service crash does not take the system down (high evidence)

QNX capability: Microkernel architecture with user-space drivers

vitals_monitor works with hardware (opens Linux device files under /dev; Linux i2c-dev in src/vitals.c:25). On Linux, device drivers run inside the kernel, so a driver bug can bring down the whole machine. In QNX the kernel only schedules, passes messages and handles interrupts; drivers and services such as vitals_monitor run as ordinary processes with their own memory protection. If one fails, the kernel and the other processes keep running and the failed process can be restarted.

Evidence: `src/vitals.c:25`

### Automatic detection and restart when a process dies (high evidence)

QNX capability: Process-manager death notifications (and HAM where installed)

vitals_monitor relies on Linux supervision (runs as a background daemon; systemd unit / watchdog script in scripts/vitals-watchdog.sh:1; fork() in a multithreaded program in src/vitals.c:87). On QNX a small guardian can register for PROCMGR_EVENT_DAEMON_DEATH and receive a kernel pulse the moment the daemon exits, then restart it with posix_spawn(); because services are isolated processes, restarting one does not disturb the others.

Evidence: `scripts/vitals-watchdog.sh:1`, `src/vitals.c:87`

### Run without full root rights (high evidence)

QNX capability: Fine-grained process abilities and security policies

vitals_monitor currently needs elevated rights (root-only daemon / Linux capabilities in src/vitals.c:17; POSIX shared memory in src/vitals.c:109). QNX splits root's power into individual abilities (for example: create a /dev entry, raise thread priority, map physical memory). With procmgr_ability() the service keeps only the abilities it needs, locks them, and then runs as a normal user; secpol policies can enforce the same rules system-wide. A compromised service can then do far less damage.

Evidence: `src/vitals.c:17`, `src/vitals.c:109`

### Fast, priority-aware communication between processes (high evidence)

QNX capability: Synchronous message passing as the core of the OS

vitals_monitor coordinates work through Linux event and IPC mechanisms (serves other processes (Unix sockets, message queues or shared memory); eventfd notifier in src/vitals.c:14; POSIX shared memory in src/vitals.c:109). In QNX, message passing is how the whole OS works: a client's MsgSend() copies data directly into the server, blocks until the reply, and the server temporarily runs at the client's priority. Clients can also simply open() and read() a /dev/vitals_monitor path. This gives one consistent, priority-aware way to talk between components.

Evidence: `src/vitals.c:14`, `src/vitals.c:109`

### A path to functional-safety certification (high evidence)

QNX capability: Safety-certified QNX OS variant available

vitals_monitor looks like embedded control or device software (a periodic control loop; opens Linux device files under /dev; Linux i2c-dev in src/vitals.c:25). If it ever has to meet a functional safety standard (automotive, industrial or medical), QNX offers a safety-certified variant of the OS, which removes a large part of the work compared with arguing the safety of a general-purpose kernel. Your own application still needs its own safety process.

Evidence: `src/vitals.c:25`

### See exactly what the system did, and when (low evidence)

QNX capability: Kernel event tracing and structured system logging

vitals_monitor relies on Linux logging or /proc inspection (syslog logging in src/vitals.c:39; sleep-based periodic loop in src/vitals.c:79). QNX's tracelogger records kernel events (thread switches, messages, interrupts) with timestamps, which shows exactly why a deadline was missed; slog2 gives fast, structured logs that stay readable after a crash.

Evidence: `src/vitals.c:39`, `src/vitals.c:79`

### Most of the code carries over (low evidence)

QNX capability: POSIX-compliant OS

QNX implements the POSIX APIs this code already relies on (threads, timers, sockets, files), so the port is about the Linux-only parts listed in the audit rather than a rewrite. The audit found 12 Linux-specific pattern(s) across 4 file(s); the readiness score is 19/100.

Things to keep in mind:

- Porting effort: 4 blocker/high finding(s) need code changes first (see the Audit tab and the step-by-step guide).
- Hardware access depends on your board's QNX drivers: CAN, I2C and SPI interfaces differ from Linux.
- These are capabilities QNX provides, not measurements. Use the Verify tab on a QNX target before relying on timing.


## Pillar 1: Relevant QNX features

### resource manager (relevance 5/5) ✓ sysroot

Component: `src/vitals.c`

`src/vitals.c` owns a device and a processing loop. On QNX that is naturally a resource manager: it registers /dev/vitals_monitor in the path space, clients use plain open/read/ write/devctl, and every request arrives as a message that inherits the client's priority. Device access moves out of client code into one process that can be restarted on its own.

APIs: `dispatch_create`, `iofunc_func_init`, `iofunc_attr_init`, `resmgr_attach`, `dispatch_context_alloc`, `dispatch_block`, `dispatch_handler`, `iofunc_devctl_default`

```mermaid
flowchart LR
  C1["client: open + devctl"] -->|"MsgSend, client priority"| R["/dev/vitals_monitor resource manager"]
  T["timer pulse"] --> R
  R --> D["device driver resmgr"]
```

### channels pulses (relevance 4/5) ✓ sysroot

Component: `src/vitals.c`

`src/vitals.c` multiplexes timers, notifications and I/O in a Linux event loop. A QNX channel replaces it: each source sends a pulse with its own code and priority, and a single receive call hands them to the thread in priority order.

APIs: `ChannelCreate`, `ConnectAttach`, `MsgReceivePulse`, `MsgSendPulse`, `timer_create`, `SIGEV_PULSE_INIT`

```mermaid
flowchart LR
  TM["timer_create, SIGEV_PULSE"] -->|"code TIMER, prio 30"| CH(("channel"))
  W["worker thread"] -->|"MsgSendPulse, code FLUSH"| CH
  IO["ionotify on fd"] -->|"code IO"| CH
  CH --> L["MsgReceivePulse loop"]
```

### procmgr ability (relevance 4/5) ✓ sysroot

Component: `src/vitals.c`

`src/vitals.c` runs as root throughout. procmgr_ability() keeps only the abilities the service still needs after start-up and locks the rest before dropping to a service user.

APIs: `procmgr_ability`, `setuid`

### secpol (relevance 4/5) ✓ sysroot

Component: `src/vitals.c`

The same least-privilege intent can be written as a secpol policy for vitals_monitor, so the system integrator controls abilities without changing code.

### ham (relevance 3/5) ✓ sysroot

Component: `scripts/vitals-watchdog.sh`

`scripts/vitals-watchdog.sh` relies on systemd or scripts for restarts. On QNX 8.0, procmgr_daemon() and procmgr_event_notify_add(PROCMGR_EVENT_DAEMON_DEATH) notify a guardian via kernel pulse immediately on process termination (or use HAM when the optional HA package is installed).

APIs: `procmgr_daemon`, `procmgr_event_notify_add`, `PROCMGR_EVENT_DAEMON_DEATH`, `posix_spawn`, `waitid`

```mermaid
flowchart LR
  S["vitals_monitor daemon"] -->|"PROCMGR_EVENT_DAEMON_DEATH pulse"| G["procmgr / guardian"]
  G -->|"posix_spawn restart"| S
```

### tracelogger (relevance 2/5) ✓ sysroot

Component: `src/vitals.c`

Capture a kernel event trace with tracelogger while vitals_monitor runs and inspect scheduling, IPC and interrupts in the System Profiler (Momentics or the VS Code QNX Toolkit) to confirm the timing behaviour after porting.

### slog2 (relevance 1/5) ✓ sysroot

Component: `src/vitals.c`

`src/vitals.c` logs through syslog. slog2 gives per-buffer verbosity and very low overhead in time-critical paths, and slog2info reads the buffers on the target.

APIs: `slog2_register`, `slog2f`

### typed shared memory (relevance 1/5) ✓ sysroot

Component: `src/vitals.c`

`src/vitals.c` publishes data in shared memory. POSIX shm works on QNX; typed memory is available when the region must map to specific physical memory.

APIs: `shm_open`, `mmap`, `posix_typed_mem_open`

## Pillar 2: Concrete improvements

- **maintainability portability** [static] Sensor reads use Linux i2c-dev request codes directly. → A sensor HAL isolates the bus driver; the QNX backend uses the board's I2C resource manager. (`src/vitals.c:25`, `src/vitals.c:40`)
- **ipc efficiency** [static] An eventfd wake-up carries no payload and no priority; the receiver must read shared state separately to learn what happened. → A pulse carries an 8-bit code and a 32-bit value plus the sender's priority, so the receiver knows what happened and the scheduler orders the work correctly. (`src/vitals.c:14`, `src/vitals.c:114`)
- **security least privilege** [static] The process runs with full root privileges for its whole lifetime. → procmgr_ability() keeps only the abilities the service needs and locks them, so a compromise does not yield root. (`src/vitals.c:17`, `src/vitals.c:102`, `src/vitals.c:106`)
- **fault isolation recovery** [static] Child processes are created with fork() from a threaded parent. → posix_spawn() creates the child directly and can set its scheduling policy and priority. (`src/vitals.c:87`)
- **maintainability portability** [static] Device control calls are scattered through application code and tied to Linux request codes. → A HAL with a devctl()-based QNX backend isolates board-specific commands in one file. (`src/vitals.c:40`)
- **fault isolation recovery** [static] Restart policy lives in systemd or a cron script, which QNX targets do not have. → procmgr_event_notify_add(PROCMGR_EVENT_DAEMON_DEATH) delivers a kernel pulse the instant a supervised daemon terminates so a lightweight guardian or HAM can respawn it. (`scripts/vitals-watchdog.sh:1`, `vitals-monitor.service:1`)
- **determinism latency** [static] Relative sleeps accumulate drift equal to the loop body's execution time. → Absolute-deadline sleeps or pulse timers keep the period fixed. (`src/vitals.c:79`)
- **maintainability portability** [static] Logging goes through syslog, which formats and sends each message to a daemon. → slog2 writes to a shared-memory buffer with per-buffer verbosity, viewable with slog2info. (`src/vitals.c:39`, `src/vitals.c:40`, `src/vitals.c:100`)
- **determinism latency** [qualitative] The periodic loop's wake-up lateness under background CPU load is unknown on QNX. → Run the agent's timer benchmark (1 kHz pulse timer, SCHED_FIFO) with and without low-priority load threads to measure wake-up lateness on your target.
- **fault isolation recovery** [qualitative] Device access and client handling live in one process with the application logic. → As a resource manager the service is a separate process that clients reach through open/read/devctl; it can be restarted without restarting its clients' code. The agent measures the time from spawn until /dev/<service> appears.
- **ipc efficiency** [qualitative] Clients exchange data with the service through Linux-specific mechanisms. → QNX synchronous message passing copies data directly between address spaces and inherits the client's priority. The agent's IPC benchmark measures MsgSend round trips.

## Pillar 3: Step-by-step guidance

### 1. Cross-compile with the QNX 8.0 toolchain

*toolchain_build · effort S · qcc snippet check: skipped*

Cross-compile with the kit's toolchain file (qcc/q++ with -V gcc_nto<arch>). Changes needed: Host-only compiler settings: Source qnxsdp-env.sh, then configure with the kit's toolchain file. Linux-only link libraries: Use Threads::Threads and drop -lrt/-ldl where the sysroot has no such library.

Before:

```c
add_compile_options(-O2 -Wall -march=native)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
target_link_libraries(vitals_monitor Threads::Threads rt)
```

After:

```c
# Add to vitals-monitor's CMakeLists.txt after the target "vitals_monitor" is defined:
#   include(cmake/qnx8.cmake)

if(CMAKE_SYSTEM_NAME STREQUAL "QNX")
  target_compile_definitions(vitals_monitor PRIVATE _QNX_SOURCE)
  target_include_directories(vitals_monitor PRIVATE ${CMAKE_CURRENT_LIST_DIR}/../include)
  # These libraries do not exist in your QNX sysroot (their functions are in libc):
  #   rt  -> remove them from target_link_libraries for QNX builds.
endif()
```

Verify: `cmake -B build-qnx -DCMAKE_TOOLCHAIN_FILE=cmake/qnx8-toolchain.cmake -DQNX_ARCH=x86_64 && cmake --build build-qnx`

### 2. Put I2C access behind a sensor HAL

*api_migration · effort M · qcc snippet check: skipped*

Create sensor_hal_read(); move the i2c-dev code to sensor_hal_linux.c and add sensor_hal_qnx.c.

Before:

```c
/* src/vitals.c */
    if (fd < 0) { syslog(LOG_ERR, "open %s: %m", I2C_BUS); return -1; }
    if (ioctl(fd, I2C_SLAVE, SENSOR_ADDR) < 0) { syslog(LOG_ERR, "I2C_SLAVE: %m"); return -1; }
    return fd;
}
```

After:

```c
/* sensor_hal.h */
int sensor_hal_open(int bus, uint8_t addr);
int sensor_hal_read_regs(int h, uint8_t reg, uint8_t *buf, size_t len);
```

Verify: `qcc -Vgcc_ntox86_64 -fsyntax-only src/sensor_hal_qnx.c`

### 3. Turn eventfd wake-ups into pulses

*api_migration · effort S · qcc snippet check: skipped*

Create the notifier with the qnx_compat.h shim from the porting kit. On QNX it sends a pulse to the loop's channel; elsewhere it falls back to a pipe.

Before:

```c
/* src/vitals.c */
notify_efd = eventfd(0, 0);

int fd = sensor_open();
```

After:

```c
#include "qnx_compat.h"

qnx_notifier_t n;
qnx_notifier_init(&n, chid, PULSE_CODE_FLUSH);
qnx_notifier_signal(&n, 1);        /* MsgSendPulse under the hood */
```

Verify: `qcc -Vgcc_ntox86_64 -fsyntax-only -Iinclude src/main.c`

### 4. Remove sysfs dependencies

*api_migration · effort M · qcc snippet check: skipped*

Wrap each sysfs access (PWM, thermal, GPIO) in a HAL function.

Before:

```c
/* src/vitals.c */
{
    FILE *f = fopen("/sys/class/thermal/thermal_zone0/temp", "r");
    long milli = 0;
    if (f) { fscanf(f, "%ld", &milli); fclose(f); }
```

Verify: `grep -rn '"/sys/' src/  # should be empty outside hal_linux.c`

### 5. Replace fork()/exec with posix_spawn()

*api_migration · effort S · qcc snippet check: skipped*

Use posix_spawn(); for daemonizing, let the startup script background the process instead.

Before:

```c
/* src/vitals.c */
{
    pid_t pid = fork();
    if (pid == 0) {
        char arg[16];
```

After:

```c
#include <spawn.h>

extern char **environ;
pid_t pid;
char *const argv[] = { (char *)path, arg, NULL };
int rc = posix_spawn(&pid, path, NULL, NULL, argv, environ);
```

Verify: `qcc -Vgcc_ntox86_64 -fsyntax-only src/main.c`

### 6. Wrap device control in a HAL

*api_migration · effort M · qcc snippet check: skipped*

Move ioctl() calls behind functions such as hal_set_line(); implement the QNX side with devctl().

Before:

```c
/* src/vitals.c */
    if (fd < 0) { syslog(LOG_ERR, "open %s: %m", I2C_BUS); return -1; }
    if (ioctl(fd, I2C_SLAVE, SENSOR_ADDR) < 0) { syslog(LOG_ERR, "I2C_SLAVE: %m"); return -1; }
    return fd;
}
```

After:

```c
/* hal.h */
int hal_serial_set_dtr(int fd, int on);

/* hal_qnx.c */
#include <devctl.h>
#include <sys/dcmd_chr.h>
int hal_serial_set_dtr(int fd, int on)
{
    int bits = on ? (_SERCTL_DTR | _SERCTL_DTR_CHG) : _SERCTL_DTR_CHG;
    return devctl(fd, DCMD_CHR_SERCTL, &bits, sizeof bits, NULL);
}
```

Verify: `qcc -Vgcc_ntox86_64 -fsyntax-only src/hal_qnx.c`

### 7. Expose the service as a /dev/vitals_monitor resource manager

*resmgr_conversion · effort L · qcc snippet check: skipped*

Start from the kit's resource-manager skeleton. Clients open /dev/vitals_monitor and use read(), write() and devctl() instead of a private socket or shared memory. The periodic work moves into the timer pulse handler, which runs serialized with client requests in one thread.

After:

```c
static int io_devctl(resmgr_context_t *ctp, io_devctl_t *msg, RESMGR_OCB_T *ocb)
{
    int status = iofunc_devctl_default(ctp, msg, ocb);
    if (status != _RESMGR_DEFAULT)
        return status;

    void  *data = _DEVCTL_DATA(msg->i);
    size_t nbytes = 0;

    switch (msg->i.dcmd) {
    case DCMD_VITALS_MONITOR_GET_STATUS:
        if (msg->i.nbytes < sizeof(state.status))
            return EINVAL;
        memcpy(data, &state.status, sizeof(state.status));
        nbytes = sizeof(state.status);
        break;
    case DCMD_VITALS_MONITOR_SET_VALUE: {
        int32_t v;
        if (msg->i.nbytes < sizeof v)
            return EINVAL;
        if (resmgr_msgread(ctp, &v, sizeof v, sizeof msg->i) != (ssize_t)sizeof v)
            return EFAULT;
        state.status.value = v;
        break;
    }
    default:
        return ENOSYS;
    }

    memset(&msg->o, 0, sizeof msg->o);
    msg->o.ret_val = EOK;
    msg->o.nbytes = (uint32_t)nbytes;
    return _RESMGR_PTR(ctp, &msg->o, sizeof msg->o + nbytes);
}
```

Verify: `ls -l /dev/vitals_monitor && vitals_monitorctl  # on the target`

### 8. Use absolute-deadline sleeps for periodic work

*scheduling_timing · effort S · qcc snippet check: skipped*

Replace relative sleeps in periodic loops with clock_nanosleep(TIMER_ABSTIME).

Before:

```c
/* src/vitals.c */
    }
    nanosleep(&period, NULL);
}
return NULL;
```

After:

```c
struct timespec next;
clock_gettime(CLOCK_MONOTONIC, &next);
for (;;) {
    do_work();
    next.tv_nsec += PERIOD_NS;
    while (next.tv_nsec >= 1000000000L) { next.tv_nsec -= 1000000000L; next.tv_sec++; }
    clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
}
```

Verify: `qcc -Vgcc_ntox86_64 -fsyntax-only src/main.c`

### 9. Drop privileges with procmgr_ability()

*reliability_security · effort M · qcc snippet check: skipped*

After privileged setup, allow the specific abilities the service still needs for the non-root domain, deny and lock everything else, then setuid() to a service user.

Before:

```c
/* src/vitals.c */
if (geteuid() != 0) {
    fprintf(stderr, "vitals-monitor must run as root\n");
    return 1;
}
prctl(PR_SET_NAME, "vitals-main", 0, 0, 0);
prctl(PR_SET_KEEPCAPS, 1, 0, 0, 0);
```

After:

```c
#include <sys/procmgr.h>

/* after resmgr_attach()/open() of privileged resources: */
if (procmgr_ability(0,
        PROCMGR_ADN_NONROOT | PROCMGR_AOP_ALLOW | PROCMGR_AOP_LOCK | PROCMGR_AID_PRIORITY,
        PROCMGR_ADN_NONROOT | PROCMGR_AOP_DENY  | PROCMGR_AOP_LOCK | PROCMGR_AID_EOL) != EOK) {
    return 1;
}
if (setgid(SERVICE_GID) == -1 || setuid(SERVICE_UID) == -1)
    return 1;
```

Verify: `pidin -p <service> arg  # on target: confirm non-root uid`

### 10. Replace systemd supervision with startup script + procmgr death notifications

*reliability_security · effort M · qcc snippet check: skipped*

Daemonize with procmgr_daemon() and register PROCMGR_EVENT_DAEMON_DEATH pulse notifications (or attach to HAM if installed).

Before:

```c
#!/bin/sh
# Restart vitals_monitor if it dies. Run from cron every minute.
if ! pgrep -x vitals_monitor >/dev/null; then
    logger -t vitals-watchdog "vitals_monitor not running, restarting"
    /usr/local/bin/vitals_monitor &
fi
```

After:

```c
#include <sys/procmgr.h>
#include <sys/siginfo.h>

struct sigevent ev;
SIGEV_PULSE_INIT(&ev, main_coid, 20, PULSE_CODE_SHUTDOWN, 0);
int handle = procmgr_event_notify_add(PROCMGR_EVENT_DAEMON_DEATH, &ev);
(void)handle;
```

Verify: `pidin -F '%a %b %N'  # on target, confirm supervised daemon running`

### 11. Optionally switch to slog2

*reliability_security · effort S · qcc snippet check: skipped*

Register a slog2 buffer set at start-up and route log calls through slog2f().

Before:

```c
/* src/vitals.c */
    int fd = open(I2C_BUS, O_RDWR);
    if (fd < 0) { syslog(LOG_ERR, "open %s: %m", I2C_BUS); return -1; }
    if (ioctl(fd, I2C_SLAVE, SENSOR_ADDR) < 0) { syslog(LOG_ERR, "I2C_SLAVE: %m"); return -1; }
    return fd;
}
```

After:

```c
#include <sys/slog2.h>

slog2_buffer_set_config_t cfg = {0};
slog2_buffer_t buf;
cfg.buffer_set_name = "motor_pid";
cfg.num_buffers = 1;
cfg.verbosity_level = SLOG2_INFO;
cfg.buffer_config[0].buffer_name = "main";
cfg.buffer_config[0].num_pages = 4;
if (slog2_register(&cfg, &buf, 0) == 0)
    slog2_set_default_buffer(buf);
slog2f(NULL, 0, SLOG2_INFO, "started, period=%d us", 1000);
```

Verify: `slog2info -b motor_pid  # on target`

### 12. Check shared-memory synchronization

*reliability_security · effort S · qcc snippet check: skipped*

Use a PTHREAD_PROCESS_SHARED + PTHREAD_PRIO_INHERIT mutex inside the shared region.

Before:

```c
/* src/vitals.c */
int shm_fd = shm_open("/vitals", O_CREAT | O_RDWR, 0644);
ftruncate(shm_fd, sizeof(vitals_shm_t));
shm = mmap(NULL, sizeof(vitals_shm_t), PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
```

Verify: `ls -l /dev/shmem  # on target`

### 13. Build, deploy and verify on a QNX 8.0 target

*deploy_verify · effort M · qcc snippet check: skipped*

Build the kit binaries with qcc, boot the QEMU target with mkqnximage, copy the binaries over SSH and run them under the advisor agent, which checks that the resource manager comes up and measures timer and IPC behaviour.

Verify: `advisorctl verify /data/home/qnxuser/vitals_monitor_resmgr --expect /dev/vitals_monitor --timeout 5000`


Unverified claims removed by the guard: 0
