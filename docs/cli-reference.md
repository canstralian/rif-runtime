# CLI Reference

The current Typer CLI is implemented in `src/rif_runtime/cli.py`.

## `rif serve`

Start the FastAPI service with Uvicorn.

```bash
rif serve
rif serve --host 127.0.0.1 --port 8000
rif serve --reload          # development only
```

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to bind |
| `--port` | `8000` | Port to bind |
| `--reload` | off | Restart on source changes (development only) |

Auto-reload is opt-in. It was previously always on, which meant this command —
the one the README quick start documents — started uvicorn's file-watching
reloader even when serving for real.

## `rif check`

Evaluate one policy request and print the resulting decision.

```bash
rif check <actor> <action> <target>
```

Example:

```bash
rif check agent:test http.request https://example.com
```

This creates a runtime instance and therefore may write decision/posture state to the configured data directory.

## `rif replay`

Rebuild graph and posture state from a decisions log.

```bash
rif replay
rif replay /path/to/decisions.jsonl
```

With no path, the command uses the configured/default data directory.

Replay reconstructs runtime state; it is not a remote execution mechanism and should not be treated as proof of an external side effect.

## `rif msf-check`

Evaluate a Metasploit capability request through the governed runtime path.

```bash
rif msf-check <capability> <target>
```

Optional parameters include:

```text
--mode
--actor
--scope-id
```

The default mode is `read_only_firewall` and the default actor is `agent:metasploit`.

This command evaluates the governed Metasploit integration. It should not be described as unrestricted Metasploit execution.

## Commands not currently implemented

Older repository documentation referenced commands such as:

```text
rif execute
rif evidence
rif telemetry
rif validate
rif policy
```

Those are not part of the current CLI surface. Do not build tooling or documentation around them until they are implemented and tested.

## Data and side effects

`rif check` and `rif replay` operate against the runtime's configured data directory. For development and tests, use an isolated `RIF_DATA_DIR` rather than shared production state.
