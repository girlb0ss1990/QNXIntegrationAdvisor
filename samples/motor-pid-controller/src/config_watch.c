/* Reload PID gains when the config file changes. */
#include "config_watch.h"
#include <stdio.h>
#include <sys/inotify.h>
#include <unistd.h>

int config_watch_start(const char *path)
{
    int fd = inotify_init1(IN_NONBLOCK);
    if (fd < 0) { perror("inotify_init1"); return -1; }
    if (inotify_add_watch(fd, path, IN_CLOSE_WRITE | IN_MODIFY) < 0) {
        perror("inotify_add_watch");
        close(fd);
        return -1;
    }
    return fd;
}

int config_watch_changed(int fd)
{
    char buf[4096];
    int changed = 0;
    while (read(fd, buf, sizeof buf) > 0)
        changed = 1;
    return changed;
}
