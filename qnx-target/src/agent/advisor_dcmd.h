/*
 * advisor_dcmd.h - devctl() protocol between advisorctl and the qnx-advisor-agent
 * resource manager at /dev/advisor. Shared by both programs. Apache-2.0.
 */
#ifndef ADVISOR_DCMD_H
#define ADVISOR_DCMD_H

#include <devctl.h>
#include <stdint.h>

#define ADVISOR_DEV_PATH      "/dev/advisor"
#define ADVISOR_PATH_MAX      256
#define ADVISOR_ARGS_MAX      512
#define ADVISOR_HIST_BUCKETS  24     /* bucket 0: <1 us, bucket i: [2^(i-1), 2^i) us */

/* ---- DCMD_ADVISOR_VERIFY: spawn a binary, optionally wait for a path, collect its exit */
struct advisor_verify_in {
    char     path[ADVISOR_PATH_MAX];         /* absolute path of the binary */
    char     args[ADVISOR_ARGS_MAX];         /* space-separated arguments (no shell) */
    char     expect_path[ADVISOR_PATH_MAX];  /* e.g. "/dev/motor_pid"; empty = wait for exit */
    uint32_t timeout_ms;
    int32_t  priority;                       /* 0 = inherit from the agent */
    int32_t  policy;                         /* SCHED_FIFO, SCHED_RR, SCHED_OTHER or -1 = inherit */
};

struct advisor_verify_out {
    int32_t  exit_status;        /* exit code if exited normally, else -1 */
    int32_t  signal;             /* terminating signal, 0 if none */
    int32_t  timed_out;          /* 1 if the agent had to kill the child at the deadline */
    int32_t  spawn_errno;        /* posix_spawn() error, 0 on success */
    int32_t  path_appeared;      /* 1 if expect_path appeared before the deadline */
    int32_t  pid;
    uint64_t wall_ns;            /* spawn -> exit collected */
    uint64_t start_latency_ns;   /* devctl received -> posix_spawn() returned */
    uint64_t path_ready_ns;      /* spawn -> expect_path visible (0 if not applicable) */
};

typedef union {
    struct advisor_verify_in  i;
    struct advisor_verify_out o;
} advisor_verify_t;

/* ---- DCMD_ADVISOR_BENCH_IPC: MsgSend round trips to a private channel */
struct advisor_bench_ipc {
    uint32_t iterations;         /* in: 1 .. 100000 */
    uint32_t payload_bytes;      /* in: 0 .. 256 */
    uint64_t min_ns, p50_ns, p99_ns, max_ns;   /* out */
    uint64_t cycles_per_sec;                   /* out */
};

/* ---- DCMD_ADVISOR_BENCH_TIMER: periodic pulse timer wake-up lateness */
struct advisor_bench_timer {
    uint32_t period_us;          /* in: 100 .. 1000000 */
    uint32_t duration_ms;        /* in: 100 .. 30000 */
    int32_t  priority;           /* in: SCHED_FIFO priority of the measuring thread */
    uint32_t load_threads;       /* in: low-priority CPU burner threads (0 .. 16) */
    uint32_t samples;            /* out */
    uint32_t late_over_period;   /* out: wake-ups later than one full period */
    uint64_t p50_ns, p99_ns, max_ns;           /* out */
    uint32_t hist[ADVISOR_HIST_BUCKETS];       /* out */
};

#define DCMD_ADVISOR_VERIFY       __DIOTF(_DCMD_MISC, 0x41, advisor_verify_t)
#define DCMD_ADVISOR_BENCH_IPC    __DIOTF(_DCMD_MISC, 0x42, struct advisor_bench_ipc)
#define DCMD_ADVISOR_BENCH_TIMER  __DIOTF(_DCMD_MISC, 0x43, struct advisor_bench_timer)

#endif /* ADVISOR_DCMD_H */
