# vitals-monitor (sample)

An original, intentionally Linux-specific sample for QNX Integration Advisor demos.
Samples a pulse-oximeter over `/dev/i2c-1`, publishes readings in POSIX shared memory,
signals a consumer with `eventfd`, `fork()`s an alarm script, insists on running as
root, and relies on a cron watchdog script for restarts. Not a medical device.

License: MIT.
