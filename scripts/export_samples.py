"""Generate reports for the bundled samples.

  docs/sample-reports/<sample>.json   served by `qnx-advisor serve` under /api/samples
  web/dist-static/reports/            the M0 static viewer (GitHub Pages), with --static

Reports contain only our own analysis of our own sample code: no QNX SDP content.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from advisor.export import to_markdown  # noqa: E402
from advisor.pipeline import Environment, analyze  # noqa: E402


def main() -> int:
    out = REPO / "docs" / "sample-reports"
    out.mkdir(parents=True, exist_ok=True)
    env = Environment.detect()
    index = []
    for sample in sorted((REPO / "samples").iterdir()):
        if not sample.is_dir():
            continue
        res = analyze(str(sample), env=env)
        r = res.report
        r.repo_url = f"samples/{sample.name}"
        (out / f"{sample.name}.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
        (out / f"{sample.name}.md").write_text(to_markdown(r), encoding="utf-8")
        index.append({"name": sample.name, "url": f"reports/{sample.name}.json"})
        print(f"{sample.name}: {len(r.findings)} findings, score {r.readiness_score}, mode {r.mode}")
    if "--static" in sys.argv:
        dist = REPO / "web" / "dist-static"
        if not dist.is_dir():
            print("build the static viewer first: cd web && npm run build:static", file=sys.stderr)
            return 1
        rep = dist / "reports"
        rep.mkdir(exist_ok=True)
        for p in out.glob("*.json"):
            shutil.copy(p, rep / p.name)
        (rep / "index.json").write_text(json.dumps(index), encoding="utf-8")
        print(f"static viewer ready in {dist}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
