# QNX Global Hackathon 2026: submission pack

Everything the Devpost form asks for, ready to copy. The category is **Developer Tooling & Host Tools**.

## Project name

**QNX Integration Advisor**: paste a Linux C/C++ repository, find out why and how it should run on QNX, and
watch the generated QNX code run on a QNX 8.0 target, in one place.

## Elevator pitch (≤ 200 characters)

Paste a Linux C/C++ repo. Get an evidence-backed "Why QNX?" verdict, a QNX porting kit built with qcc, and
proof it runs: deployed to a QNX 8.0 VM and measured, in one click.

## Text description

**The problem.** A solo developer or small team with a Linux C/C++ service (a motor controller, a CAN
logger, a medical monitor) has no cheap way to answer three questions: *would this benefit from QNX?*,
*what would I have to change?* and *does it actually work there?*. Answering them today means reading
thousands of pages of documentation, installing the SDP, learning resource managers and building a target
image before writing a line of useful code.

**What it does.** QNX Integration Advisor answers all three from a GitHub URL or a local folder.

1. **Why QNX?** It scans the code (tree-sitter C/C++ parser + 30 hand-written rules) and says, with file and
   line evidence, which QNX capabilities the project would gain: hard real-time scheduling for its periodic
   loops, a microkernel that keeps a driver crash from taking the system down, priority-aware message
   passing, least-privilege abilities, and a path to safety certification. It gives an overall fit
   (strong / good / possible / limited) and says honestly when QNX would add little. It never invents
   performance numbers.
2. **What to change.** An audit lists every Linux-only API (epoll, timerfd, inotify, SocketCAN, systemd,
   /proc, prctl capabilities and more), each with the QNX 8.0 replacement. Every recommended QNX function
   and header is checked against the user's own SDP sysroot index, so nothing is hallucinated.
3. **A porting kit.** It generates a QNX resource manager that exposes the service as `/dev/<name>`
   (`dispatch_create`, `resmgr_attach`, `iofunc_*`), compatibility shims, a `procmgr_ability`
   least-privilege setup, a CMake toolchain file and a self-test, and compiles it with the SDP's `qcc` for
   x86_64 and aarch64le.
4. **Proof on QNX.** One click on **Run on QNX 8.0** copies the build to a QNX 8.0 target (a QEMU VM the tool
   creates from the user's SDP with `mkqnximage`), where our native on-target agent
   (`qnx-advisor-agent`, itself a QNX resource manager at `/dev/advisor`) spawns the generated service,
   checks that its `/dev` path appears, runs the self-test and measures `MsgSend` round trips and SCHED_FIFO
   timer lateness under load with `ClockCycles()`. The result is a verification record tied to the
   binary's SHA-256.

**Made for people new to QNX.** Every report opens on a **Start here** tab. It explains the QNX ideas
this project needs in plain English, each with an everyday analogy, and lays out a tailored, checkable path
from "never used QNX" to "running on QNX". An **Ask the advisor** box lets a beginner ask questions such as
"what is a resource manager?" or "how do I fix this?". The answers are about their own code, and they are
fact-checked against their SDP just like the rest of the AI output.

**Built for solo developers.** Double-click `start.bat` (Windows) or run `./start.sh` (Linux/macOS). A Setup
page checks Git, the parser, the AI key, the QNX SDP and the QNX target, and explains how to fix anything
missing in plain language. On Windows, the launcher finds a QNX SDP installed in WSL and offers **QNX
mode**: it prepares KVM and QEMU networking, runs the tool inside WSL with the SDP, and boots the QNX VM in
the background, so `qcc` builds and on-target runs work from the Windows browser with no terminal. AI is
optional (OpenRouter, Anthropic, Gemini or OpenAI). It only rewrites explanations, and a guard deletes any
API or header it mentions that is not in the SDP. Without AI, every report is complete and deterministic.

**Why a real-time foundation matters here.** The tool doesn't just say "QNX is real-time". It measures it on
the user's own target: the Verify tab shows the 1 kHz timer lateness histogram idle and with four CPU
burner threads, next to the code locations that need that predictability.

## How it uses QNX (for reviewers)

| What | Where |
| :--- | :--- |
| Native QNX resource manager `/dev/advisor`: `dispatch_create`, `resmgr_attach`, `iofunc_*`, `pulse_attach`, `message_connect` | [`qnx-target/src/agent/qnx_advisor_agent.c`](../qnx-target/src/agent/qnx_advisor_agent.c) |
| devctl protocol (`__DIOTF`), `posix_spawn` with SCHED attributes, async `MsgReplyv`, timer pulses | [`qnx-target/src/agent/verify.c`](../qnx-target/src/agent/verify.c), [`advisor_dcmd.h`](../qnx-target/src/agent/advisor_dcmd.h) |
| `ClockCycles()` benchmarks: `MsgSend` round trips, SCHED_FIFO pulse-timer lateness under load | [`qnx-target/src/agent/bench.c`](../qnx-target/src/agent/bench.c) |
| Least privilege with `procmgr_ability`, a secpol policy, slog2 logging | `qnx_advisor_agent.c`, [`qnx-target/secpol/advisor.pol`](../qnx-target/secpol/advisor.pol) |
| Generated QNX code: resource manager, shims, abilities, toolchain file | [`advisor/kit/templates/`](../advisor/kit/templates/) |
| `qcc` builds (x86_64 + aarch64le, `-Wall -Wextra -Werror`) | [`qnx-target/Makefile`](../qnx-target/Makefile), [`advisor/sdp/toolchain.py`](../advisor/sdp/toolchain.py), [`docs/qnx-check-log.txt`](qnx-check-log.txt) |
| Sysroot index from the SDP (`nto*-nm`) used to validate every recommendation | [`advisor/sdp/indexer.py`](../advisor/sdp/indexer.py), [`advisor/rules/validate.py`](../advisor/rules/validate.py) |
| QEMU target from `mkqnximage`, boot + agent install | [`qnx-target/vm/`](../qnx-target/vm/), [`advisor/qnxvm.py`](../advisor/qnxvm.py) |
| Measured output from QNX 8.0 | [`docs/sample-verification-record.json`](sample-verification-record.json) |

## Build and run instructions

| Item | Value |
| :--- | :--- |
| QNX version | QNX SDP 8.0.0 (QNX Everywhere, non-commercial licence) |
| Target | QNX 8.0.0 x86_64 on QEMU (`mkqnximage --type=qemu --arch=x86_64`); aarch64le builds for Raspberry Pi 5 |
| Toolchain | `qcc` from the SDP (`-Vgcc_ntox86_64`, `-Vgcc_ntoaarch64le`; GCC 12.2.0) |
| Host | Windows 11 + WSL2 Ubuntu 24.04, or native Ubuntu 24.04. Python 3.11+, Git, QEMU |

**Quick start (the way a judge would try it):**

1. Install QNX SDP 8.0 with QNX Software Center (inside WSL Ubuntu on Windows) and
   `sudo apt install qemu-system-x86 bridge-utils dnsmasq python3-venv git`.
2. Clone this repository and double-click `start.bat` (Windows; answer **Y** to QNX mode) or run
   `./start.sh` (Linux). The first run installs dependencies and indexes the SDP.
3. Open **⚙ Setup**: every line should be green. If the QNX target isn't running, press
   **Start QNX virtual machine** (on Linux the first boot after a restart needs
   `sudo qnx-target/vm/host-prep.sh $USER` once).
4. Paste `samples/motor-pid-controller` (or any GitHub URL) and press **Analyze**. Read **Why QNX?**, then
   open **Verify on QNX** and press **Run on QNX 8.0**.

**Command line equivalents:**

```bash
source ~/qnx800/qnxsdp-env.sh
make setup              # Python venv + web UI
make index-sdp          # index the SDP sysroot
make agent              # qcc: on-target agent + advisorctl for x86_64 and aarch64le
make qnx-check          # render kits for all samples and compile them with qcc
make vm                 # create/boot the QEMU target and install the agent
make demo               # scan -> kit -> qcc -> deploy -> verify -> measure
```

## Demo video script (under 3 minutes)

| Time | Show | Say |
| :--- | :--- | :--- |
| 0:00 to 0:15 | Title, then the motor controller sample's code | "This is a Linux motor controller. Would it be better on QNX, and how would I get it there?" |
| 0:15 to 0:35 | Double-click `start.bat`, answer Y, the browser opens; Setup page all green, QNX VM running | "One double-click. It finds my QNX SDP in WSL, starts a QNX 8.0 virtual machine and checks everything." |
| 0:35 to 1:05 | Paste the sample, Analyze, **Why QNX?** tab: strong fit, evidence links | "It explains, with file and line evidence, what QNX gives this code: hard real-time for the control loop, crash isolation for the driver code, and no made-up numbers." |
| 1:05 to 1:30 | Audit tab, then Porting kit: the generated resource manager | "Every Linux-only call, with the QNX replacement, checked against my SDP. And a generated resource manager that exposes the service as /dev/motor_pid." |
| 1:30 to 2:20 | Verify tab, **Run on QNX 8.0**, the log streams: qcc, deploy, verify, bench; outcome checklist and histograms | "One click: built with qcc, copied to QNX, started under our on-target agent, /dev/motor_pid appears, the self-test passes, and we measure QNX message passing and timer accuracy under load." |
| 2:20 to 2:45 | Paste a GitHub URL (e.g. a CAN tool); Why QNX shows a different verdict, or "limited" for a web app | "It's honest: when QNX would add little, it says so." |
| 2:45 to 2:55 | README "Evidence of QNX use" table | "Open source, Apache-2.0, and it runs on the free QNX 8.0." |

Record at 1080p. Use no copyrighted music, and keep third-party logos out of the frame.
