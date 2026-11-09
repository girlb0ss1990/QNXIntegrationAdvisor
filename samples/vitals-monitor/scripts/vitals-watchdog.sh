#!/bin/sh
# Restart vitals_monitor if it dies. Run from cron every minute.
if ! pgrep -x vitals_monitor >/dev/null; then
    logger -t vitals-watchdog "vitals_monitor not running, restarting"
    /usr/local/bin/vitals_monitor &
fi
