# How QNX Integration Advisor works (in plain English)

This guide is for solo developers and small teams. It explains what the tool does, what you need, and how
to use it, step by step, without assuming you know QNX.

---

## The short version

You have some C or C++ code that runs on Linux. You want to know:

1. **Would it be better on QNX?**
2. **What would I have to change?**
3. **Does it actually work on QNX?**

You give the tool your code (a GitHub link or a folder on your computer). It reads the code and answers
all three questions in a web page. If you have QNX installed, it also builds the code with the real QNX
compiler and runs it on a small QNX computer that lives inside your PC (a "virtual machine").

---

## A few words you will see

| Word | What it means |
| :--- | :--- |
| **QNX** | An operating system, like Linux or Windows, used in cars, robots, medical devices and factories. Its big strength is timing: important code runs *exactly when it should*, even when the computer is busy. |
| **QNX SDP** | The free QNX developer kit you install on your PC. It contains the QNX compiler and the QNX libraries. |
| **qcc** | The QNX compiler. It turns C/C++ source code into a program that runs on QNX. It only runs on Linux. |
| **WSL** | "Windows Subsystem for Linux": a real Linux (Ubuntu) running inside Windows. On Windows, the QNX SDP is installed there. |
| **Virtual machine (VM)** | A pretend computer running inside your PC. The tool starts one running QNX 8.0, so you don't need any special hardware. It uses a program called QEMU. |
| **Porting** | Changing code written for one operating system so that it works on another. |
| **Resource manager** | The QNX way of offering a service. Your program shows up as a file such as `/dev/motor_pid`, and other programs talk to it by opening that file. |

---

## What you need

| You want to... | You need |
| :--- | :--- |
| Read the sample reports | Nothing. Just open the tool. |
| Analyze your own code | **Python 3.11 or newer** and **Git** |
| Get AI-written explanations (optional) | An API key from OpenRouter, Anthropic, Google or OpenAI |
| Build with the QNX compiler and run on QNX | The **QNX SDP 8.0** (free for non-commercial use from QNX Everywhere). On Windows, install it inside **WSL Ubuntu**. |

You do **not** need a Raspberry Pi or any other hardware. The QNX virtual machine is enough.

---

## How to use it, step by step

### 1. Start the tool

- **Windows:** open the `qnx-integration-advisor` folder and double-click **`start.bat`**.
- **Linux or macOS:** open a terminal in that folder and run `./start.sh`.

A black window opens. The first time, it installs what it needs, which takes a few minutes. After that,
starting takes seconds. **Keep this window open while you use the tool. Closing it stops the tool.**

**On Windows with QNX installed in WSL**, the window asks:

```
Start in QNX mode [Y,N]?
```

Press **Y**. This is what lets the tool use the QNX compiler and the QNX virtual machine (see
"Windows mode or QNX mode?" below).

Your web browser then opens the tool at **http://127.0.0.1:8765**. It runs only on your computer.
Nothing is uploaded anywhere (unless you turn on AI, see step 6).

### 2. Check everything is connected

Click **⚙ Setup** in the top-right corner. You'll see a checklist:

| Line | What a green tick means | If it isn't green |
| :--- | :--- | :--- |
| **Git** | The tool can download code from GitHub | Install Git from git-scm.com |
| **C/C++ code parser** | The tool can read your code accurately | Run the launcher again |
| **AI assistant** | Optional. Your AI key works. | Ignore it, or add a key (step 6) |
| **QNX SDP 8.0** | The QNX compiler was found | Start in QNX mode (Windows), or install the SDP |
| **QNX library index** | The tool knows every function in your QNX version, so it never recommends one that doesn't exist | Done automatically the first time |
| **QNX 8.0 target** | The QNX virtual machine is running | Click **Start QNX virtual machine** and wait about a minute |

The little badge at the top right shows how much the tool can do right now:

- **M1**: analysis only
- **M2**: analysis plus AI explanations
- **M3**: everything, including building and running on QNX

### 3. Analyze some code

Click **Back to analysis**. In the box at the top, type one of these:

- a GitHub link, e.g. `https://github.com/owner/project`
- a folder on your computer, e.g. `C:\Users\me\code\my-project`
- a built-in example: `samples/motor-pid-controller`

Then press **Analyze**. It takes a few seconds to a minute. Your code is only **read**. It is never run on
your PC.

> **Tip:** the tool understands C and C++ only. A project written in JavaScript, Python and so on is
> marked "not applicable" instead of being given a score.

### 4. Read the results

The report has five tabs.

**Why QNX?**
The tool's verdict: **Strong fit**, **Good fit**, **Possible fit** or **Limited benefit**. Below it are
cards, one for each thing QNX would give your project. For example:

- *Predictable timing for time-critical work*, because your code has a control loop that must run on time.
- *A driver crash does not take the system down*, because your code talks to hardware.

Every card shows **where in your code** the evidence is (file and line), so you can check it yourself. The
tool never makes up speed numbers. If QNX wouldn't help much, it says so.

**Audit**
A list of every place your code uses something that only exists on Linux, each with the QNX replacement.
They are sorted by how serious they are:

| Level | Meaning |
| :--- | :--- |
| Blocker | Won't build on QNX until changed |
| High | Builds, but behaves differently; should change |
| Medium / Low | Worth improving |
| Info | Just so you know |

**3-pillar report**
The full plan, in three parts:

1. **Which QNX features are relevant** to your code, and why.
2. **What would improve** on QNX, linked to the exact lines.
3. **Step-by-step instructions**, with before/after code and a command to check each step worked.

**Porting kit**
Ready-made files to get you started:

- a QNX resource manager for your service
- small "shim" files that stand in for Linux-only functions
- build settings for the QNX compiler
- a self-test

You can download it all with the **Download kit (.zip)** button.

**Verify on QNX**
This is where the tool proves the code works on QNX (step 5).

You can also download the whole report as **report.md** (a readable document) or **SARIF** (for code
review tools such as GitHub code scanning).

### 5. Run it on QNX (QNX mode only)

1. Open the **Verify on QNX** tab.
2. Make sure the **Target** box shows something like `qnxuser@172.31.1.232` (the virtual machine).
   It's filled in for you.
3. Press **Run on QNX 8.0**.

You'll see a log as it works, then a checklist:

```
✓ Compiled with QNX qcc (SDP 8.0.0) and copied to the target
✓ Ran on QNX 8.0.0 (qemu x86_64)
✓ Your service registered /dev/motor_pid 11.7 ms after start, then the agent stopped it as planned
✓ The compatibility self-test passed on QNX
✓ Measured QNX message passing: median round trip ...
✓ Measured a 1 kHz real-time timer under CPU load: ...
```

What happened behind the scenes:

1. **Build:** the QNX compiler (qcc) turned the generated code into QNX programs.
2. **Copy:** the programs were sent to the QNX virtual machine.
3. **Run:** a small helper program on QNX (the "agent") started your service and checked it appeared
   as `/dev/<name>`.
4. **Test:** the self-test ran on QNX.
5. **Measure:** the agent timed how fast QNX passes messages between programs and how accurately a
   timer fires, both with the computer idle and while it's busy.

> **About the numbers:** a virtual machine shares your PC with everything else, so its timings are only a
> rough guide. Measure on real hardware before relying on them.

A ✕ instead of a ✓ tells you exactly which step failed. The log above it shows the compiler's error
messages.

### 6. Optional: turn on AI

Without AI, the reports are complete. AI only rewrites the explanations to talk about *your* project
specifically, and adds diagrams.

1. Click **⚙ Setup**.
2. Choose a provider. **OpenRouter** is the easiest: one key for many AI models.
3. Click the link to get a key, paste it in, and press **Save and test connection**.
4. Back on the main page, tick **AI-assisted** before you press Analyze.

Good to know:

- Your key is saved only on your computer and is shown only partly hidden (masked).
- The AI provider charges for each AI-assisted analysis.
- The tool fact-checks the AI. Any QNX function it mentions that doesn't exist in your QNX version is
  removed, and any invented speed number is deleted.

---

## Windows mode or QNX mode?

The QNX compiler only runs on Linux. On Windows, that Linux is WSL. So on Windows the tool can run in two
ways:

| | Windows mode | QNX mode |
| :--- | :--- | :--- |
| How to start | `start.bat`, answer **N** (or no QNX installed) | `start.bat`, answer **Y** |
| Where the tool runs | Windows | Inside WSL Ubuntu, next to your QNX SDP |
| Analysis, Why QNX?, audit, kit | ✓ | ✓ |
| Checked against your QNX version | ✓ (after "Use my WSL QNX SDP" on the Setup page) | ✓ |
| Generated code built with the QNX compiler | ✕ | ✓ |
| Run and measure on the QNX virtual machine | ✕ | ✓ |

If you see *"The QNX compiler (qcc) only runs on Linux, so on Windows generated code is not
compile-checked"*, you're in Windows mode. Close the tool and start it again with **Y**.

In QNX mode, the launcher does the fiddly parts for you:

- It switches on the virtualization support and network that the QNX virtual machine needs.
- It runs the tool inside WSL and opens your normal Windows browser.
- It starts the QNX virtual machine in the background.
- It uses the AI key you saved on Windows.

---

## What happens under the hood (for the curious)

```
 your code ──► 1. Read ──► 2. Check ──► 3. Explain ──► 4. Generate ──► 5. Build ──► 6. Run on QNX
             (download    (find Linux-  (Why QNX?,    (porting kit)   (qcc)        (virtual machine,
              and parse)   only APIs)    3-pillar)                                  measure)
```

1. **Read:** the code is downloaded (only the files the tool needs, so even big projects are quick) and
   read with a proper C/C++ parser.
2. **Check:** about 30 hand-written rules look for Linux-only features. Every QNX function the tool
   recommends is checked against an index of *your* QNX installation.
3. **Explain:** the tool works out what your program is (a control loop, a device driver, a background
   service and so on), decides what QNX would give it, and writes the report. AI can reword this; it can't
   change the facts.
4. **Generate:** it fills in templates to make the porting kit for your project.
5. **Build:** with QNX installed, qcc compiles the kit for both Intel/AMD (x86_64) and Raspberry Pi
   (aarch64le) style processors.
6. **Run:** the programs are copied to the QNX virtual machine, started by the agent, tested and
   measured. The result is saved as a "verification record", linked to the exact program that ran.

---

## Common problems

| What you see | What to do |
| :--- | :--- |
| "Python 3.11 or newer is required" | Install Python from python.org (tick "Add python.exe to PATH"), then start again |
| `start.bat` never asks about QNX mode | The tool didn't find QNX inside WSL. Check that a `qnx800` folder exists in your Ubuntu home folder. |
| "QNX mode could not start", then it continues in Windows mode | Read the lines just above that message: they say what went wrong |
| The browser opens the old version | An earlier copy is still running. Close all the tool's black windows and start again. |
| Setup says the QNX target isn't running | Click **Start QNX virtual machine** and wait about a minute |
| "QEMU networking is not set up" (Linux only) | Run `sudo qnx-target/vm/host-prep.sh $USER` once after each restart |
| GitHub link fails | Check the link opens in your browser and the project is public |
| "Not applicable" | The project has no C/C++ code, so there's nothing for the tool to check |

---

## Privacy and safety

- Everything runs **on your own computer**.
- Your code is read, never run on your PC. It only runs inside the QNX virtual machine, and only when you
  press **Run on QNX**.
- If you turn on AI, the findings and short excerpts of the relevant code are sent to the AI provider you chose. Without AI, nothing
  leaves your computer except downloading the repository you asked for.
- QNX's own files (the SDP, the virtual machine image) are never added to the project or uploaded.
