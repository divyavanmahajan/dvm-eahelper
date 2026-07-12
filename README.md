# dvm-eahelper — LeanIX Enterprise Architecture Helper

Successor to [`dvm-leanix`](https://github.com/divyavanmahajan/dvm-leanix) and
[`dvm-eagraph`](https://github.com/divyavanmahajan/dvm-eagraph), combined into a single package.

One CLI (`eahelper`) to:

- Run **`eahelper server`** — a GraphQL proxy to SAP LeanIX plus an embedded
  **MCP server** in a single process, with the debug browser managed automatically
- Extract the Bearer token from a managed (or your own) browser via Playwright CDP
- **Download** factsheets and relationships as JSON
- **Load** them into a graph database — **KuzuDB** (embedded, default) or **Neo4j**
- Query the graph from any MCP-aware tool (Claude Code, VS Code Copilot, ...)

Works on **Windows** and **macOS**.

## Installation

```bash
uv tool install dvm-eahelper        # or: pip install dvm-eahelper
uvx playwright install chromium     # one-time, for the proxy
```

## Quick start

```bash
eahelper server
```

On first run this prompts for your LeanIX workspace URL and preferred graph
database, saves the answers to `~/.eahelper/config.toml` (so you're only asked
once), launches a managed debug browser to capture a Bearer token, then closes
it again. The server exposes the GraphQL proxy and an MCP endpoint on one port
(default `8765`).

```bash
eahelper download --relations   # auto-starts the server if it isn't running
eahelper load                   # prompts for DB backend the first time; then remembers it
eahelper load --db neo4j        # or choose explicitly
```

KuzuDB is embedded — no server needed; the database is a local directory
(`--db-path`, or `[graph].kuzu_path` in config.toml, default `./eahelper-kuzu-db`).
For Neo4j, start your server and put `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
in a `.env` file (never in config.toml — no secrets are stored there).

## Configuration

Settings are resolved in this order for every value: **CLI flag → environment
variable → `~/.eahelper/config.toml` → interactive prompt (saved back to
config.toml) → built-in default.**

```bash
eahelper config              # show effective config
eahelper config path         # print the config file path
eahelper config set graph.db kuzu
eahelper config set leanix.workspace_url https://eu-10.leanix.net/YourWorkspace
eahelper config unset browser.browser
```

Sections: `[leanix]` workspace_url, proxy_port · `[browser]` browser, cdp_port,
keep_open · `[graph]` db, kuzu_path, mcp_read_only · `[neo4j]` uri.

## MCP (Model Context Protocol)

`eahelper server` mounts an MCP server at `/mcp` (streamable HTTP), exposing
`get_schema()` and `query(cypher)` tools against your graph database. A stdio
variant is also available for harnesses that spawn a subprocess:

```bash
eahelper mcp                      # stdio transport
eahelper mcp-config                # print Claude Code / VS Code config snippets
eahelper mcp-config --install      # write/merge .mcp.json and .vscode/mcp.json
```

Pass `--mcp-read-only` to `eahelper server` (or set `[graph] mcp_read_only = true`)
to reject write Cypher queries.

## Managed browser

By default, `eahelper server` launches and closes a debug browser automatically
(persistent profile at `~/.eahelper/browser-profile`, CDP port `19222`) whenever
a LeanIX token is needed, and never touches a browser it didn't start. Pass
`--keep-browser` (or set `[browser] keep_open = true`) to leave it open.

If you prefer to manage the browser yourself, launch it manually and eahelper
will connect to the existing CDP endpoint instead of starting a new one:

**Windows (PowerShell, Edge — requires ALL other Edge windows closed first):**

```powershell
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" `
  "--remote-debugging-port=19222 --user-data-dir=C:\Temp\edge-debug --no-first-run --no-default-browser-check"
```

**macOS (Chrome):**

```bash
open -na "Google Chrome" --args --remote-debugging-port=19222 --user-data-dir="$HOME/chrome-debug"
```

## Commands

| Command | Purpose |
|---|---|
| `eahelper server` | GraphQL proxy + MCP server (foreground); add `start`/`stop`/`status` for background |
| `eahelper proxy` | Legacy standalone GraphQL proxy + GraphiQL UI |
| `eahelper diagnose` | Check browser/CDP/SSL connectivity |
| `eahelper download` | Download factsheets & relationships to JSON |
| `eahelper load` | Load downloaded JSON into KuzuDB or Neo4j |
| `eahelper seed` | Seed example/reference data |
| `eahelper mcp` | MCP server over stdio |
| `eahelper mcp-config` | Print/install MCP client config snippets |
| `eahelper config` | View or edit `~/.eahelper/config.toml` |

`download` and `load` auto-start `eahelper server` in the background if it
isn't already running.

## Agent skill

An installable Agent Skill (Claude Code, GitHub Copilot, and other
[agentskills.io](https://agentskills.io)-compatible tools) that walks you through
setup and usage lives at
[dvm-eahelper-skills](https://github.com/divyavanmahajan/dvm-eahelper-skills).

To install it, clone that repo and copy the skill folder into your agent's skills directory:

```bash
git clone https://github.com/divyavanmahajan/dvm-eahelper-skills
cd dvm-eahelper-skills

# Claude Code — personal (all projects)
mkdir -p ~/.claude/skills && cp -R skills/eahelper ~/.claude/skills/eahelper

# Claude Code — this project only
mkdir -p .claude/skills && cp -R skills/eahelper .claude/skills/eahelper

# GitHub Copilot — personal (all projects)
mkdir -p ~/.copilot/skills && cp -R skills/eahelper ~/.copilot/skills/eahelper

# GitHub Copilot — this repo only
mkdir -p .github/skills && cp -R skills/eahelper .github/skills/eahelper
```

```powershell
# Windows (PowerShell), e.g. Claude Code personal:
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse skills\eahelper "$HOME\.claude\skills\eahelper"
```

Then restart your agent (or start a new session) so it picks up the skill.

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
