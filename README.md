# storm-re

Build-aware resolver, decompile cache and MCP server in front of
[`pyghidra-mcp`](https://github.com/clearbluejar/pyghidra-mcp), for the PC
builds of CyberConnect2's Storm-engine fighting games, plus format notes for
their data files.

Ghidra knows how to decompile. It does not know that a program is Storm 4 1.09,
that its image base is `0x140000000`, that `0x7AB468` is
`ccPlayer::ChangeAction`, or that the same function lives at a different RVA in
1.06. `storm-re` supplies that layer, caches the expensive output, and returns a
bounded summary instead of a raw xref/callee dump.

> **No game files are included.** This repository contains tool code and
> documentation only: no executables, archives, extracted assets, decompiled
> code or symbol dumps. You need your own legally obtained copy of the games.
> Not affiliated with or endorsed by CyberConnect2 or the games' publisher.

## Contents

| Path | What |
|---|---|
| `src/storm_re/` | CLI + MCP server (Python 3.11+, stdlib only) |
| `docs/formats/` | CPK, xfbin and param-table layouts |
| `docs/reference/` | known Storm 4 1.09 addresses, struct offsets, input bits |
| `docs/agent-guide.md` | tool selection and workflows for LLM agents |
| `config.example.toml` | every setting with its default |

## Requirements

- Python 3.11+
- A running `pyghidra-mcp` with the game executables imported (only needed for
  `decomp`/`xrefs` cache misses; everything else is local SQLite).
- Optional data sources, all produced from your own copies (see
  [Data sources](#data-sources)).

## Quick start

```sh
git clone <this repo> && cd storm-re
cp config.example.toml ~/.config/storm-re/config.toml   # edit mcp_url + [builds]
bin/storm-re init            # discover programs, SHA-256, image bases; ingest names
bin/storm-re bsim ingest     # optional: precomputed BSim edges
bin/storm-re index           # optional: pre-decompile the hot set

bin/storm-re resolve ccPlayer::ChangeAction -b s4
bin/storm-re decomp ccPlayer::ChangeAction -b s4
bin/storm-re xrefs ccPlayer::ChangeAction -b s4 --limit 20
bin/storm-re diff ccPlayer::ChangeAction --from s4 --to s4-debug --map
bin/storm-re map ccPlayer::ChangeAction --from s4
bin/storm-re symbolize ccPlayer::ChangeAction -b s4
bin/storm-re state_surface ccPlayer -b s4 --limit 20
bin/storm-re write_sites ccPlayer --offset 0xCC0 -b s4 --limit 20
bin/storm-re patch_diff --from s4 --to s4-debug --limit 5
bin/storm-re find ChangeAction
```

`pip install -e .` also works and installs a `storm-re` entry point.

## Configuration

Precedence: CLI flag > environment variable > config file > default.
Config file: `$STORM_RE_CONFIG`, else `$XDG_CONFIG_HOME/storm-re/config.toml`
(`~/.config/storm-re/config.toml`).

| Key | Env | Default | Meaning |
|---|---|---|---|
| `mcp_url` | `STORM_RE_MCP` | `http://127.0.0.1:8770/mcp` | pyghidra-mcp endpoint |
| `db` | `STORM_RE_DB` | `~/.local/share/storm-re/storm-re.db` | SQLite cache |
| `host` | `STORM_RE_HOST` | `local` | label stored with indexed programs |
| `nucc_root` | `STORM_RE_NUCC` | `~/nucc-symbols` | `games/<game>/<sha>/functions.csv` name sets |
| `manual_root` | `STORM_RE_MANUAL` | `~/ghidra/storm-research` | `*.manual.csv` hand-verified names |
| `trilogy_tsv` | `STORM_RE_TRILOGY_TSV` | `~/ghidra/trilogy-dynsym.tsv` | Switch dynsym dump |
| `bsim_root` | `STORM_RE_BSIM` | `~/ghidra/match/out` | `*.bsim.tsv` exports |
| `hot_json` | `STORM_RE_HOT` | `hot.json` in the repo | hot-set topics for `index` |
| `assets_root` | `STORM_RE_ASSETS` | `~/storm-cpk-extracted` | your extracted CPK tree |
| `assets_win_root` | `STORM_RE_ASSETS_WIN` | (off) | Windows mirror reported as `win_path` |

Ghidra program names carry a per-project hash suffix (`/NSUNS4_release.exe-75912b`).
Point each build alias at your own import:

```toml
[builds.s4]
program = "/NSUNS4_release.exe-1a2b3c"
```

`bin/storm-re builds` shows what was found. A build whose program is missing is
skipped, so you only need the games you have.

## Data sources

Every source is optional; missing ones are skipped by `init`.

- **Ghidra names** come with your own analysis.
- **Name CSVs** (`nucc_root`): `games/<game>/<sha256>/functions.csv` with columns
  `rva,name[,short_name,namespace,confidence,size,evidence]`. Matched to builds by
  the exe SHA-256. A community name set in this layout is published at
  [exavadw/naruto-storm-symbols](https://github.com/exavadw/naruto-storm-symbols).
- **Manual CSVs** (`manual_root`): same columns; file → build mapping in
  `config.MANUAL_SOURCES`. Highest precedence.
- **Switch dynsym TSV** (`trilogy_tsv`): tab-separated, RVA (hex) first, mangled
  or demangled name last, ≥5 columns. Dump it from your own Switch build.
- **BSim exports** (`bsim_root`): `*.bsim.tsv`, 7 tab-separated columns
  `query_rva(hex) query_name target_exe target_addr(hex) target_name similarity significance`.
  Target exe names map to aliases via `config.TARGET_EXE_PATTERNS`.
- **Extracted CPKs** (`assets_root`): `<root>/<game>/<cpk dir>/<cpk name>/<entry>`
  plus `<root>/CPKS.tsv` (`game<TAB>cpk` rows). See `docs/formats/cpk.md`.

## Commands

| command | purpose |
|---|---|
| `init` | discover programs, SHA-256 and image base; ingest nucc/manual/trilogy symbols |
| `builds` | alias → program, sha, base, symbol/cache counts |
| `resolve <va\|rva\|name>` | one build-verified symbol |
| `decomp <target>` | bounded decompile summary; cached |
| `xrefs <target>` | callers, callees, data refs; deduplicated |
| `diff <target> --from A --to B [--map]` | signature, similarity, symbolic callee delta |
| `bsim ingest` | load precomputed BSim TSVs (no Ghidra) |
| `map <name> [--from A] [--to B]` | cross-build RVA with method/score/confidence |
| `index [--topic T]` | pre-decompile the hot set into SQLite |
| `show <topic\|name> [--symbolized]` | read indexed entries / readable code with no backend call |
| `symbolize <target>` | rewrite `FUN_`/`SUB_`/`DAT_` to known names |
| `state_surface <root>` | static rollback field manifest (offsets, r/w, confidence) |
| `write_sites <target> --offset O` | who writes a root+offset (or address xrefs) |
| `input_path` | pad poll → CtrlInputPad → gates → ChangeAction |
| `frame_tick` | timer idioms and per-frame constants |
| `net_session` | Steam/net-session send/recv/tick surface |
| `scene_dispatch` | scene/message dispatch |
| `patch_diff --from A --to B` | batch function diff between builds (byte mode when both files exist) |
| `export <topic> --out FILE` | markdown report from indexed facts |
| `find <query>` | symbol index, strings, or code search |
| `asset_index` / `asset_find` / `asset_info` | index and inspect your extracted CPK tree; parses xfbin chunk tables |
| `stat` | cache hit/size/savings |

Global: `--db`, `--mcp`, `--json`, `--quiet`, `--timeout`, `--no-cache`.
Exit codes: `0` ok, `1` usage, `2` not found/ambiguous, `3` backend, `4` diff
target missing, `5` database.

## MCP server

```sh
bin/storm-re-mcp --db ~/.local/share/storm-re/storm-re.db
```

Stdio by default, no third-party packages. 22 tools: the resolver/cache/index
surface plus `storm_explain` (one-call function explanation), `storm_batch`
(several read-only calls in one request) and `storm_asset_find`/`storm_asset_info`.
Every tool runs the CLI with `--json`, so MCP and CLI cannot drift.

- Negotiates MCP `2024-11-05` / `2025-03-26` / `2025-06-18`; tool annotations
  and `structuredContent`.
- Resources: `storm-re://builds`, `storm-re://stats`, `storm-re://assets`,
  `storm-re://topic/{topic}`, `storm-re://function/{build}/{rva}`.
- Prompts: `rollback_audit`, `story_port`, `clean_vs_mod`, `function_explain`.
- Stdio progress notifications and cancellation; long calls run in a worker.
- Optional HTTP JSON endpoint: `bin/storm-re-mcp --http 127.0.0.1:8788`.
  Bearer token via `--token`/`STORM_RE_MCP_TOKEN`; a non-loopback bind requires a
  token.
- Tool responses are capped at 48 KB; use resources for full reports/code.

Client config:

```json
"storm-re": {
  "type": "stdio",
  "command": "/path/to/storm-re/bin/storm-re-mcp",
  "args": ["--db", "/path/to/storm-re.db"]
}
```

`resolve`, `show`, `stat` and symbol `find` work with Ghidra down; `decomp`
and `xrefs` need it only on a cache miss. See `docs/agent-guide.md` for agent
workflows.

## Builds

`s4` (1.09), `s4-debug` (1.06), `s4-107`, `s3`/`s3hd`, `s3fb`, `s2`, `s1`,
`s1-clean`, `s1-debug`, `connections`, `revolution`, `trilogy` (Switch arm64,
name/BSim source only). Defined in `src/storm_re/config.py`.

## Symbol precedence

`manual` (rank 3) > `nucc` (rank 2) > `trilogy` (rank 2) > Ghidra (rank 1).

## Cache

Key: `(sha256, rva, kind, params, name_version)`. `name_version` is a hash of the
build's `rva:name` table, so ingesting names invalidates only the affected
entries. Raw JSON is zlib-compressed; `stat` reports raw vs summary chars.
`map` prefers a same-name symbol, then a direct BSim edge, then a
Switch-mediated edge, then an equal RVA.

## Tests

```sh
# unit, no network, no game files
PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_*.py'

# live (needs your DB + MCP + imported programs)
STORM_RE_LIVE=1 PYTHONPATH=src:tests python3 -m unittest discover -s tests -p 'test_live*.py'
```

## Design notes

- Read-only against Ghidra: no renames, retypes, comments or saves.
- Every answer carries `build`, `program`, `sha256`, `rva`, `va`, `confidence`,
  `source`. A wrong-build answer is visible, never silent.
- Address input tries VA and RVA and picks the interpretation that resolves to a
  symbol; `--addr-kind va|rva` forces one.

## License

Code: [MIT](LICENSE). Documentation in `docs/`: [CC BY 4.0](docs/LICENSE).
Game names are used only to identify compatible software.
