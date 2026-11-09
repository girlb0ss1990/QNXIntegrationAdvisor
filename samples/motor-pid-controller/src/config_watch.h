#ifndef CONFIG_WATCH_H
#define CONFIG_WATCH_H

int  config_watch_start(const char *path);   /* returns an fd usable with epoll */
int  config_watch_changed(int fd);           /* drains events, returns 1 on change */

#endif
