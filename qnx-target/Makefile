# Native QNX 8.0 code, built with qcc. Requires: source ~/qnx800/qnxsdp-env.sh
#   make            -> x86_64 (QEMU)
#   make ARCH=aarch64le   -> Raspberry Pi 5
#   make all-archs
ARCH ?= x86_64
VARIANT_x86_64    = gcc_ntox86_64
VARIANT_aarch64le = gcc_ntoaarch64le
VARIANT = $(VARIANT_$(ARCH))
ifeq ($(VARIANT),)
$(error unsupported ARCH '$(ARCH)': use x86_64 or aarch64le)
endif

CC      = qcc -V$(VARIANT)
CFLAGS  = -O2 -g -std=gnu11 -Wall -Wextra -Werror -D_QNX_SOURCE
OUT     = build/$(ARCH)

AGENT_SRCS = src/agent/qnx_advisor_agent.c src/agent/verify.c src/agent/bench.c
AGENT_HDRS = src/agent/agent.h src/agent/advisor_dcmd.h

all: $(OUT)/qnx-advisor-agent $(OUT)/advisorctl

$(OUT)/qnx-advisor-agent: $(AGENT_SRCS) $(AGENT_HDRS)
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) -o $@ $(AGENT_SRCS) -lslog2

$(OUT)/advisorctl: src/advisorctl/advisorctl.c src/agent/advisor_dcmd.h
	mkdir -p $(OUT)
	$(CC) $(CFLAGS) -o $@ src/advisorctl/advisorctl.c

all-archs:
	$(MAKE) ARCH=x86_64
	$(MAKE) ARCH=aarch64le

clean:
	rm -rf build

.PHONY: all all-archs clean
