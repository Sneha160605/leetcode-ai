"""Process-level sandbox for untrusted submissions.

Defence in depth (outermost first):
  1. Fargate task = its own Firecracker microVM, one task per worker, no shared kernel with other customers.
  2. Task runs in an isolated subnet (no IGW/NAT route) with a read-only root FS and all capabilities
     dropped except SETUID/SETGID/CHOWN, which are used here to run user code as an unprivileged uid.
  3. This module: unprivileged uid, new session, scrubbed env, rlimits (CPU, memory, procs, files,
     file size), wall-clock timeout with process-group kill, output capped via RLIMIT_FSIZE.
  4. Language harness: Python audit hook (no subprocess/sockets/outside writes), Node vm context
     without require/process.
"""
from __future__ import annotations

import json
import os
try:
    import resource  # POSIX-only: enforced in the Linux worker container
except ImportError:  # Windows local development can import the module, but must not execute submissions
    resource = None
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HARNESS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness")
SANDBOX_ROOT = os.environ.get("SANDBOX_ROOT") or tempfile.gettempdir()
SANDBOX_UID = int(os.environ.get("SANDBOX_UID", "65534"))
MAX_CODE_BYTES = 64 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024

LANG_FILES = {"python": "solution.py", "javascript": "solution.js"}


def _limits(cpu_s: int, mem_mb: int, language: str, drop: bool):
    if resource is None or os.name != "posix":
        raise RuntimeError("Secure code execution requires the Linux/POSIX worker container. Do not run untrusted submissions on the host OS.")
    def apply():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        if language == "python":  # V8 reserves huge virtual ranges, so AS limits only suit CPython
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if drop:
            resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
            os.setgroups([])
            os.setgid(SANDBOX_UID)
            os.setuid(SANDBOX_UID)

    return apply


def run_case(language: str, code: str, fn_name: str, args: list, time_limit_ms: int = 2000, mem_mb: int = 256) -> dict:
    """Run one test case in the Linux sandbox. Never execute untrusted code on Windows host."""
    if resource is None or os.name != "posix":
        return {"status": "error", "error": "Secure execution is available only in the isolated Linux worker container.", "ms": 0, "stdout": ""}
    if language not in LANG_FILES:
        raise ValueError(f"unsupported language {language}")
    if len(code.encode()) > MAX_CODE_BYTES:
        return {"status": "error", "error": "Source too large", "ms": 0, "stdout": ""}

    drop = os.geteuid() == 0
    wd = tempfile.mkdtemp(prefix="run-", dir=SANDBOX_ROOT)
    try:
        os.chmod(wd, 0o777 if drop else 0o700)
        with open(os.path.join(wd, LANG_FILES[language]), "w") as fh:
            fh.write(code)
        with open(os.path.join(wd, "case.json"), "w") as fh:
            json.dump(args, fh)
        harness = "harness.py" if language == "python" else "harness.js"
        shutil.copy(os.path.join(HARNESS_DIR, harness), os.path.join(wd, harness))
        for name in os.listdir(wd):
            os.chmod(os.path.join(wd, name), 0o644)

        cpu_s = max(1, -(-time_limit_ms // 1000))
        if language == "python":
            cmd = [sys.executable, "-I", "-B", os.path.join(wd, harness), wd, fn_name]
        else:
            cmd = [shutil.which("node") or "node", f"--max-old-space-size={mem_mb}", os.path.join(wd, harness),
                   wd, fn_name, str(time_limit_ms)]
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": wd, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}

        out_path = os.path.join(wd, "stdout.txt")
        err_path = os.path.join(wd, "stderr.txt")
        with open(out_path, "wb") as so, open(err_path, "wb") as se:
            os.chmod(out_path, 0o666)
            os.chmod(err_path, 0o666)
            t0 = time.monotonic()
            proc = subprocess.Popen(
                cmd, cwd=wd, env=env, stdin=subprocess.DEVNULL, stdout=so, stderr=se, close_fds=True,
                preexec_fn=_limits(cpu_s, mem_mb + 192, language, drop),
            )
            timed_out = False
            try:
                proc.wait(timeout=time_limit_ms / 1000 + 1.0)  # +1s grace for interpreter start-up
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()
            wall_ms = (time.monotonic() - t0) * 1000

        stdout = _tail(out_path, 2000)
        stderr = _tail(err_path, 800)
        res = _read_result(os.path.join(wd, "result.json"))

        if timed_out or (res is None and proc.returncode in (-signal.SIGKILL, -signal.SIGXCPU)):
            return {"status": "timeout", "error": "Time limit exceeded", "ms": round(wall_ms), "stdout": stdout}
        if res is None:
            text = stderr or f"process exited with code {proc.returncode}"
            if proc.returncode in (-signal.SIGSEGV, -signal.SIGABRT) or "out of memory" in text.lower() or "MemoryError" in text:
                return {"status": "mle", "error": "Memory limit exceeded", "ms": round(wall_ms), "stdout": stdout}
            return {"status": "error", "error": text[-500:], "ms": round(wall_ms), "stdout": stdout}
        if res.get("ok"):
            return {"status": "ok", "output": res.get("output"), "ms": res.get("ms", round(wall_ms)),
                    "stdout": (stdout + res.get("stdout", ""))[:2000]}
        err = str(res.get("error", "error"))
        if err.startswith("TimeLimit"):
            return {"status": "timeout", "error": "Time limit exceeded", "ms": round(wall_ms), "stdout": stdout}
        if "MemoryError" in err or "out of memory" in err.lower():
            return {"status": "mle", "error": "Memory limit exceeded", "ms": round(wall_ms), "stdout": stdout}
        return {"status": "error", "error": err, "ms": round(wall_ms), "stdout": stdout}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def _tail(path: str, n: int) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        return data[-n:].decode("utf-8", "replace")
    except OSError:
        return ""


def _read_result(path: str):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_RESULT_BYTES)
        return json.loads(data)
    except (ValueError, OSError):
        return None
