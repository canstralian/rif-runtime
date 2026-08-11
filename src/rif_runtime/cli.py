from typing import Any

import typer
import uvicorn
from pydantic import ValidationError
from rich import print

from .config import ServerSection, get_settings
from .mcp.metasploit import GovernanceMode, MetasploitIntent
from .replay import ReplayEngine
from .runtime import RIFRuntime
from .schemas import PolicyRequest

app = typer.Typer()


@app.command()
def serve(host: str | None = None, port: int | None = None) -> None:
    """Run the API server.

    Bind address comes from the configuration contract ([server] host/port in
    rif.toml, or RIF_SERVER_HOST / RIF_SERVER_PORT); --host and --port override
    it for a single invocation.  config.py is the single source of truth here —
    this command previously hardcoded 127.0.0.1 and disagreed with the
    contract's default.
    """
    overrides: dict[str, Any] = {}
    if host is not None:
        overrides["host"] = host
    if port is not None:
        overrides["port"] = port

    # Re-validate through ServerSection rather than passing the flags straight
    # to uvicorn: overrides must clear the same checks as configured values, or
    # `--port 70000` reaches uvicorn and fails with a much worse message.
    try:
        server = ServerSection.model_validate(
            get_settings().server.model_dump() | overrides
        )
    except ValidationError as exc:
        raise typer.BadParameter(str(exc)) from exc

    uvicorn.run("rif_runtime.api:app", host=server.host, port=server.port, reload=True)


@app.command()
def check(actor: str, action: str, target: str) -> None:
    r = RIFRuntime()
    print(
        r.evaluate(
            PolicyRequest(actor=actor, action=action, target=target)
        ).model_dump_json(indent=2)
    )


if __name__ == "__main__":
    app()


@app.command()
def replay(decisions_path: str = "data/decisions.jsonl") -> None:
    state = ReplayEngine(decisions_path).recover()
    print(state.__dict__)


@app.command("msf-check")
def msf_check(
    capability: str,
    target: str,
    mode: str = "read_only_firewall",
    actor: str = "agent:metasploit",
    scope_id: str = "unscoped",
) -> None:
    r = RIFRuntime()
    intent = MetasploitIntent(
        actor=actor, capability=capability, target=target, scope_id=scope_id
    )
    outcome = r.evaluate_metasploit(intent, mode=GovernanceMode(mode))
    print(outcome.decision.model_dump_json(indent=2))
    print(outcome.evidence.model_dump_json(indent=2))
