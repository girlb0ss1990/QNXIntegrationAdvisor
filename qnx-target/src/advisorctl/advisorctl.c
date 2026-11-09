/*
 * advisorctl.c - client for /dev/advisor, invoked by the host over SSH. Prints one JSON object.
 *
 *   advisorctl info
 *   advisorctl verify <path> [--args "a b"] [--expect /dev/x] [--timeout ms] [--priority p] [--policy fifo|rr|other]
 *   advisorctl bench-ipc [--iterations n] [--payload bytes]
 *   advisorctl bench-timer [--period-us us] [--duration-ms ms] [--priority p] [--load n]
 *
 * Apache-2.0.
 */
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <devctl.h>

#include "../agent/advisor_dcmd.h"

static const char *opt_val(int argc, char **argv, const char *name, const char *def)
{
    for (int i = 0; i < argc - 1; i++)
        if (strcmp(argv[i], name) == 0)
            return argv[i + 1];
    return def;
}

static long opt_long(int argc, char **argv, const char *name, long def)
{
    const char *v = opt_val(argc, argv, name, NULL);
    return v ? strtol(v, NULL, 10) : def;
}

static int fail(const char *what, int err)
{
    printf("{\"ok\":false,\"error\":\"%s: %s\"}\n", what, strerror(err));
    return EXIT_FAILURE;
}

static int copy_str(char *dst, size_t cap, const char *src)
{
    size_t n = strlen(src);
    if (n >= cap)
        return -1;
    memcpy(dst, src, n + 1);
    return 0;
}

static int cmd_info(void)
{
    char buf[1024];
    int fd = open(ADVISOR_DEV_PATH, O_RDONLY);
    if (fd == -1)
        return fail("open " ADVISOR_DEV_PATH, errno);
    ssize_t n = read(fd, buf, sizeof buf - 1);
    int err = errno;
    close(fd);
    if (n < 0)
        return fail("read", err);
    buf[n] = '\0';
    fputs(buf, stdout);
    return EXIT_SUCCESS;
}

static int cmd_verify(int fd, int argc, char **argv)
{
    if (argc < 1)
        return fail("usage", EINVAL);
    advisor_verify_t v;
    memset(&v, 0, sizeof v);
    if (copy_str(v.i.path, sizeof v.i.path, argv[0]) != 0
        || copy_str(v.i.args, sizeof v.i.args, opt_val(argc, argv, "--args", "")) != 0
        || copy_str(v.i.expect_path, sizeof v.i.expect_path, opt_val(argc, argv, "--expect", "")) != 0)
        return fail("argument too long", ENAMETOOLONG);
    v.i.timeout_ms = (uint32_t)opt_long(argc, argv, "--timeout", 5000);
    v.i.priority = (int32_t)opt_long(argc, argv, "--priority", 0);
    const char *pol = opt_val(argc, argv, "--policy", "");
    v.i.policy = strcmp(pol, "fifo") == 0 ? SCHED_FIFO : strcmp(pol, "rr") == 0 ? SCHED_RR
               : strcmp(pol, "other") == 0 ? SCHED_OTHER : -1;

    int rc = devctl(fd, DCMD_ADVISOR_VERIFY, &v, sizeof v, NULL);
    if (rc != EOK)
        return fail("devctl VERIFY", rc);
    int ok = v.o.spawn_errno == 0 && !v.o.timed_out &&
             (v.i.expect_path[0] ? v.o.path_appeared : v.o.exit_status == 0);
    printf("{\"ok\":%s,\"pid\":%d,\"exit_status\":%d,\"signal\":%d,\"timed_out\":%d,\"spawn_errno\":%d,"
           "\"path_appeared\":%d,\"wall_ns\":%llu,\"start_latency_ns\":%llu,\"path_ready_ns\":%llu}\n",
           ok ? "true" : "false", (int)v.o.pid, (int)v.o.exit_status, (int)v.o.signal, (int)v.o.timed_out,
           (int)v.o.spawn_errno, (int)v.o.path_appeared, (unsigned long long)v.o.wall_ns,
           (unsigned long long)v.o.start_latency_ns, (unsigned long long)v.o.path_ready_ns);
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}

static int cmd_bench_ipc(int fd, int argc, char **argv)
{
    struct advisor_bench_ipc b;
    memset(&b, 0, sizeof b);
    b.iterations = (uint32_t)opt_long(argc, argv, "--iterations", 10000);
    b.payload_bytes = (uint32_t)opt_long(argc, argv, "--payload", 64);
    int rc = devctl(fd, DCMD_ADVISOR_BENCH_IPC, &b, sizeof b, NULL);
    if (rc != EOK)
        return fail("devctl BENCH_IPC", rc);
    printf("{\"ok\":true,\"iterations\":%u,\"payload_bytes\":%u,\"min_ns\":%llu,\"p50_ns\":%llu,"
           "\"p99_ns\":%llu,\"max_ns\":%llu,\"cycles_per_sec\":%llu}\n",
           b.iterations, b.payload_bytes, (unsigned long long)b.min_ns, (unsigned long long)b.p50_ns,
           (unsigned long long)b.p99_ns, (unsigned long long)b.max_ns, (unsigned long long)b.cycles_per_sec);
    return EXIT_SUCCESS;
}

static int cmd_bench_timer(int fd, int argc, char **argv)
{
    struct advisor_bench_timer b;
    memset(&b, 0, sizeof b);
    b.period_us = (uint32_t)opt_long(argc, argv, "--period-us", 1000);
    b.duration_ms = (uint32_t)opt_long(argc, argv, "--duration-ms", 5000);
    b.priority = (int32_t)opt_long(argc, argv, "--priority", 40);
    b.load_threads = (uint32_t)opt_long(argc, argv, "--load", 0);
    int rc = devctl(fd, DCMD_ADVISOR_BENCH_TIMER, &b, sizeof b, NULL);
    if (rc != EOK)
        return fail("devctl BENCH_TIMER", rc);
    printf("{\"ok\":true,\"period_us\":%u,\"duration_ms\":%u,\"priority\":%d,\"load_threads\":%u,"
           "\"samples\":%u,\"late_over_period\":%u,\"p50_us\":%.3f,\"p99_us\":%.3f,\"max_us\":%.3f,\"hist_us_log2\":[",
           b.period_us, b.duration_ms, (int)b.priority, b.load_threads, b.samples, b.late_over_period,
           b.p50_ns / 1000.0, b.p99_ns / 1000.0, b.max_ns / 1000.0);
    for (int i = 0; i < ADVISOR_HIST_BUCKETS; i++)
        printf("%s%u", i ? "," : "", b.hist[i]);
    printf("]}\n");
    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: advisorctl info|verify|bench-ipc|bench-timer ...\n");
        return EXIT_FAILURE;
    }
    if (strcmp(argv[1], "info") == 0)
        return cmd_info();

    int fd = open(ADVISOR_DEV_PATH, O_RDWR);
    if (fd == -1)
        return fail("open " ADVISOR_DEV_PATH " (is qnx-advisor-agent running?)", errno);
    int rc;
    if (strcmp(argv[1], "verify") == 0)
        rc = cmd_verify(fd, argc - 2, argv + 2);
    else if (strcmp(argv[1], "bench-ipc") == 0)
        rc = cmd_bench_ipc(fd, argc - 2, argv + 2);
    else if (strcmp(argv[1], "bench-timer") == 0)
        rc = cmd_bench_timer(fd, argc - 2, argv + 2);
    else
        rc = fail("unknown command", EINVAL);
    close(fd);
    return rc;
}
