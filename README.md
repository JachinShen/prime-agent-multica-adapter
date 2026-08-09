# Prime Agent Multica Adapter

A small executable adapter that lets [Prime Agent](https://github.com/PrimeIntellect/prime-agent) run through Multica's custom `pi` runtime profile.

## What it does

Multica invokes a `pi`-compatible command with this contract:

```text
pi -p --mode json --session <path> [--provider P --model M] [custom args...]
pi --list-models
pi --version
```

Prime Agent uses the same JSON event-stream mode but differs in two CLI details:

- `--session` is named `--resume`
- model discovery is `prime-agent model list`

This adapter translates those differences and then replaces itself with the Prime Agent process using `execv`, preserving signals, exit codes, and streaming output.

## Unified session storage

Multica passes a session path as a runtime handle. The adapter keeps that file's
basename but maps it into Prime Agent's canonical session directory, which is
`~/.prime/agent/sessions` by default. This means Multica-created sessions are
visible to the normal Prime Agent terminal session browser, and terminal-created
sessions use the same storage directory.

Override the canonical directory for both processes when needed:

```bash
export PRIME_AGENT_SESSION_DIR=/absolute/path/to/shared/sessions
```

Only one process should write a session at a time. The adapter intentionally does
not implement concurrent-session locking or event arbitration.

For Multica's one-process-per-turn execution model, the adapter also enables
Prime Agent's legacy owned-worker frontend. That frontend reaps the per-turn
worker after the JSON stream closes, so the next Multica turn can resume the
same session without a stale `Session is already active` lease.

When Multica's **steer** action dispatches a replacement turn before the prior
process has finished releasing its session lease, the adapter retries only that
specific `Session is already active` error with exponential backoff. Other
Prime Agent failures are returned unchanged. Configure the retry window with
`PRIME_AGENT_MULTICA_RETRY_ATTEMPTS` and `PRIME_AGENT_MULTICA_RETRY_DELAY` if
needed.

## Install

Copy the executable somewhere on the daemon's `PATH`, for example:

```bash
install -Dm755 prime-agent-multica ~/.multica/bin/prime-agent-multica
```

If Prime Agent is not on `PATH`, set its executable explicitly:

```bash
export PRIME_AGENT_BIN=/absolute/path/to/prime-agent
```

Then configure a Multica custom runtime profile with:

- **Protocol family:** `pi`
- **Command:** `prime-agent-multica`
- **Fixed arguments:** none

For a per-machine path override, point Multica directly at the absolute adapter path.

## Local verification

```bash
./prime-agent-multica --version
./prime-agent-multica --list-models
```

The adapter itself has no network credentials, API keys, or workspace tokens. Provider authentication remains owned by Prime Agent and its local configuration.

## License

MIT. See [LICENSE](LICENSE).
