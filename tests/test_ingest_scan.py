from __future__ import annotations

from pathlib import Path

import pytest

from advisor.ingest import IngestError, ingest, parse_url
from advisor.rules import config_globs, interesting_tokens
from advisor.scanner import ast_c_cpp, scan_repo
from conftest import SAMPLES


@pytest.mark.parametrize("url,clone,ref", [
    ("https://github.com/owner/repo", "https://github.com/owner/repo.git", None),
    ("https://github.com/owner/repo.git", "https://github.com/owner/repo.git", None),
    ("https://github.com/owner/repo/tree/v1.2", "https://github.com/owner/repo.git", "v1.2"),
    ("https://gitlab.com/group/sub/repo", "https://gitlab.com/group/sub/repo.git", None),
    ("https://gitlab.com/group/repo/-/tree/main", "https://gitlab.com/group/repo.git", "main"),
    ("https://bitbucket.org/team/repo/src/dev", "https://bitbucket.org/team/repo.git", "dev"),
])
def test_parse_url_valid(url, clone, ref):
    assert parse_url(url) == (clone, ref)


@pytest.mark.parametrize("url", [
    "http://github.com/a/b", "https://evil.com/a/b", "https://github.com/a", "git@github.com:a/b.git",
    "https://github.com/a/b;rm -rf /", "https://github.com/../b", "https://github.com/a/b/tree/--upload-pack=x",
    "file:///etc/passwd",
])
def test_parse_url_rejects(url):
    with pytest.raises(IngestError):
        parse_url(url)


def test_local_ingest_hides_path():
    repo = ingest(str(SAMPLES / "motor-pid-controller"))
    assert repo.source == "local:motor-pid-controller"
    assert not repo.is_temp


def _scan(name: str):
    return scan_repo(SAMPLES / name, interesting_tokens(), config_globs())


def test_scan_extracts_includes_calls_and_roles():
    sr = _scan("motor-pid-controller")
    includes = {h.name for h in sr.hits if h.kind == "include"}
    assert {"sys/epoll.h", "sys/timerfd.h", "sys/inotify.h"} <= includes
    assert sr.has_call("timerfd_create") and sr.has_call("epoll_wait")
    assert sr.service_name == "motor_pid"
    assert sr.main_struct == ("pid_ctrl_t", "src/pid.h")
    assert {"device_service", "periodic_control_loop"} <= set(sr.roles)
    assert "pthread" in sr.build.link_libs and "rt" in sr.build.link_libs
    assert "main" in sr.repo_symbols


def test_guard_and_loop_context(tmp_path: Path):
    (tmp_path / "a.c").write_text(
        "#include <stdio.h>\n"
        "#ifdef __linux__\n#include <sys/epoll.h>\nint f(void){ return epoll_create1(0); }\n#endif\n"
        "int g(void){ for(;;){ usleep(10); } }\n"
        "int h(void){ usleep(10); return 0; }\n", encoding="utf-8")
    hits = ast_c_cpp.scan_file(tmp_path / "a.c", "a.c", set())
    epoll = [h for h in hits if h.name == "epoll_create1"][0]
    assert epoll.guarded
    sleeps = sorted((h.line, h.in_loop) for h in hits if h.name == "usleep")
    assert sleeps == [(6, True), (7, False)]


def test_regex_fallback_finds_the_same_calls(monkeypatch):
    src = SAMPLES / "can-telemetry-daemon" / "src" / "candaemon.c"
    ts = {(h.kind, h.name) for h in ast_c_cpp.scan_file(src, "x.c", {"AF_CAN"}) if h.kind in ("include", "call")}
    lines = src.read_text(encoding="utf-8").splitlines()
    rx = {(h.kind, h.name) for h in ast_c_cpp._scan_regex(lines, "x.c", {"AF_CAN"}) if h.kind in ("include", "call")}
    key = {("call", n) for n in ("epoll_wait", "eventfd", "signalfd", "fork", "socket")} | {("include", "linux/can.h")}
    assert key <= ts and key <= rx


def test_vendored_dirs_are_skipped(tmp_path: Path):
    (tmp_path / "third_party").mkdir()
    (tmp_path / "third_party" / "x.c").write_text("int main(void){ return epoll_create1(0); }\n", encoding="utf-8")
    (tmp_path / "main.c").write_text("int main(void){ return 0; }\n", encoding="utf-8")
    sr = scan_repo(tmp_path, interesting_tokens(), config_globs())
    assert not sr.has_call("epoll_create1")
    assert "third_party" in sr.files.vendored


def test_sparse_checkout_covers_scanner_inputs_and_tree_languages():
    from advisor.ingest.git_ingest import _languages_from_names, sparse_patterns
    pats = sparse_patterns()
    for needed in ("*.c", "*.h", "*.cpp", "CMakeLists.txt", "Makefile", "*.service", "configure.ac"):
        assert needed in pats
    assert _languages_from_names(["a/b.ts", "x.java", "src/m.c", "inc/k.hpp", "README.md"]) == \
        {"TypeScript", "Java", "C", "C++"}
