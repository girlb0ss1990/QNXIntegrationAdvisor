/*
 * vitals-monitor: samples a pulse-oximeter over I2C, publishes readings in
 * shared memory for a UI process, and signals new data with an eventfd.
 * Linux-specific: i2c-dev, eventfd, prctl/capabilities, fork(), /sys paths.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

#include <linux/i2c-dev.h>

#include "vitals_shm.h"

#define I2C_BUS   "/dev/i2c-1"
#define SENSOR_ADDR 0x57

static vitals_shm_t *shm;
static int           notify_efd;
static pthread_mutex_t shm_lock = PTHREAD_MUTEX_INITIALIZER;

static int sensor_open(void)
{
    int fd = open(I2C_BUS, O_RDWR);
    if (fd < 0) { syslog(LOG_ERR, "open %s: %m", I2C_BUS); return -1; }
    if (ioctl(fd, I2C_SLAVE, SENSOR_ADDR) < 0) { syslog(LOG_ERR, "I2C_SLAVE: %m"); return -1; }
    return fd;
}

static int sensor_read(int fd, uint16_t *spo2, uint16_t *bpm)
{
    uint8_t reg = 0x07, buf[4];
    if (write(fd, &reg, 1) != 1) return -1;
    if (read(fd, buf, 4) != 4) return -1;
    *spo2 = (uint16_t)(buf[0] << 8 | buf[1]);
    *bpm  = (uint16_t)(buf[2] << 8 | buf[3]);
    return 0;
}

static double board_temp_c(void)
{
    FILE *f = fopen("/sys/class/thermal/thermal_zone0/temp", "r");
    long milli = 0;
    if (f) { fscanf(f, "%ld", &milli); fclose(f); }
    return milli / 1000.0;
}

/* Sampling worker: 50 Hz with nanosleep. */
static void *sampler(void *arg)
{
    int fd = *(int *)arg;
    struct timespec period = { 0, 20 * 1000 * 1000 };
    for (;;) {
        uint16_t spo2, bpm;
        if (sensor_read(fd, &spo2, &bpm) == 0) {
            pthread_mutex_lock(&shm_lock);
            shm->spo2 = spo2;
            shm->bpm = bpm;
            shm->board_temp_c = board_temp_c();
            shm->seq++;
            pthread_mutex_unlock(&shm_lock);
            uint64_t one = 1;
            write(notify_efd, &one, sizeof one);
        }
        nanosleep(&period, NULL);
    }
    return NULL;
}

/* Spawn the alarm helper script whenever SpO2 drops below threshold. */
static void raise_alarm(uint16_t spo2)
{
    pid_t pid = fork();
    if (pid == 0) {
        char arg[16];
        snprintf(arg, sizeof arg, "%u", spo2);
        execl("/usr/local/bin/vitals-alarm.sh", "vitals-alarm.sh", arg, (char *)NULL);
        _exit(127);
    } else if (pid > 0) {
        waitpid(pid, NULL, WNOHANG);
    }
}

int main(void)
{
    openlog("vitals", LOG_PID, LOG_DAEMON);

    if (geteuid() != 0) {
        fprintf(stderr, "vitals-monitor must run as root\n");
        return 1;
    }
    prctl(PR_SET_NAME, "vitals-main", 0, 0, 0);
    prctl(PR_SET_KEEPCAPS, 1, 0, 0, 0);

    int shm_fd = shm_open("/vitals", O_CREAT | O_RDWR, 0644);
    ftruncate(shm_fd, sizeof(vitals_shm_t));
    shm = mmap(NULL, sizeof(vitals_shm_t), PROT_READ | PROT_WRITE, MAP_SHARED, shm_fd, 0);
    memset(shm, 0, sizeof *shm);

    notify_efd = eventfd(0, 0);

    int fd = sensor_open();
    if (fd < 0) return 1;

    pthread_t th;
    pthread_create(&th, NULL, sampler, &fd);

    for (;;) {
        uint64_t n;
        if (read(notify_efd, &n, sizeof n) != sizeof n) continue;
        pthread_mutex_lock(&shm_lock);
        uint16_t spo2 = shm->spo2;
        pthread_mutex_unlock(&shm_lock);
        if (spo2 < 90)
            raise_alarm(spo2);
    }
}
