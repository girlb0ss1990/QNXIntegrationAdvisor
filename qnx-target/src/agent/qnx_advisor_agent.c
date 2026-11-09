/*
 * qnx_advisor_agent.c - QNX 8.0 resource manager at /dev/advisor.
 *
 * Gives the QNX Integration Advisor host tool measured evidence from a real target:
 *   read()                    JSON snapshot of the target (uname, CPUs, clock, memory, privileges)
 *   DCMD_ADVISOR_VERIFY       posix_spawn a kit binary, watch for its /dev path, collect its exit
 *   DCMD_ADVISOR_BENCH_IPC    MsgSend round-trip times measured with ClockCycles()
 *   DCMD_ADVISOR_BENCH_TIMER  periodic pulse-timer wake-up lateness, optionally under CPU load
 *
 * Design: single-threaded dispatch loop (dispatch_*, iofunc_*, resmgr_attach, pulse_attach).
 * VERIFY replies asynchronously: the devctl returns _RESMGR_NOREPLY and the reply is sent from a
 * pulse handler once a waiter thread reports the child's exit. Starts as root to register the
 * path, then keeps only the abilities it needs (procmgr_ability) and switches to a non-root uid.
 *
 * Usage: qnx-advisor-agent [-u uid] [-a allowed_prefix] [-d] [-U]
 *   -u uid     user to switch to after start-up (default 1000)
 *   -a prefix  only binaries under this directory may be spawned (default /data/home/qnxuser/)
 *   -d         run as a daemon (procmgr_daemon)
 *   -U         stay root (debugging only)
 *
 * Apache-2.0.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <devctl.h>
#include <sys/dispatch.h>
#include <sys/iofunc.h>
#include <sys/neutrino.h>
#include <sys/procmgr.h>
#include <sys/slog2.h>
#include <sys/stat.h>
#include <sys/syspage.h>
#include <sys/utsname.h>

#include "agent.h"

dispatch_t *g_dpp;
int         g_self_coid = -1;
int         g_code_child = -1;
int         g_code_tick = -1;
uint64_t    g_cycles_per_sec;
char        g_allowed_prefix[ADVISOR_PATH_MAX] = "/data/home/qnxuser/";

static int                    g_code_shutdown = -1;
static volatile int           g_running = 1;
static int                    g_dropped;
static uid_t                  g_run_uid = 1000;
static resmgr_connect_funcs_t connect_funcs;
static resmgr_io_funcs_t      io_funcs;
static iofunc_attr_t          dev_attr;
static char                   snapshot[1024];

uint64_t cycles_to_ns(uint64_t cycles)
{
    uint64_t cps = g_cycles_per_sec ? g_cycles_per_sec : 1;
    return (cycles / cps) * 1000000000ULL + ((cycles % cps) * 1000000000ULL) / cps;
}

/* ------------------------------------------------------------------ read(): JSON snapshot */
static int build_snapshot(void)
{
    struct utsname u;
    struct stat    st;
    if (uname(&u) == -1)
        return errno;
    /* On QNX, the size reported for /proc is the amount of free memory. */
    unsigned long long free_mem = stat("/proc", &st) == 0 ? (unsigned long long)st.st_size : 0ULL;
    int n = snprintf(snapshot, sizeof snapshot,
                     "{\"sysname\":\"%s\",\"release\":\"%s\",\"version\":\"%s\",\"machine\":\"%s\","
                     "\"nodename\":\"%s\",\"num_cpu\":%u,\"cycles_per_sec\":%llu,\"free_mem_bytes\":%llu,"
                     "\"uid\":%d,\"abilities_dropped\":%s,\"allowed_prefix\":\"%s\"}\n",
                     u.sysname, u.release, u.version, u.machine, u.nodename,
                     (unsigned)_syspage_ptr->num_cpu, (unsigned long long)g_cycles_per_sec, free_mem,
                     (int)getuid(), g_dropped ? "true" : "false", g_allowed_prefix);
    return (n < 0 || (size_t)n >= sizeof snapshot) ? EOVERFLOW : EOK;
}

static int io_read(resmgr_context_t *ctp, io_read_t *msg, RESMGR_OCB_T *ocb)
{
    int status = iofunc_read_verify(ctp, msg, ocb, NULL);
    if (status != EOK)
        return status;
    if ((msg->i.xtype & _IO_XTYPE_MASK) != _IO_XTYPE_NONE)
        return ENOSYS;
    if (ocb->offset == 0) {
        status = build_snapshot();
        if (status != EOK)
            return status;
    }
    size_t len = strlen(snapshot);
    size_t nbytes = 0;
    if (ocb->offset >= 0 && (size_t)ocb->offset < len) {
        nbytes = len - (size_t)ocb->offset;
        if (nbytes > (size_t)_IO_READ_GET_NBYTES(msg))
            nbytes = (size_t)_IO_READ_GET_NBYTES(msg);
    }
    _IO_SET_READ_NBYTES(ctp, nbytes);
    if (nbytes == 0)
        return _RESMGR_NPARTS(0);
    SETIOV(ctp->iov, snapshot + ocb->offset, nbytes);
    ocb->offset += (off_t)nbytes;
    return _RESMGR_NPARTS(1);
}

/* ------------------------------------------------------------------ devctl() */
static int reply_devctl(resmgr_context_t *ctp, io_devctl_t *msg, const void *data, size_t nbytes)
{
    /* data already sits at _DEVCTL_DATA(msg->o) or is copied there; the reply header
       and payload are sent as one contiguous part. */
    void *dst = _DEVCTL_DATA(msg->o);
    if (data != dst)
        memmove(dst, data, nbytes);
    memset(&msg->o, 0, sizeof msg->o);
    msg->o.ret_val = EOK;
    msg->o.nbytes = (uint32_t)nbytes;
    return _RESMGR_PTR(ctp, &msg->o, sizeof msg->o + nbytes);
}

static int io_devctl(resmgr_context_t *ctp, io_devctl_t *msg, RESMGR_OCB_T *ocb)
{
    int status = iofunc_devctl_default(ctp, msg, ocb);
    if (status != _RESMGR_DEFAULT)
        return status;

    switch (msg->i.dcmd) {
    case DCMD_ADVISOR_VERIFY:
        if (msg->i.nbytes < sizeof(advisor_verify_t))
            return EINVAL;
        return verify_start(ctp, msg);

    case DCMD_ADVISOR_BENCH_IPC: {
        struct advisor_bench_ipc b;
        if (msg->i.nbytes < sizeof b)
            return EINVAL;
        if (resmgr_msgread(ctp, &b, sizeof b, sizeof msg->i) != (ssize_t)sizeof b)
            return EFAULT;
        status = bench_ipc(&b);
        if (status != EOK)
            return status;
        return reply_devctl(ctp, msg, &b, sizeof b);
    }

    case DCMD_ADVISOR_BENCH_TIMER: {
        struct advisor_bench_timer b;
        if (msg->i.nbytes < sizeof b)
            return EINVAL;
        if (resmgr_msgread(ctp, &b, sizeof b, sizeof msg->i) != (ssize_t)sizeof b)
            return EFAULT;
        status = bench_timer(&b);
        if (status != EOK)
            return status;
        return reply_devctl(ctp, msg, &b, sizeof b);
    }

    default:
        return ENOSYS;
    }
}

/* ------------------------------------------------------------------ shutdown */
static int on_shutdown(message_context_t *ctp, int code, unsigned flags, void *handle)
{
    (void)ctp; (void)code; (void)flags; (void)handle;
    LOG_INFO("shutdown requested");
    g_running = 0;
    return 0;
}

static void *signal_thread(void *arg)
{
    sigset_t *set = arg;
    siginfo_t si;
    while (sigwaitinfo(set, &si) == -1 && errno == EINTR)
        ;
    if (MsgSendPulse(g_self_coid, -1, g_code_shutdown, si.si_signo) == -1)
        _exit(EXIT_FAILURE);
    return NULL;
}

/* ------------------------------------------------------------------ privileges */
static int drop_privileges(uid_t uid)
{
    /*
     * The path is registered. Spawned kit binaries must be able to register their own /dev
     * path and set real-time priorities, so for the non-root domain we allow (and let children
     * inherit) only PATHSPACE and PRIORITY, then deny and lock everything else before
     * switching to the unprivileged user.
     */
    int rc = procmgr_ability(0,
        PROCMGR_ADN_NONROOT | PROCMGR_AOP_ALLOW | PROCMGR_AOP_INHERIT_YES | PROCMGR_AOP_LOCK | PROCMGR_AID_PATHSPACE,
        PROCMGR_ADN_NONROOT | PROCMGR_AOP_ALLOW | PROCMGR_AOP_INHERIT_YES | PROCMGR_AOP_LOCK | PROCMGR_AID_PRIORITY,
        PROCMGR_ADN_NONROOT | PROCMGR_AOP_DENY | PROCMGR_AOP_LOCK | PROCMGR_AID_EOL);
    if (rc != EOK) {
        LOG_ERR("procmgr_ability: %s", strerror(rc));
        return -1;
    }
    if (setgid((gid_t)uid) == -1 || setuid(uid) == -1) {
        LOG_ERR("setuid(%d): %s", (int)uid, strerror(errno));
        return -1;
    }
    g_dropped = 1;
    LOG_INFO("dropped root; running as uid %d with PATHSPACE+PRIORITY only", (int)uid);
    return 0;
}

static int setup_logging(void)
{
    slog2_buffer_set_config_t cfg;
    slog2_buffer_t            buf;
    memset(&cfg, 0, sizeof cfg);
    cfg.buffer_set_name = "qnx_advisor_agent";
    cfg.num_buffers = 1;
    cfg.verbosity_level = SLOG2_INFO;
    cfg.buffer_config[0].buffer_name = "main";
    cfg.buffer_config[0].num_pages = 4;
    if (slog2_register(&cfg, &buf, 0) == -1)
        return -1;
    slog2_set_default_buffer(buf);
    return 0;
}

int main(int argc, char **argv)
{
    int stay_root = 0, daemonize = 0, opt;
    while ((opt = getopt(argc, argv, "u:a:dU")) != -1) {
        switch (opt) {
        case 'u': g_run_uid = (uid_t)strtoul(optarg, NULL, 10); break;
        case 'a':
            if (optarg[0] != '/' || strlen(optarg) >= sizeof g_allowed_prefix) {
                fprintf(stderr, "-a needs an absolute directory\n");
                return EXIT_FAILURE;
            }
            strcpy(g_allowed_prefix, optarg);
            break;
        case 'd': daemonize = 1; break;
        case 'U': stay_root = 1; break;
        default:
            fprintf(stderr, "usage: %s [-u uid] [-a allowed_prefix] [-d] [-U]\n", argv[0]);
            return EXIT_FAILURE;
        }
    }
    if (setup_logging() == -1)
        fprintf(stderr, "slog2_register failed, continuing without slog2\n");
    if (daemonize && procmgr_daemon(EXIT_SUCCESS, PROCMGR_DAEMON_NOCHDIR | PROCMGR_DAEMON_NOCLOSE) == -1) {
        perror("procmgr_daemon");
        return EXIT_FAILURE;
    }

    g_cycles_per_sec = SYSPAGE_ENTRY(qtime)->cycles_per_sec;

    /* Block termination signals in every thread; a dedicated thread turns them into a pulse. */
    static sigset_t sigs;
    sigemptyset(&sigs);
    sigaddset(&sigs, SIGTERM);
    sigaddset(&sigs, SIGINT);
    sigaddset(&sigs, SIGHUP);
    if (pthread_sigmask(SIG_BLOCK, &sigs, NULL) != 0) {
        perror("pthread_sigmask");
        return EXIT_FAILURE;
    }

    g_dpp = dispatch_create();
    if (g_dpp == NULL) {
        perror("dispatch_create");
        return EXIT_FAILURE;
    }
    resmgr_attr_t rattr;
    memset(&rattr, 0, sizeof rattr);
    rattr.nparts_max = 1;
    rattr.msg_max_size = 4096;

    iofunc_func_init(_RESMGR_CONNECT_NFUNCS, &connect_funcs, _RESMGR_IO_NFUNCS, &io_funcs);
    io_funcs.read = io_read;
    io_funcs.devctl = io_devctl;
    iofunc_attr_init(&dev_attr, S_IFCHR | 0666, NULL, NULL);

    int id = resmgr_attach(g_dpp, &rattr, ADVISOR_DEV_PATH, _FTYPE_ANY, 0, &connect_funcs, &io_funcs, &dev_attr);
    if (id == -1) {
        perror("resmgr_attach " ADVISOR_DEV_PATH);
        return EXIT_FAILURE;
    }
    g_code_child = pulse_attach(g_dpp, MSG_FLAG_ALLOC_PULSE, 0, verify_on_child_exit, NULL);
    g_code_tick = pulse_attach(g_dpp, MSG_FLAG_ALLOC_PULSE, 0, verify_on_tick, NULL);
    g_code_shutdown = pulse_attach(g_dpp, MSG_FLAG_ALLOC_PULSE, 0, on_shutdown, NULL);
    if (g_code_child == -1 || g_code_tick == -1 || g_code_shutdown == -1) {
        perror("pulse_attach");
        return EXIT_FAILURE;
    }
    g_self_coid = message_connect(g_dpp, MSG_FLAG_SIDE_CHANNEL);
    if (g_self_coid == -1) {
        perror("message_connect");
        return EXIT_FAILURE;
    }
    if (verify_init() != 0) {
        perror("verify_init");
        return EXIT_FAILURE;
    }

    pthread_t sig_tid;
    if (pthread_create(&sig_tid, NULL, signal_thread, &sigs) != 0) {
        perror("pthread_create");
        return EXIT_FAILURE;
    }

    if (!stay_root && drop_privileges(g_run_uid) != 0) {
        fprintf(stderr, "failed to drop privileges (see slog2info)\n");
        return EXIT_FAILURE;
    }
    LOG_INFO("serving %s (cycles/s %llu)", ADVISOR_DEV_PATH, (unsigned long long)g_cycles_per_sec);

    dispatch_context_t *ctp = dispatch_context_alloc(g_dpp);
    if (ctp == NULL) {
        perror("dispatch_context_alloc");
        return EXIT_FAILURE;
    }
    while (g_running) {
        dispatch_context_t *next = dispatch_block(ctp);
        if (next == NULL) {
            if (errno == EINTR)
                continue;
            LOG_ERR("dispatch_block: %s", strerror(errno));
            break;
        }
        ctp = next;
        dispatch_handler(ctp);
    }

    verify_shutdown();
    resmgr_detach(g_dpp, id, _RESMGR_DETACH_ALL);
    LOG_INFO("exiting");
    return EXIT_SUCCESS;
}
