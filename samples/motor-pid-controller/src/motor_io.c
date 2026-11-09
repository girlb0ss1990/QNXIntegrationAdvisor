/* Encoder over a USB serial adapter, PWM through Linux sysfs. */
#include "motor_io.h"
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <termios.h>

static int enc_fd = -1;
static int pwm_fd = -1;

int motor_io_open(const char *encoder_dev, const char *pwm_path)
{
    if (!encoder_dev) encoder_dev = "/dev/ttyUSB0";
    if (!pwm_path)    pwm_path    = "/sys/class/pwm/pwmchip0/pwm0/duty_cycle";

    enc_fd = open(encoder_dev, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (enc_fd < 0) { perror("open encoder"); return -1; }

    int bits = TIOCM_DTR;
    ioctl(enc_fd, TIOCMBIS, &bits);       /* wake the encoder bridge */

    pwm_fd = open(pwm_path, O_WRONLY);
    if (pwm_fd < 0) { perror("open pwm"); return -1; }
    return 0;
}

double motor_io_read_rpm(void)
{
    char buf[32];
    ssize_t n = read(enc_fd, buf, sizeof buf - 1);
    if (n <= 0) return -1.0;
    buf[n] = '\0';
    double rpm = 0.0;
    sscanf(buf, "%lf", &rpm);
    return rpm;
}

int motor_io_write_duty(double duty_pct)
{
    char buf[32];
    long ns = (long)(duty_pct * 500.0);   /* 50 us period */
    int len = snprintf(buf, sizeof buf, "%ld\n", ns);
    return (int)write(pwm_fd, buf, (size_t)len);
}

void motor_io_close(void)
{
    if (enc_fd >= 0) close(enc_fd);
    if (pwm_fd >= 0) close(pwm_fd);
}
