CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra
LDLIBS  = -lpthread -lrt

OBJS = src/candaemon.o src/stats.o

candaemon: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LDLIBS)

install: candaemon
	install -m 755 candaemon /usr/local/sbin/
	install -m 644 candaemon.service /etc/systemd/system/

clean:
	rm -f candaemon $(OBJS)

.PHONY: install clean
