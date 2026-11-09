/*
 * verify.c - DCMD_ADVISOR_VERIFY: spawn a kit binary and report how it behaved.
 *
 * Flow (all on the dispatch thread except the waiter):
 *   devctl -> validate -> posix_spawn() with optional SCHED_* attributes -> start waiter thread
 *          -> arm a 2 ms watchdog timer that delivers a pulse to our own channel
 *          -> return _RESMGR_NOREPLY (client stays reply-blocked)
 *   tick pulse   -> stat(expect_path); once it exists, record the time and SIGTERM the child;
 *                   past the deadline, SIGKILL the child
 *   child pulse  -> waiter thread saw waitid() complete; MsgReplyv() the result to the client
 *
 * Apache-2.0.
 */
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/neutrino.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "agent.h"

#define TICK_NS      2000000L      /* watchdog tick: 2 ms */
#define MAX_ARGV     32

extern char **environ;

static struct {
    int                       active;
    rcvid_t                   rcvid;
    pid_t                     pid;
    uint64_t                  spawn_cycles;
    uint64_t                  deadline_cycles;
    int                       sent_term;
    struct advisor_verify_in  in;
    struct advisor_verify_out out;
    siginfo_t                 si;          /* written by the waiter thread before its pulse */
} pending;

static timer_t tick_timer;

int verify_init(void)
{
    struct sigevent ev;
    SIGEV_PULSE_INIT(&ev, g_self_coid, 10, g_code_tick, 0);
    return timer_create(CLOCK_MONOTONIC, &ev, &tick_timer);
}

static int arm_tick(int on)
{
    struct itimerspec its;
    memset(&its, 0, sizeof its);
    if (on) {
        its.it_value.tv_nsec = TICK_NS;
        its.it_interval.tv_nsec = TICK_NS;
    }
    return timer_settime(tick_timer, 0, &its, NULL);
}

static void *waiter(void *arg)
{
    pid_t pid = (pid_t)(intptr_t)arg;
    siginfo_t si;
    memset(&si, 0, sizeof si);
    while (waitid(P_PID, (id_t)pid, &si, WEXITED) == -1 && errno == EINTR)
        ;
    pending.si = si;
    /* Hand the result to the dispatch thread; it owns all reply state. */
    MsgSendPulse(g_self_coid, -1, g_code_child, (int)pid);
    return NULL;
}

static int split_args(char *buf, char *argv[], int max)
{
    int n = 0;
    char *save = NULL;
    for (char *tok = strtok_r(buf, " \t", &save); tok && n < max - 1; tok = strtok_r(NULL, " \t", &save))
        argv[n++] = tok;
    argv[n] = NULL;
    return n;
}

static int path_allowed(const char *path)
{
    size_t plen = strlen(g_allowed_prefix);
    if (path[0] != '/' || strstr(path, "/../") != NULL || strncmp(path, g_allowed_prefix, plen) != 0)
        return 0;
    struct stat st;
    return stat(path, &st) == 0 && S_ISREG(st.st_mode) && (st.st_mode & S_IXUSR);
}

static void reply_pending(void)
{
    struct _io_devctl_reply hdr;
    iov_t iov[2];
    memset(&hdr, 0, sizeof hdr);
    hdr.ret_val = EOK;
    hdr.nbytes = sizeof pending.out;
    SETIOV(&iov[0], &hdr, sizeof hdr);
    SETIOV(&iov[1], &pending.out, sizeof pending.out);
    if (MsgReplyv(pending.rcvid, EOK, iov, 2) == -1)
        LOG_WARN("verify: client gone before reply (%s)", strerror(errno));
    pending.active = 0;
}

int verify_start(resmgr_context_t *ctp, io_devctl_t *msg)
{
    uint64_t t0 = ClockCycles();
    if (pending.active)
        return EBUSY;

    memset(&pending.in, 0, sizeof pending.in);
    memset(&pending.out, 0, sizeof pending.out);
    if (resmgr_msgread(ctp, &pending.in, sizeof pending.in, sizeof msg->i) != (ssize_t)sizeof pending.in)
        return EFAULT;
    pending.in.path[ADVISOR_PATH_MAX - 1] = '\0';
    pending.in.args[ADVISOR_ARGS_MAX - 1] = '\0';
    pending.in.expect_path[ADVISOR_PATH_MAX - 1] = '\0';
    if (!path_allowed(pending.in.path))
        return EACCES;
    if (pending.in.timeout_ms == 0 || pending.in.timeout_ms > 600000)
        pending.in.timeout_ms = 5000;

    char  argbuf[ADVISOR_ARGS_MAX];
    char *argv[MAX_ARGV + 1];
    argv[0] = pending.in.path;
    memcpy(argbuf, pending.in.args, sizeof argbuf);
    split_args(argbuf, argv + 1, MAX_ARGV);

    posix_spawnattr_t attr;
    int rc = posix_spawnattr_init(&attr);
    if (rc != 0)
        return rc;
    if (pending.in.policy >= 0 && pending.in.priority > 0) {
        struct sched_param sp;
        memset(&sp, 0, sizeof sp);
        sp.sched_priority = pending.in.priority;
        rc = posix_spawnattr_setschedpolicy(&attr, pending.in.policy);
        if (rc == 0)
            rc = posix_spawnattr_setschedparam(&attr, &sp);
        if (rc == 0)
            rc = posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETSCHEDULER | POSIX_SPAWN_SETSCHEDPARAM);
        if (rc != 0) {
            posix_spawnattr_destroy(&attr);
            return rc;
        }
    }
    pid_t pid;
    rc = posix_spawn(&pid, pending.in.path, NULL, &attr, argv, environ);
    posix_spawnattr_destroy(&attr);
    uint64_t t1 = ClockCycles();

    pending.out.start_latency_ns = cycles_to_ns(t1 - t0);
    if (rc != 0) {
        /* Report spawn failures as data, not as a devctl error, so the host sees the errno. */
        pending.out.spawn_errno = rc;
        pending.out.exit_status = -1;
        LOG_WARN("verify: posix_spawn(%s) failed: %s", pending.in.path, strerror(rc));
        pending.rcvid = ctp->rcvid;
        pending.active = 1;
        reply_pending();
        return _RESMGR_NOREPLY;
    }

    pthread_t tid;
    pthread_attr_t pa;
    pthread_attr_init(&pa);
    pthread_attr_setdetachstate(&pa, PTHREAD_CREATE_DETACHED);
    rc = pthread_create(&tid, &pa, waiter, (void *)(intptr_t)pid);
    pthread_attr_destroy(&pa);
    if (rc != 0) {
        kill(pid, SIGKILL);
        waitpid(pid, NULL, 0);
        return rc;
    }

    pending.active = 1;
    pending.rcvid = ctp->rcvid;
    pending.pid = pid;
    pending.sent_term = 0;
    pending.spawn_cycles = t1;
    pending.deadline_cycles = t1 + (g_cycles_per_sec / 1000ULL) * pending.in.timeout_ms;
    pending.out.pid = pid;
    if (arm_tick(1) == -1)
        LOG_WARN("verify: timer_settime: %s", strerror(errno));
    LOG_INFO("verify: spawned %s pid %d (timeout %u ms)", pending.in.path, (int)pid, pending.in.timeout_ms);
    return _RESMGR_NOREPLY;
}

int verify_on_tick(message_context_t *ctp, int code, unsigned flags, void *handle)
{
    (void)ctp; (void)code; (void)flags; (void)handle;
    if (!pending.active)
        return 0;
    uint64_t now = ClockCycles();
    if (pending.in.expect_path[0] != '\0' && !pending.out.path_appeared) {
        struct stat st;
        if (stat(pending.in.expect_path, &st) == 0) {
            pending.out.path_appeared = 1;
            pending.out.path_ready_ns = cycles_to_ns(now - pending.spawn_cycles);
            /* The service came up: ask it to stop. Exit by SIGTERM is the expected outcome. */
            kill(pending.pid, SIGTERM);
            pending.sent_term = 1;
            pending.deadline_cycles = now + g_cycles_per_sec;    /* 1 s grace before SIGKILL */
            return 0;
        }
    }
    if (now >= pending.deadline_cycles) {
        if (!pending.sent_term || pending.out.path_appeared == 0)
            pending.out.timed_out = 1;
        kill(pending.pid, SIGKILL);
        arm_tick(0);
    }
    return 0;
}

int verify_on_child_exit(message_context_t *ctp, int code, unsigned flags, void *handle)
{
    (void)code; (void)flags; (void)handle;
    pid_t pid = (pid_t)ctp->msg->pulse.value.sival_int;
    if (!pending.active || pid != pending.pid)
        return 0;
    arm_tick(0);
    uint64_t now = ClockCycles();
    pending.out.wall_ns = cycles_to_ns(now - pending.spawn_cycles);
    if (pending.si.si_code == CLD_EXITED) {
        pending.out.exit_status = pending.si.si_status;
        pending.out.signal = 0;
    } else {
        pending.out.exit_status = -1;
        pending.out.signal = pending.si.si_status;
    }
    LOG_INFO("verify: pid %d done: exit %d signal %d timed_out %d path %d",
             (int)pid, pending.out.exit_status, pending.out.signal, pending.out.timed_out, pending.out.path_appeared);
    reply_pending();
    return 0;
}

void verify_shutdown(void)
{
    if (pending.active) {
        kill(pending.pid, SIGKILL);
        pending.out.timed_out = 1;
        pending.out.exit_status = -1;
        reply_pending();
    }
    timer_delete(tick_timer);
}
