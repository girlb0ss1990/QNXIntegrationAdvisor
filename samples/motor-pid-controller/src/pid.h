#ifndef PID_H
#define PID_H

typedef struct {
    double kp, ki, kd;
    double integral;
    double prev_error;
    double out_min, out_max;
} pid_ctrl_t;

void   pid_init(pid_ctrl_t *p, double kp, double ki, double kd, double lo, double hi);
double pid_step(pid_ctrl_t *p, double setpoint, double measured, double dt_s);

#endif
