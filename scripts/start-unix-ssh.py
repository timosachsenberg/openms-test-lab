"""Bounded Upterm session with the same allowlisted public key as Windows."""
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shlex
import signal
import subprocess
import sys
import tarfile
import time
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("unix_lab", ROOT / "scripts/unix-lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
DIGESTS = {
    "darwin_amd64": "400225025b8b67b4ceca3022146b00185997bb6d66f73c04c7343572ef43aefa",
    "darwin_arm64": "e20db7e128c831a4e9b709a2f2a1fc141cb73302ca23a147937df01ab94dd041",
    "linux_amd64": "663799a0a8d8643e35cf4d4ce66919fb0ab60992f8896f1dae62fb784b724ded",
    "linux_arm64": "c9c5dd9553a2d45a962ee369e0d9c69c7bac86160651e82908304b0b05dbc724",
}
minutes = int(os.environ.get("LAB_SESSION_MINUTES", "60"))
if minutes not in {5, 15, 30, 60, 120}:
    raise ValueError("Invalid session duration")
key = ROOT / "ssh/authorized_keys"
if not key.exists() or not key.read_text().strip():
    raise ValueError("No public key configured; refusing to open an unrestricted session")
subprocess.run(["ssh-keygen", "-lf", str(key)], check=True)
target = ("darwin" if sys.platform == "darwin" else "linux") + ("_arm64" if platform.machine() in {"arm64", "aarch64"} else "_amd64")
directory = Path(os.environ["RUNNER_TEMP"]) / "openms-lab-upterm"
directory.mkdir(exist_ok=True)
archive = directory / "upterm.tar.gz"
lab.download(f"https://github.com/owenthereal/upterm/releases/download/v0.28.0/upterm_{target}.tar.gz", archive, DIGESTS[target])
with tarfile.open(archive) as bundle:
    members = [item for item in bundle.getmembers() if Path(item.name).name == "upterm" and item.isfile()]
    if len(members) != 1:
        raise RuntimeError("Expected one Upterm executable")
    with bundle.extractfile(members[0]) as source, (directory / "upterm").open("wb") as out:
        out.write(source.read())
binary = directory / "upterm"
binary.chmod(0o700)
subprocess.run([str(binary), "version"], check=True)
command = "/bin/bash --noprofile --rcfile " + shlex.quote(str(ROOT / "scripts/enter-unix-lab.sh")) + " -i"
args = [str(binary), "host", "--accept", "--hide-client-ip", "--skip-host-key-check",
        "--known-hosts", str(directory / "known_hosts"), "--server", "ssh://uptermd.upterm.dev:22",
        "--authorized-keys", str(key), "--force-command", command, "--",
        "/bin/sh", "-c", "while [ ! -f continue ]; do sleep 1; done"]
env = os.environ.copy()
env.pop("GH_TOKEN", None)
env.pop("GITHUB_TOKEN", None)
os.chdir(ROOT)
process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
selector = selectors.DefaultSelector()
selector.register(process.stdout, selectors.EVENT_READ)
startup = time.monotonic() + 90
deadline = None
transcript = ""
connection = None
try:
    while True:
        for selected, _ in selector.select(timeout=0.2):
            chunk = os.read(selected.fileobj.fileno(), 8192)
            if chunk:
                text = chunk.decode("utf-8", "replace")
                print(text, end="", flush=True)
                transcript += text
            else:
                selector.unregister(selected.fileobj)
        plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", transcript)
        match = re.search(r"ssh\s+([A-Za-z0-9_:+/=.-]+@uptermd\.upterm\.dev)", plain)
        if not connection and match:
            connection = "ssh -i windows-test-lab_ed25519 " + match.group(1)
            deadline = time.monotonic() + minutes * 60
            info = {"command": connection, "destination": match.group(1), "minutes": minutes,
                    "platform": sys.platform, "architecture": platform.machine()}
            (ROOT / "reports/ssh-session.json").write_text(json.dumps(info, indent=2) + "\n")
            print("\nSSH READY: " + connection, flush=True)
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as out:
                    out.write(f"\n## SSH session\n\n~~~text\n{connection}\n~~~\n\nUse the same private key as the Windows lab. Session: {minutes} minutes. Run \u0060finish-lab\u0060 to upload exports and finish.\n")
        if (ROOT / "continue").exists() or (deadline and time.monotonic() >= deadline):
            print("\nSession finished; uploading exports next.")
            break
        if not connection and time.monotonic() > startup:
            raise RuntimeError("Upterm was not ready within 90 seconds")
        if process.poll() is not None:
            raise RuntimeError(f"Upterm exited unexpectedly: {process.returncode}")
finally:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    selector.close()
