/*
 * bench.c - measured evidence for the host report. All timing uses ClockCycles().
 * No dynamic allocation inside measurement loops (sample buffers are static).
 *
 *   bench_ipc():   MsgSend round trips between two threads over a private channel
 *   bench_timer(): a SCHED_FIFO thread waits on a periodic pulse timer; lateness of each
 *                  wake-up against the ideal schedule, optionally with low-priority CPU burners
 *
 * Numbers from a QEMU target include virtualization overhead and are indicative only.
 * Apache-2.0.
 */
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
#include <sys/neutrino.h>
#include <sys/siginfo.h>
#include <time.h>

#include "agent.h"

#define MAX_SAMPLES   100000
#define MAX_LOAD      16
#define IPC_WARMUP    200
#define IPC_STOP      0xDEADu

#ifdef _NTO_CHF_PRIVATE
#define BENCH_CHF _NTO_CHF_PRIVATE
#else
#define BENCH_CHF 0
#endif

static uint64_t samples[MAX_SAMPLES];

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

static uint64_t pct(const uint64_t *sorted, uint32_t n, unsigned p)
{
    if (n == 0)
        return 0;
    uint32_t i = (uint32_t)(((uint64_t)(n - 1) * p) / 100U);
    return sorted[i];
}

/* ------------------------------------------------------------------ IPC */
struct ipc_msg {
    uint32_t cmd;
    uint8_t  payload[256];
};

static void *ipc_server(void *arg)
{
    int chid = (int)(intptr_t)arg;
    struct ipc_msg m;
    for (;;) {
        rcvid_t rcvid = MsgReceive(chid, &m, sizeof m, NULL);
        if (rcvid == -1)
            return NULL;
        if (rcvid == 0)
            continue;                       /* pulse */
        MsgReply(rcvid, EOK, &m, sizeof m);
        if (m.cmd == IPC_STOP)
            return NULL;
    }
}

int bench_ipc(struct advisor_bench_ipc *b)
{
    if (b->iterations == 0 || b->iterations > MAX_SAMPLES)
        b->iterations = 10000;
    if (b->payload_bytes > sizeof(((struct ipc_msg *)0)->payload))
        b->payload_bytes = sizeof(((struct ipc_msg *)0)->payload);

    int chid = ChannelCreate(BENCH_CHF);
    if (chid == -1)
        return errno;
    pthread_t tid;
    int rc = pthread_create(&tid, NULL, ipc_server, (void *)(intptr_t)chid);
    if (rc != 0) {
        ChannelDestroy(chid);
        return rc;
    }
    int coid = ConnectAttach(0, 0, chid, _NTO_SIDE_CHANNEL, 0);
    if (coid == -1) {
        rc = errno;
        ChannelDestroy(chid);
        pthread_join(tid, NULL);
        return rc;
    }

    struct ipc_msg out, in;
    memset(&out, 0xA5, sizeof out);
    out.cmd = 1;
    size_t len = sizeof out.cmd + b->payload_bytes;
    rc = EOK;
    for (uint32_t i = 0; i < IPC_WARMUP + b->iterations; i++) {
        uint64_t t0 = ClockCycles();
        if (MsgSend(coid, &out, len, &in, len) == -1) {
            rc = errno;
            break;
        }
        uint64_t t1 = ClockCycles();
        if (i >= IPC_WARMUP)
            samples[i - IPC_WARMUP] = t1 - t0;
    }
    out.cmd = IPC_STOP;
    MsgSend(coid, &out, sizeof out.cmd, &in, sizeof in.cmd);
    pthread_join(tid, NULL);
    ConnectDetach(coid);
    ChannelDestroy(chid);
    if (rc != EOK)
        return rc;

    qsort(samples, b->iterations, sizeof samples[0], cmp_u64);
    b->min_ns = cycles_to_ns(samples[0]);
    b->p50_ns = cycles_to_ns(pct(samples, b->iterations, 50));
    b->p99_ns = cycles_to_ns(pct(samples, b->iterations, 99));
    b->max_ns = cycles_to_ns(samples[b->iterations - 1]);
    b->cycles_per_sec = g_cycles_per_sec;
    LOG_INFO("bench_ipc: n=%u p50=%lluns p99=%lluns", b->iterations,
             (unsigned long long)b->p50_ns, (unsigned long long)b->p99_ns);
    return EOK;
}

/* ------------------------------------------------------------------ timer */
static volatile int burn_stop;

static void *burner(void *arg)
{
    (void)arg;
    volatile uint64_t x = 0;
    while (!burn_stop)
        x++;
    return NULL;
}

struct timer_job {
    struct advisor_bench_timer *b;
    uint32_t                    n;
    int                         err;
};

static void *timer_thread(void *arg)
{
    struct timer_job *job = arg;
    struct advisor_bench_timer *b = job->b;
    struct sigevent   ev;
    struct itimerspec its;
    timer_t           tid;
    struct _pulse     p;

    int chid = ChannelCreate(BENCH_CHF);
    if (chid == -1) {
        job->err = errno;
        return NULL;
    }
    int coid = ConnectAttach(0, 0, chid, _NTO_SIDE_CHANNEL, 0);
    if (coid == -1) {
        job->err = errno;
        ChannelDestroy(chid);
        return NULL;
    }
    SIGEV_PULSE_INIT(&ev, coid, b->priority, _PULSE_CODE_MINAVAIL, 0);
    if (timer_create(CLOCK_MONOTONIC, &ev, &tid) == -1) {
        job->err = errno;
        ConnectDetach(coid);
        ChannelDestroy(chid);
        return NULL;
    }
    memset(&its, 0, sizeof its);
    its.it_value.tv_sec = b->period_us / 1000000U;
    its.it_value.tv_nsec = (long)(b->period_us % 1000000U) * 1000L;
    its.it_interval = its.it_value;

    uint32_t want = (uint32_t)(((uint64_t)b->duration_ms * 1000U) / b->period_us);
    if (want > MAX_SAMPLES)
        want = MAX_SAMPLES;
    uint64_t period_cycles = (g_cycles_per_sec * (uint64_t)b->period_us) / 1000000ULL;
    uint64_t t_first = 0;

    if (timer_settime(tid, 0, &its, NULL) == -1) {
        job->err = errno;
    } else {
        /* The first expiry defines the schedule; lateness of later ones is measured against it. */
        for (uint32_t k = 0; k <= want; k++) {
            if (MsgReceivePulse(chid, &p, sizeof p, NULL) == -1) {
                job->err = errno;
                break;
            }
            uint64_t now = ClockCycles();
            if (k == 0) {
                t_first = now;
                continue;
            }
            uint64_t ideal = t_first + period_cycles * k;
            samples[k - 1] = now > ideal ? now - ideal : 0;
            job->n = k;
        }
    }
    timer_delete(tid);
    ConnectDetach(coid);
    ChannelDestroy(chid);
    return NULL;
}

int bench_timer(struct advisor_bench_timer *b)
{
    if (b->period_us < 100 || b->period_us > 1000000)
        b->period_us = 1000;
    if (b->duration_ms < 100 || b->duration_ms > 30000)
        b->duration_ms = 5000;
    if (b->priority < 1 || b->priority > 254)
        b->priority = 40;
    if (b->load_threads > MAX_LOAD)
        b->load_threads = MAX_LOAD;

    pthread_t      load[MAX_LOAD];
    uint32_t       nload = 0;
    pthread_attr_t la;
    struct sched_param sp;
    int rc;

    burn_stop = 0;
    pthread_attr_init(&la);
    pthread_attr_setinheritsched(&la, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&la, SCHED_RR);
    memset(&sp, 0, sizeof sp);
    sp.sched_priority = 5;                   /* well below the measuring thread */
    pthread_attr_setschedparam(&la, &sp);
    for (; nload < b->load_threads; nload++) {
        if (pthread_create(&load[nload], &la, burner, NULL) != 0)
            break;
    }
    pthread_attr_destroy(&la);

    struct timer_job job = { .b = b, .n = 0, .err = EOK };
    pthread_attr_t ta;
    pthread_t      tt;
    pthread_attr_init(&ta);
    pthread_attr_setinheritsched(&ta, PTHREAD_EXPLICIT_SCHED);
    pthread_attr_setschedpolicy(&ta, SCHED_FIFO);
    memset(&sp, 0, sizeof sp);
    sp.sched_priority = b->priority;
    pthread_attr_setschedparam(&ta, &sp);
    rc = pthread_create(&tt, &ta, timer_thread, &job);
    pthread_attr_destroy(&ta);
    if (rc == 0)
        pthread_join(tt, NULL);

    burn_stop = 1;
    for (uint32_t i = 0; i < nload; i++)
        pthread_join(load[i], NULL);
    b->load_threads = nload;
    if (rc != 0)
        return rc;
    if (job.err != EOK && job.n == 0)
        return job.err;

    uint32_t n = job.n;
    uint64_t period_ns = (uint64_t)b->period_us * 1000ULL;
    memset(b->hist, 0, sizeof b->hist);
    b->late_over_period = 0;
    for (uint32_t i = 0; i < n; i++) {
        uint64_t ns = cycles_to_ns(samples[i]);
        samples[i] = ns;
        uint64_t us = ns / 1000ULL;
        unsigned bucket = 0;
        while (us > 0 && bucket < ADVISOR_HIST_BUCKETS - 1) {
            us >>= 1;
            bucket++;
        }
        b->hist[bucket]++;
        if (ns > period_ns)
            b->late_over_period++;
    }
    qsort(samples, n, sizeof samples[0], cmp_u64);
    b->samples = n;
    b->p50_ns = pct(samples, n, 50);
    b->p99_ns = pct(samples, n, 99);
    b->max_ns = n ? samples[n - 1] : 0;
    LOG_INFO("bench_timer: n=%u load=%u p99=%lluns max=%lluns", n, nload,
             (unsigned long long)b->p99_ns, (unsigned long long)b->max_ns);
    return EOK;
}
