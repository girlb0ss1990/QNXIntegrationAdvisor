"""qnx-advisor command line: index-sdp | scan | kit | verify | serve | env."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import IntegrationReport


def _print_event(event: str, data: dict) -> None:
    msg = data.get("message")
    if msg:
        print(f"[{event:7s}] {msg}", file=sys.stderr)


def cmd_env(args) -> int:
    from .server import detect_env
    print(json.dumps(detect_env(args.sdp, args.target), indent=2))
    return 0


def cmd_index(args) -> int:
    from .sdp import build_index, locate_sdp, save_index
    sdp = locate_sdp(args.sdp)
    if sdp is None:
        print("QNX SDP not found. Source qnxsdp-env.sh or pass --sdp ~/qnx800.", file=sys.stderr)
        return 2
    idx = build_index(sdp, progress=lambda m: print("  " + m, file=sys.stderr))
    path = save_index(idx)
    print(json.dumps({**idx.summary(), "path": str(path)}, indent=2))
    return 0


def cmd_scan(args) -> int:
    from .export import to_markdown, to_sarif
    from .pipeline import Environment, analyze
    env = Environment.detect(args.sdp)
    res = analyze(args.source, ref=args.ref, arch=args.arch, use_llm=args.llm, env=env,
                  emit=_print_event, compile_kit_files=not args.no_qcc)
    r = res.report
    if args.format == "sarif":
        text = json.dumps(to_sarif(r), indent=2)
    elif args.format == "md":
        text = to_markdown(r)
    else:
        text = r.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    if args.kit:
        from .kit.generator import write_kit
        write_kit(r.kit, Path(args.kit))
        print(f"wrote porting kit to {args.kit}", file=sys.stderr)
    return 0


def cmd_kit(args) -> int:
    from .kit.generator import write_kit
    r = IntegrationReport.model_validate_json(Path(args.report).read_text(encoding="utf-8"))
    write_kit(r.kit, Path(args.out))
    print(f"wrote {len(r.kit)} files to {args.out}")
    return 0


def cmd_verify(args) -> int:
    from .pipeline import Environment
    from .verify.deploy import DeployError, Target
    from .verify.target import run_verification
    env = Environment.detect(args.sdp)
    if env.sdp is None:
        print("verify needs a local QNX SDP 8.0 to build the kit.", file=sys.stderr)
        return 2
    r = IntegrationReport.model_validate_json(Path(args.report).read_text(encoding="utf-8"))
    try:
        rec = run_verification(r, env.sdp, Target(args.target, port=args.port, key=args.key), args.arch, _print_event)
    except DeployError as e:
        print(f"verify failed: {e}", file=sys.stderr)
        return 1
    Path(args.report).write_text(r.model_dump_json(indent=2), encoding="utf-8")
    print(rec.model_dump_json(indent=2))
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .server import create_app
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("warning: binding beyond localhost exposes clone/scan to your network", file=sys.stderr)
    if args.open:
        import threading
        import time
        import urllib.request
        import webbrowser
        browse_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        url = f"http://{browse_host}:{args.port}/"

        def up() -> bool:
            try:
                with urllib.request.urlopen(url + "api/env", timeout=2) as r:
                    return r.status == 200
            except OSError:
                return False

        if up():   # already running (e.g. launcher double-clicked twice): just open a tab
            print(f"QNX Integration Advisor is already running at {url}", file=sys.stderr)
            webbrowser.open(url)
            return 0

        def open_when_ready() -> None:
            for _ in range(60):
                time.sleep(0.5)
                if up():
                    print(f"\n  QNX Integration Advisor is ready: {url}\n  Close this window to stop it.\n",
                          file=sys.stderr)
                    webbrowser.open(url)
                    return

        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(create_app(sdp=args.sdp, target=args.target), host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="qnx-advisor", description="QNX 8.0 integration advisor (local-first)")
    p.add_argument("--sdp", help="path to the QNX SDP 8.0 install (default: QNX_HOST/QNX_TARGET or ~/qnx800)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("env", help="show detected mode, SDP, index and target")
    s.add_argument("--target", help="user@host of a QNX target to probe")
    s.set_defaults(fn=cmd_env)

    s = sub.add_parser("index-sdp", help="index headers/macros/symbols of the local SDP (written to ~/.qnx-advisor)")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("scan", help="analyze a repository URL or local path")
    s.add_argument("source")
    s.add_argument("--ref")
    s.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64le"])
    s.add_argument("--llm", action="store_true", help="enable AI-assisted mode (needs a provider key)")
    s.add_argument("--format", default="json", choices=["json", "md", "sarif"])
    s.add_argument("--out")
    s.add_argument("--kit", help="also write the porting kit to this directory")
    s.add_argument("--no-qcc", action="store_true", help="skip qcc compile checks")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("kit", help="write the porting kit from a saved report.json")
    s.add_argument("report")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_kit)

    s = sub.add_parser("verify", help="build, deploy and measure on a QNX 8.0 target (updates report.json)")
    s.add_argument("report")
    s.add_argument("--target", required=True, help="user@host, e.g. qnxuser@10.0.2.15")
    s.add_argument("--port", type=int, default=22)
    s.add_argument("--key")
    s.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64le"])
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("serve", help="run the local web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--target", help="default QNX target user@host for live verification")
    s.add_argument("--open", action="store_true", help="open the UI in the default browser once it is ready")
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
