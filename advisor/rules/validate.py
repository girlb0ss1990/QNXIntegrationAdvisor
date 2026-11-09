"""Rule self-validation: every QNX API/header the rule DB recommends must exist in the
local SDP 8.0 sysroot index. Run with `make rules-validate` (needs `qnx-advisor index-sdp`)."""
from __future__ import annotations

import sys

from ..sdp.indexer import SysrootIndex, load_index
from . import load_features, load_rules

# Alternatives of kind "build"/"design" may name APIs that only document intent.
CHECKED_KINDS = {"posix", "qnx_native", "build"}


def validate(idx: SysrootIndex) -> list[str]:
    problems: list[str] = []
    for r in load_rules():
        for alt in r.alternatives:
            if alt["kind"] not in CHECKED_KINDS:
                continue
            for api in alt.get("apis", []):
                if not idx.known(api):
                    problems.append(f"{r.id}: '{api}' not found in sysroot (symbols, macros or declarations)")
    for name, feat in load_features().items():
        for api in feat.get("apis", []):
            if not idx.known(api):
                problems.append(f"feature {name}: '{api}' not found in sysroot")
        for hdr in feat.get("headers", []):
            if not idx.has_header(hdr):
                problems.append(f"feature {name}: <{hdr}> not found in sysroot")
    return problems


def main() -> int:
    idx = load_index()
    if idx is None:
        print("No sysroot index. Run `qnx-advisor index-sdp` first (needs a local QNX SDP 8.0).", file=sys.stderr)
        return 2
    problems = validate(idx)
    print(f"Validated rule DB against SDP {idx.sdp_version} index ({len(idx.symbols)} symbols, {len(idx.macros)} macros)")
    for p in problems:
        print("  MISSING", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
