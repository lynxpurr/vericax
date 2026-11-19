#!/usr/bin/env python3
"""``vericax-sh`` - the agent-facing sandbox CLI (spec/08 section 4, spec/09 section 6).

This file is deliberately standard-library only: it is copied verbatim into the
agent container image as ``/usr/local/bin/vericax-sh`` and must run on any
python3 without dependencies.

Environment:
    VERICAX_PROXY_SOCKET   unix socket of the episode proxy (default
                           /run/vericax/proxy.sock)
    VERICAX_SANDBOX_TOKEN  per-episode credential, required

Exit codes:
    remote returncode     for `run` when the VM command executed
    124                   VM command timed out
    125                   proxy/transport failure
    78                    local setup error (missing token/socket, path denial)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
from pathlib import Path

SOCKET = os.environ.get("VERICAX_PROXY_SOCKET", "/run/vericax/proxy.sock")
TOKEN = os.environ.get("VERICAX_SANDBOX_TOKEN", "")
PUT_CHUNK_BYTES = 24 * 1024 * 1024   # decoded bytes per request


class TransportError(Exception):
    pass


def _request(payload: dict) -> dict:
    if not TOKEN:
        raise TransportError("VERICAX_SANDBOX_TOKEN is not set")
    payload = {"token": TOKEN, **payload}
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1300)
        sock.connect(SOCKET)
    except OSError as exc:
        raise TransportError(f"proxy unreachable at {SOCKET}: {exc}") from exc
    try:
        with sock.makefile("rwb") as fh:
            fh.write(json.dumps(payload).encode() + b"\n")
            fh.flush()
            line = fh.readline()
            if not line:
                raise TransportError("proxy closed the connection without a reply")
            response = json.loads(line)
    except json.JSONDecodeError as exc:
        raise TransportError(f"proxy reply is not JSON: {exc}") from exc
    finally:
        sock.close()
    return response


def _fail(message: str, code: int = 125) -> "int":
    print(f"vericax-sh: {message}", file=sys.stderr)
    return code


def cmd_run(args) -> int:
    cmd = " ".join(args.cmd)
    response = _request({"v": "run", "cmd": cmd, "cwd": args.cwd, "timeout": args.timeout})
    if not response.get("ok"):
        if response.get("error") == "timeout":
            return _fail(f"command timed out after {response.get('timeout_seconds')}s", 124)
        return _fail(f"run failed: {response.get('error')}")
    sys.stdout.write(response.get("stdout", ""))
    sys.stderr.write(response.get("stderr", ""))
    sys.stdout.flush()
    sys.stderr.flush()
    return int(response.get("returncode", 125))


def cmd_put(args) -> int:
    local = Path(args.local)
    if not local.is_file():
        return _fail(f"no such file: {local}", 78)
    data = local.read_bytes()
    if len(data) > PUT_CHUNK_BYTES:
        return _fail(f"file exceeds the {PUT_CHUNK_BYTES // (1024 * 1024)} MiB put limit", 78)
    response = _request({
        "v": "put", "remote": args.remote,
        "data_b64": base64.b64encode(data).decode(),
    })
    if not response.get("ok"):
        return _fail(f"put failed: {response.get('error')} ({args.remote})")
    return 0


def cmd_get(args) -> int:
    response = _request({"v": "get", "remote": args.remote})
    if not response.get("ok"):
        if response.get("error") == "not_found":
            return _fail(f"not found in sandbox: {args.remote}", 78)
        return _fail(f"get failed: {response.get('error')} ({args.remote})")
    data = base64.b64decode(response.get("data_b64", ""))
    local = Path(args.local)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    return 0


def cmd_done(_args) -> int:
    response = _request({"v": "done"})
    if not response.get("ok"):
        return _fail(f"done failed: {response.get('error')}")
    return 0


def cmd_whoami(_args) -> int:
    response = _request({"v": "whoami"})
    if not response.get("ok"):
        return _fail(f"whoami failed: {response.get('error')}")
    print(json.dumps({k: v for k, v in response.items() if k != "ok"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="vericax-sh", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", required=True)

    p_run = sub.add_parser("run", help="run a command inside the sandbox VM")
    p_run.add_argument("--cwd", default=None, help="working directory for this command")
    p_run.add_argument("--timeout", type=int, default=None, help="per-command timeout (s)")
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="command line (use -- before it)")
    p_run.set_defaults(func=cmd_run)

    p_put = sub.add_parser("put", help="copy a local file into the sandbox VM")
    p_put.add_argument("local")
    p_put.add_argument("remote")
    p_put.set_defaults(func=cmd_put)

    p_get = sub.add_parser("get", help="copy a file out of the sandbox VM")
    p_get.add_argument("remote")
    p_get.add_argument("local")
    p_get.set_defaults(func=cmd_get)

    p_done = sub.add_parser("done", help="optional early completion signal")
    p_done.set_defaults(func=cmd_done)

    p_who = sub.add_parser("whoami", help="print episode/sandbox metadata")
    p_who.set_defaults(func=cmd_whoami)

    args = parser.parse_args()
    if args.verb == "run" and args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]
    if args.verb == "run" and not args.cmd:
        parser.error("run needs a command; use: vericax-sh run -- <command...>")
    try:
        return args.func(args)
    except TransportError as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
