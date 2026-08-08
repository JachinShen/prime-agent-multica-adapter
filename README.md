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
