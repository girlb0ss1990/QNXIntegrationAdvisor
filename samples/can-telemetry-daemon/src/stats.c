#include "stats.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>

void stats_init(can_stats_t *s) { memset(s, 0, sizeof *s); }

void stats_add(can_stats_t *s, uint32_t id, uint8_t dlc, const uint8_t *data)
{
    for (unsigned i = 0; i < s->n; i++) {
        if (s->ids[i].id == id) {
            s->ids[i].count++;
            s->ids[i].dlc = dlc;
            memcpy(s->ids[i].last, data, dlc > 8 ? 8 : dlc);
            return;
        }
    }
    if (s->n < MAX_IDS) {
        can_id_stat_t *e = &s->ids[s->n++];
        e->id = id; e->count = 1; e->dlc = dlc;
        memcpy(e->last, data, dlc > 8 ? 8 : dlc);
    }
}

void stats_roll(can_stats_t *s)
{
    for (unsigned i = 0; i < s->n; i++) {
        s->ids[i].count_prev_window = s->ids[i].count;
        s->ids[i].count = 0;
    }
}

void stats_dump(const can_stats_t *s, int fd)
{
    char line[96];
    for (unsigned i = 0; i < s->n; i++) {
        int len = snprintf(line, sizeof line, "%03X %u/s dlc=%u\n",
                           s->ids[i].id, s->ids[i].count_prev_window, s->ids[i].dlc);
        write(fd, line, (size_t)len);
    }
}
