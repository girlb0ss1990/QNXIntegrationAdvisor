#include "pid.h"

void pid_init(pid_ctrl_t *p, double kp, double ki, double kd, double lo, double hi)
{
    p->kp = kp; p->ki = ki; p->kd = kd;
    p->integral = 0.0; p->prev_error = 0.0;
    p->out_min = lo; p->out_max = hi;
}

double pid_step(pid_ctrl_t *p, double setpoint, double measured, double dt_s)
{
    double err = setpoint - measured;
    p->integral += err * dt_s;
    double deriv = (err - p->prev_error) / dt_s;
    p->prev_error = err;
    double out = p->kp * err + p->ki * p->integral + p->kd * deriv;
    if (out > p->out_max) out = p->out_max;
    if (out < p->out_min) out = p->out_min;
    return out;
}
