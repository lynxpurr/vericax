"""Adapter loading and launch planning (spec/08 section 5).

The adapter is the ONLY place allowed to differ per stack. Lifecycle code
(lifecycle/freeze/scoring/summary/cli) must never branch on a stack name
(rule A1); a new stack is a new TOML file plus a conformance case, nothing
else. The schema here extends the spec sketch with ``[model]`` (attribution,
spec/08 section 1.1) and ``[container]`` (image plus runtime-injected
credential forwarding) - both are adapter-owned configuration mapping.
"""
from __future__ import annotations

import shlex
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

INSTRUCTION_MODES = ("argv", "file", "stdin")
FILE_TOOL_POLICIES = ("disable", "proxy", "allow_local")
# what one usage event describes: one model call, or the whole session (openclaw --json)
COST_GRANULARITIES = ("call", "session")

CONTAINER_INSTRUCTION_PATH = "/vericax/instruction.md"
CONTAINER_PAYLOAD_DIR = "/vericax/payload"
CONTAINER_SANDBOX_TARGET = "/usr/local/bin/vericax-sh"

_ARGV_LIMIT = 100_000  # stay well under the kernel's per-argument cap


@dataclass
class Adapter:
    name: str
    version: str
    command: list[str] = field(default_factory=list)
    instruction: str = "argv"
    approval: list[str] = field(default_factory=list)
    grace_seconds: int = 10
    shell: str = "path"
    shell_target: str = "vericax-sh"
    file_tools: str = "disable"
    working_dir: str = "/home/user/Desktop"
    output_format: str = "text"
    cost_path: str | None = None
    cost_event_types: list[str] = field(default_factory=list)
    cost_granularity: str = "call"
    state_dir: str | None = None
    state_seed: list[str] = field(default_factory=list)
    state_template_dir: str | None = None
    source_dir: Path | None = None
    model_name: str | None = None
    model_endpoint: str | None = None
    container_image: str = "vericax-agent:phase1"
    container_env: dict[str, str] = field(default_factory=dict)
    container_env_from: list[str] = field(default_factory=list)

    @property
    def needs_stdin(self) -> bool:
        return self.instruction == "stdin"


def load_adapter(path: Path) -> Adapter:
    """Parse and validate one ``adapters/<stack>.toml``."""
    if not path.is_file():
        raise SystemExit(f"adapter not found: {path}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    def section(name: str) -> dict:
        value = raw.get(name, {})
        return value if isinstance(value, dict) else {}

    launch, sandbox = section("launch"), section("sandbox")
    output, state = section("output"), section("state")
    model, container = section("model"), section("container")

    name = raw.get("name")
    if not name:
        raise SystemExit(f"{path}: adapter must declare name")
    command = launch.get("command")
    if not isinstance(command, list) or not command:
        raise SystemExit(f"{path}: launch.command must be a non-empty argv list")
    instruction = launch.get("instruction", "argv")
    if instruction not in INSTRUCTION_MODES:
        raise SystemExit(f"{path}: launch.instruction must be one of {INSTRUCTION_MODES}")
    if instruction != "argv" and "{instruction}" in command:
        raise SystemExit(f"{path}: instruction={instruction} forbids an {{instruction}} placeholder")
    if instruction == "argv" and "{instruction}" not in command:
        raise SystemExit(f"{path}: instruction=argv needs an {{instruction}} placeholder")
    file_tools = sandbox.get("file_tools", "disable")
    if file_tools not in FILE_TOOL_POLICIES:
        raise SystemExit(f"{path}: sandbox.file_tools must be one of {FILE_TOOL_POLICIES}")
    if file_tools == "allow_local":
        raise SystemExit(f"{path}: file_tools=allow_local is debug-only; published configs must disable")
    container_env = container.get("env", {})
    if not isinstance(container_env, dict):
        raise SystemExit(f"{path}: container.env must be a table")
    cost_event_types = output.get("cost_event_types", [])
    if not isinstance(cost_event_types, list) or not all(
            isinstance(item, str) for item in cost_event_types):
        raise SystemExit(f"{path}: output.cost_event_types must be a list of event types")
    cost_granularity = output.get("cost_granularity", "call")
    if cost_granularity not in COST_GRANULARITIES:
        raise SystemExit(f"{path}: output.cost_granularity must be one of {COST_GRANULARITIES}")

    return Adapter(
        name=name,
        version=str(raw.get("version", "unknown")),
        command=[str(part) for part in command],
        instruction=instruction,
        approval=[str(flag) for flag in launch.get("approval", [])],
        grace_seconds=int(launch.get("grace_seconds", 10)),
        shell=str(sandbox.get("shell", "path")),
        shell_target=str(sandbox.get("shell_target", "vericax-sh")),
        file_tools=file_tools,
        working_dir=str(sandbox.get("working_dir", "/home/user/Desktop")),
        output_format=str(output.get("format", "text")),
        cost_path=output.get("cost_path"),
        cost_event_types=list(cost_event_types),
        cost_granularity=cost_granularity,
        state_dir=state.get("dir") or None,
        state_seed=[str(item) for item in state.get("seed", [])],
        state_template_dir=state.get("template_dir") or None,
        source_dir=path.parent,
        model_name=model.get("name"),
        model_endpoint=model.get("endpoint"),
        container_image=str(container.get("image", "vericax-agent:phase1")),
        container_env={str(k): str(v) for k, v in container_env.items()},
        container_env_from=[str(item) for item in container.get("env_from", [])],
    )


def resolve_adapter(spec: str) -> Path:
    """--adapter accepts an explicit path or a bare name under adapters/."""
    path = Path(spec)
    if path.suffix == ".toml" or path.parent != Path("."):
        return path
    candidate = Path(__file__).resolve().parents[1] / "adapters" / f"{spec}.toml"
    return candidate if candidate.is_file() else path


def build_command(
    adapter: Adapter, instruction_text: str, extra_argv: list[str] | None = None
) -> tuple[list[str], bool]:
    """Materialize the container argv for the agent process.

    Returns (argv, needs_stdin). Rule A2: this function is generic; every
    per-stack difference must come from the TOML file.

    ``instruction = "stdin"`` is delivered as a shell redirect from the
    read-only instruction mount (``sh -c '<argv> < /vericax/instruction.md'``).
    Docker's attach-stdin path proved unreliable (no EOF delivery, garbled
    streams); the redirect is deterministic and needs no extra plumbing.
    """
    argv: list[str] = []
    for part in adapter.command:
        if part == "{instruction}":
            if adapter.instruction == "argv":
                if len(instruction_text.encode()) > _ARGV_LIMIT:
                    raise SystemExit(
                        "instruction too large for instruction=argv; switch the "
                        "adapter to instruction=file or stdin")
                argv.append(instruction_text)
            elif adapter.instruction == "file":
                argv.append(CONTAINER_INSTRUCTION_PATH)
            # stdin: the placeholder is simply dropped; see the redirect below
        else:
            argv.append(part)
    argv.extend(adapter.approval)
    if extra_argv:
        argv.extend(extra_argv)
    if adapter.instruction == "stdin":
        return ["sh", "-c", f"{shlex.join(argv)} < {CONTAINER_INSTRUCTION_PATH}"], False
    return argv, False


def prepare_state_seed(adapter: Adapter, episode_dir: Path) -> dict[str, str]:
    """Create the per-run state dir on the host and copy declared seed files.

    Returns the mount map {host_path: {bind, mode}}. Seeds keep their basename
    inside the state dir; the dir itself is mounted read-write so the stack can
    write sessions, while the host copy stays under the episode's run dir
    (invariant E2, spec/09 section 4).
    """
    mounts: dict[str, dict[str, str]] = {}
    if not adapter.state_dir:
        return mounts
    if adapter.state_dir.startswith("/"):
        raise SystemExit(f"{adapter.name}: state.dir must be relative to the container HOME")
    host_state = episode_dir / "agent-state"
    host_state.mkdir(parents=True, exist_ok=True)
    if adapter.state_template_dir:
        # a stack-owned tree (e.g. a dsh profile) copied whole into the state
        # dir; relative paths resolve next to the adapter TOML
        template = Path(adapter.state_template_dir).expanduser()
        if not template.is_absolute() and adapter.source_dir:
            template = adapter.source_dir / template
        if not template.is_dir():
            raise SystemExit(f"{adapter.name}: state template missing: {template}")
        shutil.copytree(template, host_state, dirs_exist_ok=True)
    for seed in adapter.state_seed:
        source = Path(seed).expanduser()
        if not source.is_file():
            raise SystemExit(f"{adapter.name}: state seed missing: {source}")
        shutil.copy2(source, host_state / source.name)
    container_target = f"/root/{adapter.state_dir}"
    mounts[str(host_state)] = {"bind": container_target, "mode": "rw"}
    return mounts


def container_env(adapter: Adapter, base_env: dict[str, str], host_env=None) -> dict[str, str]:
    """Merge the contract env with adapter-owned values and credential forwarding."""
    import os
    host_env = os.environ if host_env is None else host_env
    env = dict(base_env)
    env.update(adapter.container_env)
    for name in adapter.container_env_from:
        value = host_env.get(name)
        if value:
            env[name] = value
    if adapter.shell_target == "vericax-sh" and adapter.shell == "path":
        # the harness guarantees the client binary sits at this path in the image
        env["VERICAX_SANDBOX"] = CONTAINER_SANDBOX_TARGET
    return env


def quote_for_logging(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)
