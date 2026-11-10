/* agent.h - internal interfaces of qnx-advisor-agent. Apache-2.0. */
#ifndef AGENT_H
#define AGENT_H

#include <stdint.h>
#include <sys/iofunc.h>
#include <sys/dispatch.h>
#include <sys/slog2.h>

#include "advisor_dcmd.h"

#define LOG_INFO(...)  slog2f(NULL, 0, SLOG2_INFO, __VA_ARGS__)
#define LOG_WARN(...)  slog2f(NULL, 0, SLOG2_WARNING, __VA_ARGS__)
#define LOG_ERR(...)   slog2f(NULL, 0, SLOG2_ERROR, __VA_ARGS__)

/* Shared state set up in qnx_advisor_agent.c */
extern dispatch_t *g_dpp;
extern int         g_self_coid;       /* side-channel connection to our own dispatch channel */
extern int         g_code_child;      /* pulse code: verify child exited */
extern int         g_code_tick;       /* pulse code: verify watchdog tick */
extern uint64_t    g_cycles_per_sec;
extern char        g_allowed_prefix[ADVISOR_PATH_MAX];

uint64_t cycles_to_ns(uint64_t cycles);

/* verify.c */
int  verify_init(void);
int  verify_start(resmgr_context_t *ctp, io_devctl_t *msg);     /* _RESMGR_NOREPLY or an errno */
int  verify_on_child_exit(message_context_t *ctp, int code, unsigned flags, void *handle);
int  verify_on_tick(message_context_t *ctp, int code, unsigned flags, void *handle);
void verify_shutdown(void);

/* bench.c */
int bench_ipc(struct advisor_bench_ipc *b);
int bench_timer(struct advisor_bench_timer *b);

#endif
