#ifndef MOTOR_IO_H
#define MOTOR_IO_H

int    motor_io_open(const char *encoder_dev, const char *pwm_path);
double motor_io_read_rpm(void);
int    motor_io_write_duty(double duty_pct);
void   motor_io_close(void);

#endif
