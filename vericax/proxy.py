"""Host-side proxy for the ``vericax-sh`` contract (spec/09 section 6, D2a/D2b).

One proxy per episode. It listens on a per-episode Unix socket, authenticates
with a per-episode token, and maps the five verbs (run/put/get/done/whoami)
onto the sandbox VM's control plane. It never exposes host shell, host
filesystem, or the scoring surface, and it appends every command to
``commands.jsonl`` with token-free fields.

cwd persistence (T2): the runtime starts a fresh bash per call, so ``cd``
would not survive between agent commands. The proxy captures the final ``pwd``
of every run (via a per-episode sentinel appended after the command) and
restarts the next run in that directory, reproducing interactive-shell
semantics without a persistent shell process. Environment variables are NOT
persisted; agents must inline ``export`` with the command that needs them.
"""
from __future__ import annotations

import base64
import json
import secrets
import socket
import tempfile
import threading
import time
from pathlib import Path

MAX_REQUEST_BYTES = 160 * 1024 * 1024   # put/get payloads (base64) budget
MAX_OUTPUT_BYTES = 1 * 1024 * 1024      # spec/09 6.2: truncate >1 MiB responses
PUT_FILE_LIMIT = 64 * 1024 * 1024
GET_FILE_LIMIT = 64 * 1024 * 1024
ALLOWED_ROOTS = ("/home/user", "/tmp")

_VERBS = ("run", "put", "get", "done", "whoami")


def temp_socket_path() -> Path:
    """Create a short, private directory for one proxy socket.

    AF_UNIX paths are limited to 108 bytes. Keeping the socket under /tmp
    decouples it from the episode directory name, which grows with the adapter
    name (e.g. ``opencode-bailian``) and can push the path over the limit. The
    caller removes ``path.parent`` when the proxy stops.
    """
    return Path(tempfile.mkdtemp(prefix="vx-proxy-")) / "p.sock"


def _safe_remote(path: str) -> str | None:
    """Normalize a VM-side path; None when it escapes the allowed roots."""
    import posixpath
    if not path or not path.startswith("/"):
        return None
    norm = posixpath.normpath(path)
    if not any(norm == root or norm.startswith(root + "/") for root in ALLOWED_ROOTS):
        return None
    return norm


class ProxyServer:
    def __init__(
        self,
        vm,                      # SandboxVM (control plane only)
        socket_path: Path,
        token: str,
        episode_id: str,
        workdir: str,
        log_dir: Path,
        default_timeout: int = 120,
    ):
        self._vm = vm
        self._socket_path = Path(socket_path)
        self._token = token
        self._episode_id = episode_id
        self._cwd = workdir
        self._workdir = workdir
        self._log_dir = Path(log_dir)
        self._default_timeout = default_timeout
        self._marker = "__VCAX_PWD_" + secrets.token_hex(8)
        self._done_requested = threading.Event()
        self._sock = None
        self._thread = None
        self._accepting = False
        self._log_lock = threading.Lock()
        self._cmd_log = self._log_dir / "commands.jsonl"
        self._full_output_dir = self._log_dir / "command-outputs"

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self._socket_path))
        self._socket_path.chmod(0o666)
        self._sock.listen(8)
        self._accepting = True
        self._thread = threading.Thread(target=self._serve, name="vericax-proxy", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Close the entry point; in-flight requests finish, new ones fail."""
        self._accepting = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._socket_path.exists():
            self._socket_path.unlink()

    @property
    def done_requested(self) -> bool:
        return self._done_requested.is_set()

    # ------------------------------------------------------------ server loop
    def _serve(self) -> None:
        while self._accepting:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(1200)
            with conn.makefile("rwb") as fh:
                line = fh.readline(MAX_REQUEST_BYTES)
                if not line:
                    return
                try:
                    request = json.loads(line)
                except ValueError:
                    self._reply(fh, {"ok": False, "error": "bad_request"})
                    return
                if not isinstance(request, dict) or request.get("token") != self._token:
                    got = request.get("token") if isinstance(request, dict) else f"<{type(request).__name__}>"
                    raw = line[:200].decode(errors="replace").replace(self._token, "<token>")
                    self._log("auth", {
                        "denied": True,
                        "got_len": len(got) if isinstance(got, str) else -1,
                        "got_prefix": got[:6] if isinstance(got, str) else "",
                        "want_len": len(self._token),
                        "raw": raw,
                    })
                    self._reply(fh, {"ok": False, "error": "auth_failed"})
                    return
                verb = request.get("v")
                if verb not in _VERBS:
                    self._reply(fh, {"ok": False, "error": f"unknown_verb:{verb}"})
                    return
                self._reply(fh, self._dispatch(verb, request))
        except Exception as exc:  # noqa: BLE001 - one poisoned request must not kill the server
            try:
                self._reply(fh, {"ok": False, "error": f"proxy_error:{exc}"})
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _reply(fh, response: dict) -> None:
        fh.write(json.dumps(response).encode() + b"\n")
        fh.flush()

    # ------------------------------------------------------------ verbs
    def _dispatch(self, verb: str, request: dict) -> dict:
        handler = {
            "run": self._verb_run,
            "put": self._verb_put,
            "get": self._verb_get,
            "done": self._verb_done,
            "whoami": self._verb_whoami,
        }[verb]
        started = time.monotonic()
        try:
            response = handler(request)
        except Exception as exc:  # noqa: BLE001
            response = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
        response["duration_ms"] = int((time.monotonic() - started) * 1000)
        return response

    def _verb_run(self, request: dict) -> dict:
        cmd = str(request.get("cmd", "")).strip()
        if not cmd:
            return {"ok": False, "error": "empty_command"}
        cwd = request.get("cwd") or self._cwd
        if not str(cwd).startswith("/"):
            return {"ok": False, "error": "bad_cwd"}
        timeout = int(request.get("timeout") or self._default_timeout)

        err_file = f"/tmp/.vcax_err_{secrets.token_hex(6)}"
        # Same-shell { ...; } block so a bare `cd` inside the command updates
        # the persisted cwd; stderr goes to a file so streams stay separated.
        script = (
            "{\n"
            f"{cmd}\n"
            f"}} 2>\"{err_file}\"\n"
            "__vcax_rc=$?\n"
            f"printf '%s' '{self._marker}'\"$PWD\"\n"
            "exit $__vcax_rc"
        )
        logged_cwd = cwd
        try:
            result = self._vm.bash(script, timeout=timeout + 10, cwd=str(cwd))
        except Exception as exc:  # noqa: BLE001
            self._log("run", {"cwd": logged_cwd, "argv": cmd, "exit": 125,
                              "error": type(exc).__name__})
            if type(exc).__name__ == "SandboxCommandTimeout":
                return {"ok": False, "error": "timeout", "timeout_seconds": timeout}
            return {"ok": False, "error": "sandbox_unavailable"}

        output = result["output"]
        stdout, new_cwd = output, None
        marker_at = output.rfind(self._marker)
        if marker_at >= 0:
            stdout = output[:marker_at]
            new_cwd = output[marker_at + len(self._marker):].strip() or None

        stderr = b""
        try:
            stderr = self._vm.get(err_file) or b""
            self._vm.bash(f"rm -f '{err_file}'", timeout=30)
        except Exception:  # noqa: BLE001 - stderr fetch is best-effort
            pass

        exit_code = result["returncode"]
        stdout_bytes, stderr_bytes = len(stdout.encode()), len(stderr)
        if len(stdout.encode()) > MAX_OUTPUT_BYTES:
            self._full_output_dir.mkdir(parents=True, exist_ok=True)
            spill = self._full_output_dir / f"{int(time.time() * 1000)}.out"
            spill.write_bytes(stdout.encode())
            stdout = stdout.encode()[:MAX_OUTPUT_BYTES].decode(errors="ignore") + \
                "\n[vericax-sh] output truncated; full log on the host: " + spill.name
        if new_cwd and new_cwd.startswith("/"):
            self._cwd = new_cwd
        self._log("run", {"cwd": logged_cwd, "argv": cmd, "exit": exit_code,
                          "stdout_bytes": stdout_bytes, "stderr_bytes": stderr_bytes})
        return {
            "ok": True, "returncode": exit_code,
            "stdout": stdout, "stderr": stderr.decode(errors="ignore"),
            "cwd": self._cwd,
        }

    def _verb_put(self, request: dict) -> dict:
        remote = _safe_remote(str(request.get("remote", "")))
        if remote is None:
            return {"ok": False, "error": "path_denied"}
        data = base64.b64decode(request.get("data_b64", ""))
        if len(data) > PUT_FILE_LIMIT:
            return {"ok": False, "error": "file_too_large"}
        # vm.upload chunks through the bash channel itself (MAX_ARG_STRLEN);
        # the socket message carries the whole payload in one request.
        self._vm.upload(remote, data)
        self._log("put", {"remote": remote, "bytes": len(data)})
        return {"ok": True, "bytes": len(data), "remote": remote}

    def _verb_get(self, request: dict) -> dict:
        remote = _safe_remote(str(request.get("remote", "")))
        if remote is None:
            return {"ok": False, "error": "path_denied"}
        data = self._vm.get(remote)
        if data is None:
            return {"ok": False, "error": "not_found", "remote": remote}
        if len(data) > GET_FILE_LIMIT:
            return {"ok": False, "error": "file_too_large"}
        self._log("get", {"remote": remote, "bytes": len(data)})
        return {"ok": True, "data_b64": base64.b64encode(data).decode(), "bytes": len(data)}

    def _verb_done(self, _request: dict) -> dict:
        self._done_requested.set()
        self._log("done", {})
        return {"ok": True}

    def _verb_whoami(self, _request: dict) -> dict:
        return {"ok": True, "episode_id": self._episode_id, "cwd": self._cwd,
                "workdir": self._workdir, "deadline_hint": None}

    # ------------------------------------------------------------ logging
    def _log(self, verb: str, fields: dict) -> None:
        record = {"ts": time.time(), "episode": self._episode_id, "verb": verb, **fields}
        with self._log_lock:
            self._cmd_log.parent.mkdir(parents=True, exist_ok=True)
            with self._cmd_log.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
