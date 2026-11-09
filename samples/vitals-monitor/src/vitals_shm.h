#ifndef VITALS_SHM_H
#define VITALS_SHM_H

#include <stdint.h>

typedef struct {
    uint32_t seq;
    uint16_t spo2;          /* tenths of a percent */
    uint16_t bpm;
    double   board_temp_c;
} vitals_shm_t;

#endif
