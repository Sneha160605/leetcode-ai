"""Python harness. Runs INSIDE the sandboxed child process.

argv: workdir fn_name. Reads workdir/solution.py and workdir/case.json, writes workdir/result.json.
It only ever reports the *actual* output; comparison with the expected value happens in the parent,
so the sandboxed code can never learn hidden expected outputs.
"""
import importlib.util
import json
import os
import sys
import time
import traceback

workdir = os.path.realpath(sys.argv[1])
fn_name = sys.argv[2]
RESULT = os.path.join(workdir, "result.json")

with open(os.path.join(workdir, "case.json"), "rb") as fh:
    args = json.loads(fh.read())

BLOCKED = {
    "subprocess.Popen", "os.system", "os.exec", "os.fork", "os.forkpty", "os.posix_spawn", "os.spawn",
    "os.kill", "os.killpg", "os.chmod", "os.chown", "os.setuid", "os.setgid", "os.symlink", "os.link",
    "socket.connect", "socket.bind", "socket.sendto", "socket.getaddrinfo", "socket.gethostbyname",
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.cdata", "mmap.__new__", "pty.spawn", "shutil.copyfile",
    "shutil.rmtree", "os.remove", "os.rmdir", "os.rename", "os.truncate",
}


def _hook(event, a):
    if event in BLOCKED:
        raise PermissionError("blocked by sandbox: " + event)
    if event == "open":
        path, mode, flags = a
        if isinstance(path, (bytes, bytearray)):
            path = path.decode("utf-8", "ignore")
        wants_write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND)
        )
        if wants_write and isinstance(path, str):
            real = os.path.realpath(path)
            if not (real == workdir or real.startswith(workdir + os.sep) or real in ("/dev/null",)):
                raise PermissionError("blocked by sandbox: write outside workdir")


def _write(obj):
    data = json.dumps(obj)
    fd = os.open(RESULT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as fh:
        fh.write(data)


def main():
    spec = importlib.util.spec_from_file_location("user_solution", os.path.join(workdir, "solution.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.addaudithook(_hook)  # cannot be removed once installed
    try:
        spec.loader.exec_module(mod)
        fn = getattr(mod, fn_name, None)
        if not callable(fn):
            return _write({"ok": False, "error": f"Function '{fn_name}' is not defined"})
        t0 = time.perf_counter()
        out = fn(*args)
        ms = (time.perf_counter() - t0) * 1000
        _write({"ok": True, "output": out, "ms": round(ms, 2)})
    except MemoryError:
        _write({"ok": False, "error": "MemoryError: memory limit exceeded"})
    except SyntaxError as e:
        _write({"ok": False, "error": f"SyntaxError: {e.msg} (line {e.lineno})"})
    except BaseException as e:  # noqa: BLE001 - report everything the user code can raise
        tb = traceback.format_exception_only(type(e), e)[-1].strip()
        _write({"ok": False, "error": tb[:500]})


main()
