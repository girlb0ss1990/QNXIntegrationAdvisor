# QNX Integration Advisor - developer entry points (Linux / WSL2 / macOS).
# QNX targets need `source ~/qnx800/qnxsdp-env.sh` first.
PY      ?= .venv/bin/python
PIP     ?= .venv/bin/pip
ADVISOR ?= .venv/bin/qnx-advisor
TARGET  ?= qnxuser@$(shell cat qnx-target/vm/local/ip 2>/dev/null || echo 10.0.2.15)

.PHONY: setup web index-sdp rules-validate qnx-check agent vm target-test test lint eval samples static demo serve env-info clean

setup:                      ## venv + Python deps + web build (one command install)
	python3 -m venv .venv
	$(PIP) install -q -e ".[dev,llm]"
	$(MAKE) web

web:                        ## build the React SPA into advisor/static
	cd web && npm ci && npm run build

serve:                      ## run the local UI on http://127.0.0.1:8765
	$(ADVISOR) serve --target $(TARGET)

env-info:                   ## show mode, SDP, qcc version (from the compiler), index, target
	$(ADVISOR) env --target $(TARGET)

index-sdp:                  ## index the local SDP sysroot (written to ~/.qnx-advisor, gitignored)
	$(ADVISOR) index-sdp

rules-validate:             ## every recommended QNX API/header must exist in your SDP 8.0
	$(PY) -m advisor.rules.validate

qnx-check:                  ## render kits for all samples, compile with qcc for x86_64 + aarch64le
	$(PY) -m advisor.verify.qnx_check

agent:                      ## build the native target agent + advisorctl with qcc
	$(MAKE) -C qnx-target all-archs

vm:                         ## create/boot the mkqnximage QEMU target and install the agent
	qnx-target/vm/setup-vm.sh

target-test:                ## agent smoke test against the VM
	ssh -o BatchMode=yes $(TARGET) /data/home/qnxuser/bin/advisorctl info
	ssh -o BatchMode=yes $(TARGET) /data/home/qnxuser/bin/advisorctl bench-ipc --iterations 1000
	ssh -o BatchMode=yes $(TARGET) /data/home/qnxuser/bin/advisorctl bench-timer --duration-ms 1000

test:                       ## unit + API tests (no SDP needed)
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check advisor tests eval scripts

eval:                       ## precision/recall against hand-labelled expectations
	$(PY) eval/score.py

samples:                    ## regenerate docs/sample-reports
	$(PY) scripts/export_samples.py

static:                     ## M0 static viewer (pre-generated sample reports) for GitHub Pages
	cd web && npm run build:static
	$(PY) scripts/export_samples.py --static

demo:                       ## end to end: scan sample -> kit -> verify on the VM (M3)
	$(ADVISOR) scan samples/motor-pid-controller --out out/motor.json --kit out/motor-kit
	$(ADVISOR) verify out/motor.json --target $(TARGET)
	$(PY) -c "import json;r=json.load(open('out/motor.json'));json.dump(r['verification'][-1],open('docs/sample-verification-record.json','w'),indent=2)"

clean:
	rm -rf out web/dist-static qnx-target/build
