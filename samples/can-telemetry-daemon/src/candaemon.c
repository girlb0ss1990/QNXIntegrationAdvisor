/*
 * can-telemetry-daemon: reads frames from SocketCAN, aggregates per-ID
 * statistics and serves them to local clients on a UNIX socket.
 * Linux-specific: SocketCAN, epoll, eventfd, signalfd, /proc, fork().
 */
#define _GNU_SOURCE
#include <errno.h>
#include <net/if.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/signalfd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <syslog.h>
#include <unistd.h>

#include <linux/can.h>
#include <linux/can/raw.h>

#include "stats.h"

#define SOCK_PATH "/run/candaemon.sock"

static int        flush_efd = -1;
static can_stats_t stats;

static int open_can(const char *ifname)
{
    int s = socket(PF_CAN, SOCK_RAW, CAN_RAW);
    if (s < 0) { syslog(LOG_ERR, "socket(PF_CAN): %m"); return -1; }

    struct ifreq ifr;
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);
    ifr.ifr_name[IFNAMSIZ - 1] = '\0';
    if (ioctl(s, SIOCGIFINDEX, &ifr) < 0) { syslog(LOG_ERR, "SIOCGIFINDEX: %m"); return -1; }

    struct sockaddr_can addr = { .can_family = AF_CAN, .can_ifindex = ifr.ifr_ifindex };
    if (bind(s, (struct sockaddr *)&addr, sizeof addr) < 0) { syslog(LOG_ERR, "bind: %m"); return -1; }
    return s;
}

static int open_server(void)
{
    int s = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a = { .sun_family = AF_UNIX };
    strncpy(a.sun_path, SOCK_PATH, sizeof a.sun_path - 1);
    unlink(SOCK_PATH);
    if (bind(s, (struct sockaddr *)&a, sizeof a) < 0 || listen(s, 4) < 0) {
        syslog(LOG_ERR, "unix socket: %m");
        return -1;
    }
    return s;
}

/* Periodic flusher: wakes the main loop through an eventfd every second. */
static void *flusher(void *arg)
{
    (void)arg;
    for (;;) {
        sleep(1);
        uint64_t one = 1;
        write(flush_efd, &one, sizeof one);
    }
    return NULL;
}

static long rss_kb(void)
{
    FILE *f = fopen("/proc/self/statm", "r");
    long pages = 0, resident = 0;
    if (f) { fscanf(f, "%ld %ld", &pages, &resident); fclose(f); }
    return resident * (sysconf(_SC_PAGESIZE) / 1024);
}

static void daemonize(void)
{
    pid_t pid = fork();
    if (pid < 0) exit(1);
    if (pid > 0) exit(0);
    setsid();
}

int main(int argc, char **argv)
{
    const char *ifname = argc > 1 ? argv[1] : "can0";
    int foreground = argc > 2 && strcmp(argv[2], "-f") == 0;

    openlog("candaemon", LOG_PID, LOG_DAEMON);
    if (!foreground) daemonize();

    int can = open_can(ifname);
    int srv = open_server();
    if (can < 0 || srv < 0) return 1;

    flush_efd = eventfd(0, EFD_NONBLOCK);
    pthread_t th;
    pthread_create(&th, NULL, flusher, NULL);

    sigset_t mask;
    sigemptyset(&mask);
    sigaddset(&mask, SIGTERM);
    sigaddset(&mask, SIGINT);
    sigprocmask(SIG_BLOCK, &mask, NULL);
    int sfd = signalfd(-1, &mask, SFD_NONBLOCK);

    int ep = epoll_create1(EPOLL_CLOEXEC);
    int fds[] = { can, srv, flush_efd, sfd };
    for (unsigned i = 0; i < sizeof fds / sizeof fds[0]; i++) {
        struct epoll_event ev = { .events = EPOLLIN, .data.fd = fds[i] };
        epoll_ctl(ep, EPOLL_CTL_ADD, fds[i], &ev);
    }

    stats_init(&stats);
    syslog(LOG_INFO, "listening on %s", ifname);

    struct epoll_event evs[8];
    for (;;) {
        int n = epoll_wait(ep, evs, 8, -1);
        if (n < 0 && errno == EINTR) continue;
        for (int i = 0; i < n; i++) {
            int fd = evs[i].data.fd;
            if (fd == can) {
                struct can_frame fr;
                if (read(can, &fr, sizeof fr) == sizeof fr)
                    stats_add(&stats, fr.can_id, fr.can_dlc, fr.data);
            } else if (fd == srv) {
                int c = accept(srv, NULL, NULL);
                if (c >= 0) { stats_dump(&stats, c); close(c); }
            } else if (fd == flush_efd) {
                uint64_t v;
                read(flush_efd, &v, sizeof v);
                stats_roll(&stats);
                syslog(LOG_DEBUG, "rolled window, rss=%ld kB", rss_kb());
            } else if (fd == sfd) {
                syslog(LOG_INFO, "shutting down");
                unlink(SOCK_PATH);
                return 0;
            }
        }
    }
}
