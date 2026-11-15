"""The built-in QEMU target helpers and Windows QNX mode (no QNX software needed)."""
from advisor import qnxvm, settings, wsl_launch


def test_saved_target_reads_vm_ip(tmp_path, monkeypatch):
    monkeypatch.setenv("QNX_ADVISOR_VM_DIR", str(tmp_path))
    monkeypatch.setattr(qnxvm, "REPO", tmp_path / "nowhere")
    assert qnxvm.saved_target() is None
    (tmp_path / "ip").write_text("172.31.1.232\n")
    assert qnxvm.saved_target() == "qnxuser@172.31.1.232"
    (tmp_path / "ip").write_text("1.2.3.4; rm -rf /\n")      # never trusted as a host name
    assert qnxvm.saved_target() is None


def test_target_check_offers_start_button(tmp_path, monkeypatch):
    monkeypatch.setenv("QNX_ADVISOR_VM_DIR", str(tmp_path))
    monkeypatch.setattr(qnxvm, "REPO", tmp_path / "nowhere")
    monkeypatch.setattr(qnxvm, "can_start", lambda: (True, ""))
    c = settings.target_check()
    assert c["id"] == "target" and c["action"] == "start_vm" and c["status"] == "optional"
    monkeypatch.setattr(qnxvm, "can_start", lambda: (False, "mkqnximage not found in the SDP"))
    c = settings.target_check()
    assert not c["action"] and "Mkqnximage not found" in c["fix"]


def test_start_vm_refuses_without_sdp(monkeypatch):
    monkeypatch.setattr(qnxvm, "can_start", lambda: (False, "QNX SDP environment not loaded"))
    assert qnxvm.start_vm() == {"state": "error", "log": "QNX SDP environment not loaded"}


def test_sdp_user_from_wsl_path(monkeypatch):
    monkeypatch.setattr(wsl_launch, "find_wsl_sdp", lambda: {"sdp": "/home/dev_1/qnx800", "index": None})
    assert wsl_launch.sdp_user() == "dev_1"
    monkeypatch.setattr(wsl_launch, "find_wsl_sdp", lambda: {"sdp": "/root/qnx800", "index": None})
    assert wsl_launch.sdp_user() == "root"
    monkeypatch.setattr(wsl_launch, "find_wsl_sdp", lambda: None)
    assert wsl_launch.sdp_user() is None


def test_windows_path_pasted_in_qnx_mode(monkeypatch, tmp_path):
    from advisor.ingest import git_ingest
    monkeypatch.setattr(git_ingest.os, "name", "posix")
    monkeypatch.setattr(git_ingest, "Path", lambda p: tmp_path if p == "/mnt/c" else __import__("pathlib").Path(p))
    assert git_ingest.windows_path_in_wsl(r"C:\Users\me\src\app") == "/mnt/c/Users/me/src/app"
    assert git_ingest.windows_path_in_wsl("https://github.com/a/b") == "https://github.com/a/b"
    assert git_ingest.windows_path_in_wsl("samples/x") == "samples/x"
