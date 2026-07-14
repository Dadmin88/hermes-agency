"""LLM-powered processing for incoming Hermes Agency tasks.

This module bridges incoming A2A tasks into Hermes' delegation system.  The
transport worker remains responsible for task lifecycle (complete/fail, Kanban,
announcements); this module is only responsible for turning a task record into a
subagent response.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from .conversation import format_conversation_history
from .trust import store_for_config

logger = logging.getLogger(__name__)

SAFE_TOOLSETS = ["web", "search", "skills", "memory", "session_search"]
SKILL_CONTEXT_CACHE_TTL_SECONDS = 300
SUBPROCESS_PROGRESS_INTERVAL_SECONDS = 5.0
SUBPROCESS_PROGRESS_LINE_BATCH = 3
DELEGATION_FIRST_PROGRESS_SECONDS = 10.0
DELEGATION_PROGRESS_INTERVAL_SECONDS = 30.0
_SKILL_CONTEXT_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
ProgressCallback = Callable[[str], None]
TRUST_ORDER = {"blocked": 0, "limited": 1, "full": 2}


class TaskProcessingError(RuntimeError):
    """Raised when incoming task processing cannot produce a response."""


class SubprocessTaskError(TaskProcessingError):
    """Raised when subprocess fallback fails."""


def toolsets_for_access(tool_access: str | None) -> list[str] | None:
    """Map configured incoming tool access to Hermes delegation toolsets.

    ``None`` means inherit the parent agent's full tool surface, which is how
    Hermes delegation represents unrestricted access.  ``[]`` means no tools.
    """

    access = (tool_access or "safe").strip().lower()
    if access == "none":
        return []
    if access == "full":
        return None
    if access != "safe":
        logger.warning("Unknown agency incoming tool_access=%r; using safe", tool_access)
    toolsets = list(SAFE_TOOLSETS)
    try:
        from .config import get_config

        if get_config().skill_governance.hub_acquisition_enabled:
            toolsets.insert(3, "agency-skills")
    except Exception:
        pass
    return toolsets


def load_skill_context(skill_id: str, profile_home: str | Path) -> str | None:
    """Load skill-specific instructions for an incoming A2A target skill.

    The requested Hermes Agency skill id is matched against installed Hermes
    skills under ``<profile_home>/skills/**/SKILL.md`` using the same slug shape
    as ``card_builder.py``: exact match first, then prefix, then substring.
    Existing matches are cached briefly; misses are intentionally not cached so
    newly installed skills are picked up on the next task.
    """

    requested_raw = str(skill_id or "").strip()
    if not requested_raw:
        return None
    requested = _normalise_skill_id(requested_raw)
    profile_dir = Path(profile_home).expanduser().resolve()
    cache_key = (str(profile_dir), requested)
    now = time.time()
    cached = _SKILL_CONTEXT_CACHE.get(cache_key)
    if cached is not None:
        cached_at, cached_context = cached
        if now - cached_at < SKILL_CONTEXT_CACHE_TTL_SECONDS:
            logger.debug("Using cached Hermes Agency skill context for %s", requested)
            return cached_context
        _SKILL_CONTEXT_CACHE.pop(cache_key, None)

    match = _find_skill_file(requested, profile_dir)
    if match is None:
        logger.info(
            "Requested Hermes Agency skill %r was not found under %s", requested_raw, profile_dir
        )
        return None

    matched_id, skill_file = match
    text = _read_text(skill_file)
    frontmatter = _extract_frontmatter(text)
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        description = _fallback_frontmatter_value(text, "description")
    if not description:
        description = f"Hermes skill from {skill_file.parent.name}."

    logger.info(
        "Matched requested Hermes Agency skill %r to local Hermes skill %r at %s",
        requested_raw,
        matched_id,
        skill_file,
    )
    context = (
        f'The sender requested the "{requested_raw}" skill.\n'
        f"Matched local Hermes skill: {matched_id}\n"
        f"Skill description: {description}\n\n"
        "Use this skill's knowledge and approach when processing the task.\n"
        "If the skill provides specific instructions, follow them.\n\n"
        "Skill instructions (SKILL.md):\n"
        f"{text.strip()}"
    ).strip()
    _SKILL_CONTEXT_CACHE[cache_key] = (now, context)
    return context


def build_delegation_prompt(task_record: Any, skill_context: str | None = None) -> str:
    """Build the task prompt sent to the Hermes subagent."""

    sender_peer_id = _field(task_record, "sender_peer_id") or "unknown peer"
    sender_name = _sender_name(task_record) or "unknown sender"
    skill_id = _field(task_record, "target_skill_id") or "none"
    message_text = _field(task_record, "message_text") or ""
    context_packet = _field(task_record, "context_packet")
    history_block = ""
    if isinstance(context_packet, dict):
        history_block = format_conversation_history(context_packet.get("conversation_history"))
    request_block = (
        f"{history_block}\n\nCurrent request:\n{message_text}"
        if history_block
        else f"Message:\n{message_text}"
    )
    skill_block = f"\n\n{skill_context.strip()}" if skill_context else ""
    return (
        "You received a task from another agent via Hermes Agency P2P.\n\n"
        f"Sender: {sender_name} ({sender_peer_id})\n"
        f"Skill requested: {skill_id}\n"
        f"{request_block}"
        f"{skill_block}\n\n"
        "Process this task using your knowledge and tools. Return a clear, concise response."
    )


def build_delegation_context(task_record: Any) -> str:
    """Build additional context for the subagent."""

    sender_peer_id = _field(task_record, "sender_peer_id") or "unknown peer"
    sender_name = _sender_name(task_record) or "unknown sender"
    skill_id = _field(task_record, "target_skill_id") or "none"
    task_id = _field(task_record, "task_id") or "unknown task"
    context_packet = _field(task_record, "context_packet")
    context_packet_json = ""
    if context_packet:
        try:
            context_packet_json = json.dumps(
                context_packet, ensure_ascii=False, indent=2, default=str
            )
        except Exception:
            context_packet_json = str(context_packet)

    parts = [
        "You are processing a task from another agent. Your normal SOUL.md instructions apply.",
        "Additional context:",
        f"- Hermes Agency task id: {task_id}",
        f"- Sender: {sender_name} ({sender_peer_id})",
        f"- Skill requested: {skill_id}",
        "- This task was received via Hermes Agency P2P.",
        "- Respond as the receiving Hermes profile, not as the sender.",
        "- Keep the final response suitable to send back as an A2A task artifact.",
    ]
    if context_packet_json:
        parts.extend(["", "Structured context packet:", context_packet_json])
    return "\n".join(parts)


def _emit_progress(progress_callback: ProgressCallback | None, text: str) -> None:
    message = str(text or "").strip()
    if not progress_callback or not message:
        return
    try:
        progress_callback(message)
    except Exception:
        logger.debug("Hermes Agency progress callback failed", exc_info=True)


@contextmanager
def _delegation_progress_heartbeat(progress_callback: ProgressCallback | None):
    if progress_callback is None:
        yield
        return

    stop_event = threading.Event()

    def run() -> None:
        if stop_event.wait(DELEGATION_FIRST_PROGRESS_SECONDS):
            return
        _emit_progress(progress_callback, "Processing...")
        while not stop_event.wait(DELEGATION_PROGRESS_INTERVAL_SECONDS):
            _emit_progress(progress_callback, "Still working...")

    thread = threading.Thread(target=run, name="agency-progress-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)


def process_incoming_task(
    task_record: Any,
    config: Any,
    fallback_response: Callable[[Any], str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Process an incoming A2A task through Hermes delegation.

    Args:
        task_record: IncomingTaskRecord-like object with message/sender fields.
        config: AgencyConfig-like object with incoming delegation settings.
        fallback_response: Optional callable used to produce the legacy template
            response if delegation fails.  Kept optional so callers can decide
            whether failure should fallback or propagate.

    Returns:
        The subagent's response text, or fallback text when provided.

    Raises:
        TaskProcessingError when delegation fails and no fallback was provided.
    """

    skill_id = str(_field(task_record, "target_skill_id") or "").strip()
    skill_context = None
    if skill_id:
        skill_context = load_skill_context(skill_id, _active_profile_home())
        if skill_context is None and bool(
            getattr(config, "incoming_reject_unmatched_skills", False)
        ):
            raise TaskProcessingError(f"I don't have the {skill_id} skill")
    prompt = build_delegation_prompt(task_record, skill_context=skill_context)
    context = build_delegation_context(task_record)
    mode = str(getattr(config, "incoming_mode", "delegation") or "delegation").strip().lower()
    toolsets = toolsets_for_access(getattr(config, "incoming_tool_access", "safe"))
    max_iterations = getattr(config, "incoming_max_iterations", 25)
    timeout = int(getattr(config, "delegation_timeout", 120) or 120)
    send_progress = bool(getattr(config, "incoming_send_progress", False))
    active_progress_callback = progress_callback if send_progress else None

    if mode == "template":
        if fallback_response is not None:
            return fallback_response(task_record)
        raise TaskProcessingError("incoming.mode=template does not run LLM processing")

    if mode == "delegation":
        try:
            with _delegation_progress_heartbeat(active_progress_callback):
                response = _call_delegate_task(
                    goal=prompt,
                    context=context,
                    toolsets=toolsets,
                    max_iterations=max_iterations,
                )
            if not response.strip():
                raise TaskProcessingError("Hermes delegation returned an empty response")
            return response.strip()
        except Exception:  # noqa: BLE001 - fall back only when explicitly enabled
            logger.exception("Incoming Hermes Agency delegation failed")
            if not bool(getattr(config, "incoming_allow_subprocess_fallback", False)):
                logger.warning(
                    "Incoming Hermes Agency subprocess fallback disabled; returning safe fallback"
                )
                if fallback_response is not None:
                    return fallback_response(task_record)
                raise TaskProcessingError("Incoming Hermes Agency delegation failed")

    if mode in {"delegation", "subprocess"}:
        if mode == "subprocess" and not bool(getattr(config, "incoming_allow_subprocess", False)):
            logger.warning(
                "Incoming Hermes Agency subprocess mode denied: agency.incoming.allow_subprocess=false"
            )
            if fallback_response is not None:
                return fallback_response(task_record)
            raise TaskProcessingError("incoming subprocess mode is disabled")
        if mode == "delegation" and not bool(getattr(config, "incoming_allow_subprocess", False)):
            logger.warning(
                "Incoming Hermes Agency subprocess fallback denied: agency.incoming.allow_subprocess=false"
            )
            if fallback_response is not None:
                return fallback_response(task_record)
            raise TaskProcessingError("incoming subprocess fallback is disabled")
        if not _subprocess_trust_allowed(task_record, config):
            logger.warning(
                "Incoming Hermes Agency subprocess denied for sender %s: requires %s trust",
                _field(task_record, "sender_peer_id") or "unknown peer",
                getattr(config, "incoming_min_subprocess_trust", "full"),
            )
            if fallback_response is not None:
                return fallback_response(task_record)
            raise TaskProcessingError("sender trust level is insufficient for subprocess")
        profile_name = resolve_subprocess_profile(config)
        if profile_name:
            subprocess_message = f"{prompt}\n\n{context}"
            if active_progress_callback is not None:
                response = process_via_subprocess(
                    profile_name,
                    subprocess_message,
                    timeout,
                    progress_callback=active_progress_callback,
                    allow_hooks=bool(getattr(config, "incoming_allow_hooks_for_remote", False)),
                )
            else:
                if bool(getattr(config, "incoming_allow_hooks_for_remote", False)):
                    response = process_via_subprocess(
                        profile_name,
                        subprocess_message,
                        timeout,
                        allow_hooks=True,
                    )
                else:
                    response = process_via_subprocess(profile_name, subprocess_message, timeout)
            if response.strip() and not _is_error_response(response):
                return response.strip()
            logger.error("Incoming Hermes Agency subprocess fallback failed: %s", response)
        else:
            logger.error(
                "Incoming Hermes Agency subprocess fallback skipped: profile could not be resolved"
            )

    if fallback_response is not None:
        return fallback_response(task_record)
    raise TaskProcessingError("Incoming Hermes Agency task processing failed")


def _subprocess_trust_allowed(task_record: Any, config: Any) -> bool:
    sender_peer_id = str(_field(task_record, "sender_peer_id") or "").strip()
    if not sender_peer_id:
        return False
    min_trust = (
        str(getattr(config, "incoming_min_subprocess_trust", "full") or "full").strip().lower()
    )
    if min_trust not in {"limited", "full"}:
        min_trust = "full"
    try:
        record = store_for_config(config).list_peers().get(sender_peer_id) or {}
    except Exception:
        logger.warning("Could not read trust store for subprocess authorization", exc_info=True)
        return False
    trust_level = str(record.get("trust_level") or "").strip().lower()
    if trust_level == "blocked" or not trust_level:
        return False
    return TRUST_ORDER.get(trust_level, 0) >= TRUST_ORDER[min_trust]


def resolve_subprocess_profile(config: Any) -> str | None:
    """Resolve which Hermes profile should process subprocess fallback tasks."""

    override = str(getattr(config, "incoming_subprocess_profile", "") or "").strip()
    if override:
        return override
    env_profile = os.getenv("HERMES_PROFILE", "").strip()
    if env_profile:
        return env_profile
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home()).expanduser()
        if home.parent.name == "profiles" and home.name:
            return home.name
        if home.name == ".hermes":
            return "default"
        if home.name:
            return home.name
    except Exception:
        logger.debug("Could not resolve subprocess profile from Hermes home", exc_info=True)
    return None


def process_via_subprocess(
    profile_name: str,
    task_message: str,
    timeout: int | float,
    progress_callback: ProgressCallback | None = None,
    *,
    allow_hooks: bool = False,
) -> str:
    """Process a task via `hermes -p <profile> chat -q ... --quiet`.

    Returns the subprocess stdout on success.  On crash, timeout, empty output,
    encoding problems, or command-resolution failure, returns an ``ERROR: ...``
    string so callers can fall back to the legacy template response.
    """

    try:
        return asyncio.run(
            _process_via_subprocess_async(
                profile_name,
                task_message,
                timeout,
                progress_callback=progress_callback,
                allow_hooks=allow_hooks,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: subprocess task processing failed: {type(exc).__name__}: {exc}"


async def _process_via_subprocess_async(
    profile_name: str,
    task_message: str,
    timeout: int | float,
    progress_callback: ProgressCallback | None = None,
    *,
    allow_hooks: bool = False,
) -> str:
    profile = (profile_name or "").strip()
    if not profile:
        raise SubprocessTaskError("missing subprocess profile")
    message = task_message or ""
    if not message.strip():
        raise SubprocessTaskError("empty task message")
    hermes_cmd = _resolve_hermes_command()
    if not hermes_cmd:
        raise SubprocessTaskError("could not locate hermes executable")
    timeout_seconds = max(1.0, float(timeout or 120))
    env = os.environ.copy()
    env.pop("HERMES_YOLO_MODE", None)
    # Pool runners are long-lived processes that may be launched from an active
    # Hermes chat/session. Do not leak the runner's own session context into the
    # worker CLI subprocess: if HERMES_SESSION_ID points at a session from a
    # different profile DB, the child can try to create its new session as a
    # branch of a non-existent parent and spam FOREIGN KEY failures while still
    # doing real work.
    for key in list(env):
        if key.startswith("HERMES_SESSION_"):
            env.pop(key, None)
    if allow_hooks:
        env["HERMES_ACCEPT_HOOKS"] = "1"
    else:
        env.pop("HERMES_ACCEPT_HOOKS", None)
    proc = await asyncio.create_subprocess_exec(
        hermes_cmd,
        "-p",
        profile,
        "chat",
        "-q",
        message,
        "--quiet",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out_text, err_text = await asyncio.wait_for(
            _collect_subprocess_output(proc, progress_callback=progress_callback),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise SubprocessTaskError(f"subprocess timed out after {timeout_seconds:g}s")
    if proc.returncode != 0:
        detail = err_text or out_text or f"exit code {proc.returncode}"
        raise SubprocessTaskError(f"subprocess exited with {proc.returncode}: {detail}")
    if not out_text:
        detail = f" stderr: {err_text}" if err_text else ""
        raise SubprocessTaskError(f"subprocess produced empty response.{detail}")
    return out_text


async def _collect_subprocess_output(
    proc: asyncio.subprocess.Process,
    *,
    progress_callback: ProgressCallback | None = None,
) -> tuple[str, str]:
    stdout_lines: list[str] = []
    pending_progress: list[str] = []
    last_progress_at = time.time()

    assert proc.stdout is not None
    assert proc.stderr is not None
    while True:
        raw_line = await proc.stdout.readline()
        if not raw_line:
            break
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line or line.startswith("Warning:"):
            continue
        stdout_lines.append(line)
        if progress_callback is not None:
            pending_progress.append(line)
            now = time.time()
            if (
                len(pending_progress) >= SUBPROCESS_PROGRESS_LINE_BATCH
                or now - last_progress_at >= SUBPROCESS_PROGRESS_INTERVAL_SECONDS
            ):
                _emit_progress(progress_callback, "\n".join(pending_progress))
                pending_progress.clear()
                last_progress_at = now

    stderr = await proc.stderr.read()
    await proc.wait()
    return "\n".join(stdout_lines).strip(), stderr.decode("utf-8", errors="replace").strip()


def _clean_subprocess_stdout(text: str) -> str:
    """Remove CLI warning chatter that can precede quiet-mode final output."""

    lines = str(text or "").splitlines()
    while lines and lines[0].startswith("Warning:"):
        lines.pop(0)
    return "\n".join(lines).strip()


def _resolve_hermes_command() -> str | None:
    found = shutil.which("hermes")
    if found:
        return found
    candidate = Path(sys.executable).resolve().parent / "hermes"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    fallback = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes"
    if fallback.exists() and os.access(fallback, os.X_OK):
        return str(fallback)
    return None


def _is_error_response(response: str) -> bool:
    return str(response or "").lstrip().lower().startswith("error:")


def _call_delegate_task(
    *,
    goal: str,
    context: str,
    toolsets: list[str] | None,
    max_iterations: int,
) -> str:
    """Invoke Hermes delegate_task synchronously and extract the summary text."""

    delegate_task = _import_hermes_delegate_task()

    parent_agent = _build_parent_agent()
    # Hermes delegate_task treats an empty/falsey toolset list as "inherit from
    # parent".  Use an impossible sentinel so the child-toolset intersection is
    # empty, preserving incoming.tool_access="none" as truly text-only.
    delegate_toolsets = ["__agency_no_tools__"] if toolsets == [] else toolsets
    # Plugin worker logs should not leak into daemon stdout/stderr while the
    # subagent runs; the result is returned through task artifacts instead.
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            raw = delegate_task(
                goal=goal,
                context=context,
                toolsets=delegate_toolsets,
                max_iterations=max_iterations,
                background=False,
                parent_agent=parent_agent,
            )
    return _extract_delegate_summary(raw)


def _import_hermes_delegate_task():
    """Import Hermes' core delegate_task without being shadowed by plugin tools.py.

    The plugin itself has a ``tools.py`` module.  When scripts are run from the
    plugin directory, Python can mistake that file for Hermes' top-level
    ``tools`` package.  Production Hermes normally has its source root first on
    sys.path, but this defensive import keeps local validation and daemon
    startup paths from depending on path order.
    """

    try:
        return importlib.import_module("tools.delegate_tool").delegate_task
    except Exception as first_exc:  # noqa: BLE001 - retry with sanitized sys.path
        plugin_dir = Path(__file__).resolve().parent
        original_path = list(sys.path)
        removed_modules: dict[str, Any] = {}
        hermes_roots = _hermes_source_root_candidates(plugin_dir)
        try:
            sys.path = _delegate_import_sys_path(original_path, plugin_dir, hermes_roots)
            removed_modules = _remove_plugin_tools_shadow(plugin_dir)
            return importlib.import_module("tools.delegate_tool").delegate_task
        except Exception as second_exc:  # noqa: BLE001
            raise TaskProcessingError(
                f"Could not import Hermes delegate_task: {second_exc}"
            ) from first_exc
        finally:
            sys.path = original_path
            for name, module in removed_modules.items():
                sys.modules.setdefault(name, module)


def _delegate_import_sys_path(
    original_path: list[str], plugin_dir: Path, hermes_roots: list[Path]
) -> list[str]:
    """Build a temporary import path that prefers Hermes core over plugin tools.py."""

    sanitized: list[str] = []
    seen: set[Path] = set()

    def append_entry(entry: str) -> None:
        try:
            resolved = Path(entry or os.getcwd()).resolve()
        except Exception:
            sanitized.append(entry)
            return
        if _is_path_under_plugin(resolved, plugin_dir) or resolved in seen:
            return
        seen.add(resolved)
        sanitized.append(entry)

    for root in hermes_roots:
        append_entry(str(root))
    for entry in original_path:
        append_entry(entry)
    return sanitized


def _remove_plugin_tools_shadow(plugin_dir: Path) -> dict[str, Any]:
    """Drop top-level ``tools`` modules loaded from this plugin tree.

    Pool runners execute ``pool/agency_node_runner.py`` directly, which puts
    ``hermes-agency/pool`` on ``sys.path``. In that runtime, a top-level
    ``tools`` import can resolve to ``pool/tools.py`` instead of the plugin's
    root ``tools.py``. Both files are plugin implementation modules, not the
    Hermes core ``tools`` package, so remove either shadow before retrying the
    core delegate import.
    """

    removed: dict[str, Any] = {}
    for name, module in list(sys.modules.items()):
        if name != "tools" and not name.startswith("tools."):
            continue
        module_file = getattr(module, "__file__", "") or ""
        if module_file and _is_path_under_plugin(Path(module_file), plugin_dir):
            removed[name] = sys.modules.pop(name)
    return removed


def _is_path_under_plugin(path: Path, plugin_dir: Path) -> bool:
    try:
        resolved = path.resolve()
        plugin_root = plugin_dir.resolve()
    except Exception:
        return False
    return resolved == plugin_root or plugin_root in resolved.parents


def _hermes_source_root_candidates(plugin_dir: Path) -> list[Path]:
    """Find Hermes source roots that contain the core ``tools`` package."""

    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: str | Path | None) -> None:
        if candidate is None:
            return
        try:
            root = Path(candidate).expanduser().resolve()
        except Exception:
            return
        if root == plugin_dir or root in seen or not _has_core_delegate_tool(root):
            return
        seen.add(root)
        candidates.append(root)

    for module_name in (
        "run_agent",
        "hermes_constants",
        "model_tools",
        "toolsets",
        "hermes_cli",
        "hermes_cli.config",
    ):
        add(_source_root_from_loaded_module(module_name))
        add(_source_root_from_module_spec(module_name))

    for entry in sys.path:
        add(entry or os.getcwd())

    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        add(parent)

    hermes_home = os.getenv("HERMES_HOME")
    if hermes_home:
        add(Path(hermes_home) / "hermes-agent")

    default_home = Path.home() / ".hermes"
    add(default_home / "hermes-agent")
    profiles_dir = default_home / "profiles"
    try:
        profile_homes = [path for path in profiles_dir.iterdir() if path.is_dir()]
    except OSError:
        profile_homes = []
    for profile_home in profile_homes:
        add(profile_home / "hermes-agent")

    return candidates


def _source_root_from_loaded_module(module_name: str) -> Path | None:
    module = sys.modules.get(module_name)
    module_file = getattr(module, "__file__", None) if module is not None else None
    if not module_file:
        return None
    return _source_root_from_module_file(module_file)


def _source_root_from_module_spec(module_name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    return _source_root_from_module_file(spec.origin)


def _source_root_from_module_file(module_file: str | Path) -> Path | None:
    path = Path(module_file).resolve()
    if path.name == "__init__.py":
        return path.parent.parent
    if path.parent.name in {"hermes_cli", "agent", "gateway", "tools"}:
        return path.parent.parent
    return path.parent


def _has_core_delegate_tool(root: Path) -> bool:
    return (root / "tools" / "__init__.py").is_file() and (
        root / "tools" / "delegate_tool.py"
    ).is_file()


def _build_parent_agent():
    """Build a quiet parent AIAgent so delegate_task has runtime context.

    Hermes' delegate_task implementation requires a parent AIAgent for model,
    credential, toolset, session, and SOUL/profile context.  Incoming A2A tasks
    are processed outside a normal chat turn, so we construct a minimal quiet
    parent using the same runtime-resolution path as Hermes oneshot mode.
    """

    from hermes_cli.config import load_config
    from hermes_cli.fallback_config import get_fallback_chain
    from hermes_cli.models import detect_provider_for_model
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from run_agent import AIAgent

    cfg = load_config()
    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, str):
        cfg_model = model_cfg
        cfg_provider = ""
    else:
        cfg_model = model_cfg.get("default") or model_cfg.get("model") or ""
        cfg_provider = str(model_cfg.get("provider") or "").strip().lower()

    env_model = os.getenv("HERMES_INFERENCE_MODEL", "").strip()
    effective_model = env_model or cfg_model
    effective_provider = (
        os.getenv("HERMES_INFERENCE_PROVIDER", "").strip().lower() or cfg_provider or None
    )

    if env_model and effective_provider is None:
        detected = detect_provider_for_model(env_model, cfg_provider or "auto")
        if detected:
            effective_provider, effective_model = detected

    runtime = resolve_runtime_provider(
        requested=effective_provider,
        target_model=effective_model or None,
    )

    try:
        from hermes_state import SessionDB

        session_db = SessionDB()
    except Exception:
        session_db = None

    parent_session_id = f"agency-{uuid.uuid4().hex[:12]}"
    _precreate_delegate_parent_session(
        session_db=session_db,
        parent_session_id=parent_session_id,
        effective_model=effective_model,
        runtime=runtime,
    )

    parent = AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=effective_model,
        enabled_toolsets=None,
        quiet_mode=True,
        platform="agency",
        session_id=parent_session_id,
        session_db=session_db,
        credential_pool=runtime.get("credential_pool"),
        fallback_model=get_fallback_chain(cfg) or None,
        clarify_callback=_noninteractive_clarify_callback,
    )
    parent.suppress_status_output = True
    parent.stream_delta_callback = None
    parent.tool_gen_callback = None
    return parent


def _precreate_delegate_parent_session(
    *,
    session_db: Any,
    parent_session_id: str,
    effective_model: str,
    runtime: dict[str, Any],
) -> None:
    """Create the parent session row used by delegate_task children.

    Hermes delegate_task records child sessions with parent_session_id set to
    the parent agent's session id. Incoming A2A processing builds that parent
    outside a normal chat turn, so the row must exist before children write to
    the profile SessionDB or SQLite foreign keys fail.
    """

    if session_db is None:
        return
    try:
        session_db.create_session(
            parent_session_id,
            "agency",
            model=effective_model,
            model_config={
                "_agency_delegate_parent": True,
                "provider": runtime.get("provider"),
            },
        )
    except Exception:  # noqa: BLE001 - missing parent row must not break task handling
        logger.warning("Could not pre-create Hermes Agency delegate parent session", exc_info=True)


def _extract_delegate_summary(raw: Any) -> str:
    """Extract response text from delegate_task's JSON result."""

    if isinstance(raw, dict):
        payload = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text

    if payload.get("error"):
        raise TaskProcessingError(str(payload["error"]))

    results = payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            status = str(first.get("status") or "").lower()
            if status and status not in {"completed", "success", "ok"}:
                raise TaskProcessingError(str(first.get("error") or f"delegation status={status}"))
            summary = first.get("summary")
            if summary is not None:
                return str(summary).strip()
            if first.get("error"):
                raise TaskProcessingError(str(first["error"]))

    summary = payload.get("summary")
    if summary is not None:
        return str(summary).strip()
    return json.dumps(payload, ensure_ascii=False)


def _active_profile_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()).expanduser()
    except Exception:
        return Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def _find_skill_file(requested: str, profile_home: Path) -> tuple[str, Path] | None:
    from .card_builder import _cfg_get, _read_yaml_file

    roots = [profile_home / "skills"]
    config = _read_yaml_file(profile_home / "config.yaml")
    external = _cfg_get(config, "skills", "external_dirs", default=[])
    if isinstance(external, list):
        roots.extend(Path(item).expanduser() for item in external if isinstance(item, str))
    roots = [root for root in roots if root.is_dir() and not root.is_symlink()]
    if not roots:
        return None

    candidates: list[tuple[str, Path]] = []
    for skills_dir in roots:
        for skill_file in sorted(skills_dir.glob("**/SKILL.md")):
            if skill_file.is_symlink() or not skill_file.is_file():
                continue
            text = _read_text(skill_file)
            frontmatter = _extract_frontmatter(text)
            raw_name = str(frontmatter.get("name") or "").strip()
            if not raw_name:
                raw_name = _fallback_frontmatter_value(text, "name")
            ids: list[str] = []
            if raw_name:
                ids.append(_normalise_skill_id(raw_name))
            rel_parent = skill_file.parent.relative_to(skills_dir).as_posix()
            ids.append(_normalise_skill_id(rel_parent))
            for candidate_id in dict.fromkeys(ids):
                candidates.append((candidate_id, skill_file))

    for candidate_id, skill_file in candidates:
        if candidate_id == requested:
            return candidate_id, skill_file

    boundary_prefix_matches = [
        item
        for item in candidates
        if item[0].startswith(f"{requested}-") or item[0].startswith(f"{requested}.")
    ]
    if boundary_prefix_matches:
        return _best_skill_match(boundary_prefix_matches)

    review_matches = [item for item in candidates if f"{requested}-review" in item[0]]
    if review_matches:
        return _best_skill_match(review_matches)

    boundary_substring_matches = [
        item
        for item in candidates
        if f"-{requested}-" in f"-{item[0]}-" or f".{requested}." in f".{item[0]}."
    ]
    if boundary_substring_matches:
        return _best_skill_match(boundary_substring_matches)

    prefix_matches = [item for item in candidates if item[0].startswith(requested)]
    if prefix_matches:
        return _best_skill_match(prefix_matches)

    substring_matches = [item for item in candidates if requested in item[0]]
    if substring_matches:
        return _best_skill_match(substring_matches)

    return None


def _best_skill_match(matches: list[tuple[str, Path]]) -> tuple[str, Path]:
    return sorted(matches, key=lambda item: (len(item[0]), item[0], str(item[1])))[0]


def _normalise_skill_id(raw: str) -> str:
    slug = str(raw or "").strip().lower().replace("/", ".")
    slug = re.sub(r"[^a-z0-9_.-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-._")
    return slug or "hermes-skill"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _extract_frontmatter(text: str) -> dict[str, Any]:
    if not str(text).startswith("---"):
        return {}
    parts = str(text).split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml

        loaded = yaml.safe_load(parts[1])
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _fallback_frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*[\"']?(.+?)[\"']?\s*$", str(text))
    return match.group(1).strip() if match else ""


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _sender_name(task_record: Any) -> str | None:
    metadata = _field(task_record, "metadata") or {}
    context_packet = _field(task_record, "context_packet") or {}
    for source in (metadata, context_packet):
        if not isinstance(source, dict):
            continue
        for key in ("sender_name", "from_agent", "source_agent", "agent_name", "sender"):
            value = source.get(key)
            if value:
                return str(value)
        sender = source.get("sender")
        if isinstance(sender, dict):
            for key in ("name", "agent", "profile"):
                value = sender.get(key)
                if value:
                    return str(value)
    return None


def _noninteractive_clarify_callback(question: str, choices=None) -> str:
    if choices:
        return f"[No user available for clarification. Pick the best option from {choices} and continue.]"
    return (
        "[No user available for clarification. Make the most reasonable assumption and continue.]"
    )
