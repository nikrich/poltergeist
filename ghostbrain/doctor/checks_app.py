"""App, vault, contexts, llm-provider, scheduler, routing-mode checks."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from ghostbrain.doctor import CheckResult, Fix, desktop_config, register

APP_BUNDLE = Path("/Applications/Poltergeist.app")


def _platform() -> str:
    return sys.platform


def _app_installed() -> bool:
    if _platform() == "darwin":
        return APP_BUNDLE.exists()
    return True  # other platforms: the binary running doctor IS the app's sidecar


def _app_process_running() -> bool:
    if _platform() != "darwin":
        return True
    proc = subprocess.run(["pgrep", "-f", "Poltergeist.app/Contents/MacOS/Poltergeist"],
                          capture_output=True, text=True, check=False)
    return proc.returncode == 0


def _descriptor() -> dict | None:
    from ghostbrain.api import runtime

    return runtime.load_descriptor()


def _health_ok(port: int, token: str) -> bool:
    import httpx

    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health",
                      headers={"Authorization": f"Bearer {token}"}, timeout=3.0)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


@register("app")
def check_app() -> CheckResult:
    if not _app_installed():
        return CheckResult(
            id="app", status="fail", summary="Poltergeist.app not found in /Applications",
            fix=Fix(kind="manual", command="download the latest release from https://github.com/nikrich/poltergeist/releases/latest and drag it to Applications"),
        )
    desc = _descriptor()
    running = _app_process_running()
    if desc is None and not running:
        return CheckResult(
            id="app", status="fail", summary="Poltergeist is not running",
            fix=Fix(kind="manual", command="open Poltergeist and wait for the sidebar to load"),
        )
    if desc is None and running:
        return CheckResult(
            id="app", status="fail", summary="app is running but its sidecar is not published",
            detail="Usually the app was reopened before the previous sidecar finished shutting down; it then runs read-only with no recorder or sync.",
            fix=Fix(kind="manual", command="quit Poltergeist, wait ten seconds, reopen it"),
        )
    port, token = int(desc.get("port", 0)), str(desc.get("token", ""))
    if not _health_ok(port, token):
        return CheckResult(
            id="app", status="fail", summary=f"sidecar on port {port} is not answering",
            fix=Fix(kind="manual", command="quit Poltergeist, wait ten seconds, reopen it"),
        )
    return CheckResult(id="app", status="ok", summary=f"sidecar running on port {port}", data={"port": port})


@register("vault")
def check_vault() -> CheckResult:
    from ghostbrain.paths import vault_path

    root = vault_path()
    marker = root / "90-meta" / "routing.yaml"
    if not marker.exists():
        return CheckResult(
            id="vault", status="fail", summary=f"{root} is not bootstrapped",
            fix=Fix(kind="automated", command="setup bootstrap"),
        )
    desktop_vault = desktop_config.load().get("vaultPath")
    if isinstance(desktop_vault, str) and desktop_vault.strip() and Path(desktop_vault).expanduser().resolve() != root.resolve():
        return CheckResult(
            id="vault", status="warn", summary=str(root),
            detail=f"The desktop app's setting points at {desktop_vault}, but the sidecar uses {root}. Set the app's vault path back to {root} in Settings until the two are reconciled.",
            fix=Fix(kind="manual", command=f"Settings → vault path → {root}"),
        )
    return CheckResult(id="vault", status="ok", summary=str(root))


def _contexts() -> tuple[str, ...]:
    from ghostbrain.routing_config import contexts

    return contexts()


@register("contexts")
def check_contexts() -> CheckResult:
    ctx = _contexts()
    if not ctx:
        return CheckResult(
            id="contexts", status="fail", summary="no contexts configured",
            fix=Fix(kind="manual", command="add a `contexts:` list to 90-meta/routing.yaml (e.g. personal, work)"),
        )
    return CheckResult(id="contexts", status="ok", summary=", ".join(ctx), data={"contexts": list(ctx)})


_LOGIN_FIX = {
    "claude": "npm install -g @anthropic-ai/claude-code && claude login",
    "codex": "npm i -g @openai/codex && codex login",
    "gemini": "npm i -g @google/gemini-cli, run `gemini` once and choose Login with Google",
    "openai_http": "Settings → AI provider → set the base URL and pick a model for each tier",
}


def _llm_provider():
    from ghostbrain.llm.providers import get_provider

    return get_provider()


@register("llm-provider")
def check_llm_provider() -> CheckResult:
    from ghostbrain.llm.client import LLMError

    try:
        provider = _llm_provider()
    except LLMError as e:
        return CheckResult(
            id="llm-provider", status="fail", summary=str(e),
            fix=Fix(kind="manual", command="edit llm.provider in 90-meta/config.yaml (claude | codex | gemini | openai_http)"),
        )
    try:
        probe = provider.probe()
    except Exception as e:  # noqa: BLE001 — a doctor check must never raise
        return CheckResult(
            id="llm-provider", status="fail", summary=f"{provider.id}: {e}",
            fix=Fix(kind="manual", command=_LOGIN_FIX.get(provider.id, "edit llm.provider in 90-meta/config.yaml (claude | codex | gemini | openai_http)")),
        )
    models = provider.models()
    tiers = " ".join(f"{t}={models.get(t, '?')}" for t in ("fast", "balanced", "quality"))
    data = {"provider": provider.id, "models": models, "probe": probe.detail}
    if not probe.ok:
        return CheckResult(
            id="llm-provider", status="fail", summary=f"{provider.id}: {probe.reason}",
            detail="Every routing, extraction, digest and chat call goes through this provider.",
            fix=Fix(kind="manual", command=_LOGIN_FIX.get(provider.id, "edit llm.provider in 90-meta/config.yaml (claude | codex | gemini | openai_http)")),
            data=data,
        )
    return CheckResult(id="llm-provider", status="ok", summary=f"{provider.id}: {probe.reason} — {tiers}", data=data)


@register("scheduler")
def check_scheduler() -> CheckResult:
    cfg = desktop_config.load()
    enabled = cfg.get("schedulerEnabled")
    if enabled is True:
        return CheckResult(id="scheduler", status="ok", summary="enabled")
    if enabled is False:
        return CheckResult(
            id="scheduler", status="fail", summary="disabled — connectors will never sync",
            fix=Fix(kind="manual", command="Settings → background → turn on 'Run scheduler in-app'"),
        )
    return CheckResult(
        id="scheduler", status="warn", summary="desktop settings not found; cannot tell",
        detail=f"expected {desktop_config.path()}",
    )


@register("routing-mode")
def check_routing_mode() -> CheckResult:
    from ghostbrain.paths import vault_path

    cfg_file = vault_path() / "90-meta" / "config.yaml"
    cfg: dict = {}
    if cfg_file.exists():
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    mode = str((cfg.get("worker") or {}).get("routing_mode", "review_only"))
    inbox = vault_path() / "00-inbox" / "raw"
    count = len(list(inbox.glob("*.md"))) if inbox.exists() else 0
    data = {"mode": mode, "inbox_count": count}
    if mode == "live":
        return CheckResult(id="routing-mode", status="ok", summary="live", data=data)
    return CheckResult(
        id="routing-mode", status="warn",
        summary=f"review_only — {count} item(s) held in 00-inbox/raw, nothing filed to contexts",
        detail="Review mode keeps every captured item in the inbox for you to audit. The app's meeting and calendar views only read filed notes, so it looks empty until you go live.",
        fix=Fix(kind="automated", command="setup go-live"),
        data=data,
    )
