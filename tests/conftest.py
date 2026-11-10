from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from advisor.sdp.indexer import SysrootIndex  # noqa: E402

SAMPLES = REPO / "samples"


@pytest.fixture
def fake_index() -> SysrootIndex:
    """A tiny stand-in for a real SDP 8.0 index (names only), shaped like the real thing."""
    symbols = {
        # libc
        **{s: ["c"] for s in [
            "poll", "select", "pipe", "read", "write", "open", "ioctl", "devctl", "timer_create", "timer_settime",
            "clock_nanosleep", "clock_gettime", "ChannelCreate", "ConnectAttach", "MsgReceivePulse", "MsgSendPulse",
            "MsgDeliverEvent", "MsgSend", "MsgReceive", "ionotify", "pulse_attach", "dispatch_create", "iofunc_func_init",
            "iofunc_attr_init", "resmgr_attach", "dispatch_context_alloc", "dispatch_block", "dispatch_handler",
            "iofunc_devctl_default", "procmgr_ability", "procmgr_daemon", "procmgr_event_notify_add",
            "setuid", "setgid", "ThreadCtl", "pthread_mutexattr_init",
            "pthread_mutexattr_setprotocol", "pthread_attr_setschedpolicy", "pthread_attr_setschedparam",
            "pthread_getcpuclockid", "ClockId", "posix_spawn", "posix_spawnattr_init", "waitpid", "waitid", "sigwaitinfo",
            "pthread_sigmask", "pthread_create", "dlopen", "shm_open", "mmap", "posix_typed_mem_open", "syslog"]},
        "socket": ["socket"],
        "inotify_add_watch": ["fsnotify"],
        "slog2_register": ["slog2"], "slog2f": ["slog2"], "slog2_set_default_buffer": ["slog2"],
    }
    macros = {"SIGEV_PULSE_INIT", "PTHREAD_PRIO_INHERIT", "SCHED_SPORADIC", "_NTO_TCTL_RUNMASK_GET_AND_SET_INHERIT",
              "RMSK_SET", "DCMD_PROC_INFO", "DCMD_PROC_MAPINFO", "PROCMGR_EVENT_DAEMON_DEATH"}
    headers = {"sys/inotify.h", "sys/neutrino.h", "sys/dispatch.h", "sys/iofunc.h", "devctl.h", "pthread.h", "sched.h",
               "sys/siginfo.h", "sys/procmgr.h", "spawn.h", "sys/wait.h", "sys/slog2.h", "sys/mman.h", "time.h", "poll.h"}
    return SysrootIndex(sdp_version="8.0.3", qcc_version="ntox86_64-gcc (GCC) test", archs=["x86_64", "aarch64le"],
                        headers=headers, macros=macros, symbols=symbols,
                        libraries={"c", "m", "socket", "fsnotify", "slog2", "ham"})
