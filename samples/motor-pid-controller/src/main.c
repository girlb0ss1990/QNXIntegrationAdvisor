/*
 * motor-pid-controller: 1 kHz PID loop for a small DC motor.
 * Linux-specific: timerfd, epoll, inotify, sched_setaffinity.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/mman.h>
#include <sys/timerfd.h>
#include <unistd.h>

#include "config_watch.h"
#include "motor_io.h"
#include "pid.h"

#define LOOP_HZ 1000

static pid_ctrl_t      pid;
static pthread_mutex_t gains_lock;           /* shared by control + telemetry threads */
static double          setpoint_rpm = 1500.0;
static volatile double last_rpm, last_duty;

static void load_gains(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) return;
    double kp = 1.0, ki = 0.0, kd = 0.0, sp = setpoint_rpm;
    char line[128];
    while (fgets(line, sizeof line, f)) {
        sscanf(line, "kp=%lf", &kp);
        sscanf(line, "ki=%lf", &ki);
        sscanf(line, "kd=%lf", &kd);
        sscanf(line, "setpoint_rpm=%lf", &sp);
    }
    fclose(f);
    pthread_mutex_lock(&gains_lock);
    pid_init(&pid, kp, ki, kd, 0.0, 100.0);
    setpoint_rpm = sp;
    pthread_mutex_unlock(&gains_lock);
}

/* Low-priority telemetry thread: prints status every 100 ms. */
static void *telemetry_thread(void *arg)
{
    (void)arg;
    for (;;) {
        pthread_mutex_lock(&gains_lock);
        double sp = setpoint_rpm;
        usleep(2000);                        /* slow formatting while holding the lock */
        pthread_mutex_unlock(&gains_lock);
        printf("sp=%.0f rpm=%.1f duty=%.1f%%\n", sp, last_rpm, last_duty);
        usleep(100000);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    const char *cfg = argc > 1 ? argv[1] : "config/gains.conf";

    pthread_mutex_init(&gains_lock, NULL);
    load_gains(cfg);

    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0)
        perror("mlockall");

    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(1, &set);
    if (sched_setaffinity(0, sizeof set, &set) != 0)
        perror("sched_setaffinity");

    struct sched_param sp = { .sched_priority = 80 };
    pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);

    if (motor_io_open(NULL, NULL) != 0)
        return 1;

    pthread_t tel;
    pthread_create(&tel, NULL, telemetry_thread, NULL);

    int tfd = timerfd_create(CLOCK_MONOTONIC, 0);
    struct itimerspec its = {
        .it_interval = { 0, 1000000000L / LOOP_HZ },
        .it_value    = { 0, 1000000000L / LOOP_HZ },
    };
    timerfd_settime(tfd, 0, &its, NULL);

    int cfd = config_watch_start(cfg);

    int ep = epoll_create1(0);
    struct epoll_event ev = { .events = EPOLLIN };
    ev.data.fd = tfd; epoll_ctl(ep, EPOLL_CTL_ADD, tfd, &ev);
    if (cfd >= 0) { ev.data.fd = cfd; epoll_ctl(ep, EPOLL_CTL_ADD, cfd, &ev); }

    struct epoll_event events[4];
    for (;;) {
        int n = epoll_wait(ep, events, 4, -1);
        if (n < 0 && errno == EINTR) continue;
        for (int i = 0; i < n; i++) {
            if (events[i].data.fd == tfd) {
                uint64_t expirations;
                read(tfd, &expirations, sizeof expirations);
                double rpm = motor_io_read_rpm();
                pthread_mutex_lock(&gains_lock);
                double duty = pid_step(&pid, setpoint_rpm, rpm, 1.0 / LOOP_HZ);
                pthread_mutex_unlock(&gains_lock);
                motor_io_write_duty(duty);
                last_rpm = rpm; last_duty = duty;
            } else if (events[i].data.fd == cfd && config_watch_changed(cfd)) {
                load_gains(cfg);
            }
        }
    }
    motor_io_close();
    return 0;
}
