#ifndef STATS_H
#define STATS_H

#include <stdint.h>

#define MAX_IDS 256

typedef struct {
    uint32_t id;
    uint32_t count;
    uint32_t count_prev_window;
    uint8_t  last[8];
    uint8_t  dlc;
} can_id_stat_t;

typedef struct {
    can_id_stat_t ids[MAX_IDS];
    unsigned      n;
} can_stats_t;

void stats_init(can_stats_t *s);
void stats_add(can_stats_t *s, uint32_t id, uint8_t dlc, const uint8_t *data);
void stats_roll(can_stats_t *s);
void stats_dump(const can_stats_t *s, int fd);

#endif
