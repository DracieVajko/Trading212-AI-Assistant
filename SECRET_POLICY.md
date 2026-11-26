# Secret handling policy (hard rules)

The AI agent MUST NEVER read, print, echo, copy or otherwise expose secret
material. This applies to the assistant, all subagents and any tool use.

## Prohibited

- Reading `api.env`, `*.env`, `*.env.*`, or any file under `~/.portfolio-secrets/`.
- Printing, echoing, or including in any response the value of:
  `TRADING212_API_KEY`, `TRADING212_API_SECRET`, `T212_DEMO_API_KEY`,
  `T212_DEMO_API_SECRET`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`,
  `MISTRAL_API_KEY`, `OPENCODE_ZEN_API_KEY`, or any `*_SECRET` / `*_KEY`.
- Searching file contents for secret values or key names (`grep`, `Select-String`).
- Running shell commands that mention secret file paths or key names.
- Writing secrets into logs, reports, commit messages, docs or examples.

## How secrets are used

Secrets live in `~/.portfolio-secrets/api.env` (outside the workspace) and are
loaded by the Python process via `investment_engine.secrets.load_secrets()`.
The agent does not need them and must not access them.

Override location: `PORTFOLIO_SECRETS_FILE`.

## If you need to verify an API works

Do NOT read the key. Instead run the existing read-only helper, which reports
only non-sensitive status (counts, totals) and never prints credentials:

```
py -3.12 tools/t212_cli.py --status     # if available
```

or call `get_positions()` / `get_account_summary()` through a short script and
print only the aggregate numbers, never the key.

## Incident response

If a secret was ever printed into a conversation or log: rotate it at the
provider immediately; do not rely on deleting the message.
