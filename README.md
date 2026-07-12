# dvm-eahelper — LeanIX Enterprise Architecture Helper

Successor to [`dvm-leanix`](https://github.com/divyavanmahajan/dvm-leanix) and
[`dvm-eagraph`](https://github.com/divyavanmahajan/dvm-eagraph), combined into a single package.

One CLI (`eahelper`) to:

- Run a local **GraphQL proxy** to SAP LeanIX — extracts the Bearer token from your
  already-logged-in browser via Playwright CDP, serves GraphiQL for exploration
- **Download** factsheets and relationships as JSON
- **Load** them into a graph database — **KuzuDB** (embedded, default) or **Neo4j**

Works on **Windows** and **macOS**.

## Installation

```bash
uv tool install dvm-eahelper        # or: pip install dvm-eahelper
uvx playwright install chromium     # one-time, for the proxy
```

## Quick start

### 1. Launch a debug browser and log into LeanIX

**Windows (PowerShell, Edge):**

```powershell
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  "--remote-debugging-port=9222 --user-data-dir=C:\Temp\edge-debug --no-first-run --no-default-browser-check"
```

**macOS (Chrome):**

```bash
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-debug"
```

Log into your LeanIX workspace in that browser window.

### 2. Run the proxy (separate terminal, keep it running)

```bash
eahelper proxy
```

### 3. Download and load

```bash
eahelper download --relations
eahelper load              # prompts for DB backend; KuzuDB is the default
eahelper load --db neo4j   # or choose explicitly
```

KuzuDB is embedded — no server needed; the database is a local directory
(`--db-path`, default `./eahelper-kuzu-db`). For Neo4j, start your server and put
`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` in a `.env` file.

## Commands

| Command | Purpose |
|---|---|
| `eahelper proxy` | Local GraphQL proxy + GraphiQL UI |
| `eahelper diagnose` | Check browser/CDP/SSL connectivity |
| `eahelper download` | Download factsheets & relationships to JSON |
| `eahelper load` | Load downloaded JSON into KuzuDB or Neo4j |
| `eahelper seed` | Seed example/reference data |

Backend selection precedence: `--db` flag → `EAHELPER_DB` env var → interactive
prompt (default **kuzu**).

## Agent skill

An installable Agent Skill (Claude Code, GitHub Copilot, and other
[agentskills.io](https://agentskills.io)-compatible tools) that walks you through
setup and usage lives at
[dvm-eahelper-skills](https://github.com/divyavanmahajan/dvm-eahelper-skills).

## Migrating from dvm-leanix / dvm-eagraph

| Old | New |
|---|---|
| `dvm-leanix serve` / `lean-ix serve` | `eahelper proxy` |
| `dvm-leanix download` | `eahelper download` |
| `dvm-leanix diagnose` | `eahelper diagnose` |
| `dvm-eagraph` | `eahelper load` |
| `dvm-eagraph-seed` | `eahelper seed` |

Token store moved from `~/.lean-ix/` to `~/.eahelper/`.

## License

MIT
