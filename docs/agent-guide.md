# storm-re: agent guide

Use this before raw Ghidra work. `storm-re` is the build-verified, cached,
Storm-aware layer in front of `pyghidra-mcp`. It resolves names and addresses,
symbolizes decompiled code, maps functions across builds, and extracts rollback
state surfaces.

Drop this file into an agent's context (for example a `CLAUDE.md` include).

- MCP server name: **`storm-re`** (22 tools)
- CLI: `bin/storm-re` (same behavior as the MCP)
- DB: `~/.local/share/storm-re/storm-re.db` (or `STORM_RE_DB` / config file)

## Rule of thumb

Do not start with `decompile_function` or `list_xrefs`. Ask `storm-re` first;
fall back to the raw `ghidra` MCP only when it cannot answer. `storm_explain`
is the one-call default for a single function; `storm_batch` handles several
read-only questions at once.

Native MCP extras: resources for full reports/code (`storm-re://builds`,
`storm-re://topic/{topic}`, `storm-re://function/{build}/{rva}`), prompts for
rollback/story/clean-vs-mod workflows, and stdio progress/cancellation.

```text
resolve → show / symbolize → state_surface / write_sites → decomp → diff
```

## Tool selection

| Need | MCP tool | CLI | Cost |
|---|---|---|---|
| What is this VA/RVA/name? | `storm_resolve` | `resolve` | local, no Ghidra |
| Read a hot function now | `storm_show` | `show` | local SQLite |
| Readable decompile | `storm_symbolize` | `symbolize` | cache/one decompile |
| Callers/callees/data refs | `storm_xrefs` | `xrefs` | cache/one decompile |
| Bounded decompile summary | `storm_decomp` | `decomp` | cache-first |
| Compare two builds | `storm_diff` | `diff --map` | 2 decompiles |
| Find the counterpart RVA | `storm_map` | `map` | local BSim edges |
| Rollback field manifest | `storm_state_surface` | `state_surface` | N seeds, cache-first |
| Who writes this field? | `storm_write_sites` | `write_sites` | N seeds or xrefs |
| Input chain map | `storm_input_path` | `input_path` | 3+ decompiles |
| Timer/frame scan | `storm_frame_tick` | `frame_tick` | N seeds, cache-first |
| Steam/net surface | `storm_net_session` | `net_session` | N seeds + imports |
| Explain one function | `storm_explain` | `explain` | resolve+decomp+symbolize+maps |
| Batch read-only calls | `storm_batch` | — | up to 10 tools |
| Story dispatch | `storm_scene_dispatch` | `scene_dispatch` | N seeds |
| Batch build diff | `storm_patch_diff` | `patch_diff` | 2N decompiles |
| Markdown report | `storm_export` | `export` | SQLite + cached maps |
| Symbol search | `storm_find` | `find` | local (symbol mode) |
| Builds and shas | `storm_builds` | `builds` | local |
| Cache/BSim/index stats | `storm_stat` | `stat` | local |
| Find extracted CPK files | `storm_asset_find` | `asset_find` | local SQLite |
| One CPK file + xfbin chunks | `storm_asset_info` | `asset_info` | local file read |

Asset tools search your extracted tree at `<assets_root>/<game>/<cpk dir>/<cpk name>/<entry>`
(games `storm1 storm2 storm3hd storm3fb stormrev storm4 stormgen`, build aliases
like `s2` work); results carry `path` and, when `assets_win_root` is set, `win_path`.
Empty query = per-CPK overview. Re-index with `storm-re asset_index` after re-extracting.

`resolve`, `show`, `stat`, `builds`, symbol `find`, and cached `symbolize`/
`state_surface`/`write_sites` work with **Ghidra down**. `decomp`/`xrefs` need
the backend only on a cache miss.

## Canonical workflows

### Identify and read a function

```text
storm_resolve  ccPlayer::ChangeAction           build=s4
storm_show     input                            # if it is in the hot set
storm_symbolize ccPlayer::ChangeAction          # readable code
storm_decomp   ccPlayer::ChangeAction detail=sig
storm_xrefs    ccPlayer::ChangeAction direction=to limit=40
```

Use a **full name** (`ccPlayer::ChangeAction`). A short name like `ChangeAction`
is ambiguous (three classes) and returns exit 2 with candidates.

### Cross-build work (1.09 ↔ 1.06 ↔ 1.07)

```text
storm_map  ccPlayer::ChangeAction from=s4 to=s4-debug
storm_diff ccPlayer::ChangeAction from=s4 to=s4-debug --map
```

`map` prefers an exact same-name symbol, then a direct BSim edge, then a
Trilogy-mediated edge, then the same RVA. Always report `method`, `score` and
`confidence`. A 1.06 name can be a false positive; the BSim edge is the check.

### Rollback state surface

```text
storm_state_surface ccPlayer limit=20
storm_write_sites   ccPlayer offset=0xCC0 limit=20
storm_write_sites   ccPlayer offset=0xC8C include_reads=true
```

Known anchors from `docs/reference/storm4-1.09.md`: `+0xCC0` current action, `+0xCC4`
previous action, `+0xC8C` char id, `+0x218` pad/struct. Static results are
`inferred`; confirm with a replay `trace`/`snap` or an in-game probe before
calling a field `CONFIRMED`.

### Address xrefs (data or code)

```text
storm_write_sites 0x1416663c8 include_reads=true limit=50
```

This calls Ghidra `list_xrefs`; a data address can have thousands of refs, so
use `limit` and `include_reads` deliberately. Default is writes only.

### Input, frame and net

```text
storm_input_path  build=s4
storm_frame_tick  build=s4 limit=20
storm_net_session build=s4 limit=20
```

`input_path` returns the three seeds, verified call edges, the two vfunc gates,
button bits and the known chain. It reports **no direct path** when the hop is
indirect; do not invent one.

`frame_tick` flags the `-(3000/fps)` state-timer idiom, the `nuccSys+0x942`
scaling byte, and per-frame `+=`/`*=` constants. All results are heuristic;
confirm with a runtime frame trace.

`net_session` classifies `ccNetFreeBattleSync` functions as send/recv/tick/init/
buffer, lists the Steam imports, and separates game-sync from transport.
Direction is name-inferred; confirm with a net trace.

### Story dispatch, mod diff, reports

```text
storm_scene_dispatch build=s4 limit=15
storm_patch_diff --from s4 --to s4-debug --limit 5
storm_export input --out /tmp/input.md
```

`scene_dispatch` resolves the scene manager, `ccMessageManager::GetMessageParam`,
`Movie::Invoke` and stage-name lookups. Scene ids 0x5300/0x5301 are mod-defined
runtime ids, not exe addresses.

`patch_diff` compares common game symbols across two builds. When both program
files exist it defaults to **byte mode**: function bytes at each RVA are compared,
so call-site patches are found even when decompiled text is similar. Then it
decompiles the changed functions for signature/similarity/callee detail.
`--no-byte-diff` forces text mode.

Clean vs modded NSUNS1:

```text
storm_patch_diff --from s1-clean --to s1 --limit 20
```

`s1-clean` is the clean Steam exe (`a68ea53d…`); its names are inherited from
the modded `s1` import by RVA (medium confidence). Byte mode found 37 changed
functions, including `ccPlayerRpg::CtrlAct_RPG_DASH` call redirects.

`export` writes a markdown report from indexed facts and cached maps. It never
invents prose; missing/error entries are counted as skipped.

### Story / UI work

```text
storm_show    story
storm_symbolize ccMessageManager::GetMessageParam
storm_state_surface ccBattle limit=20
```

Story scene roots and message lookup are in `docs/reference/storm4-1.09.md`; use `resolve`
before reading a decompile, and `symbolize` before quoting code.

## Build aliases

`s4` (1.09), `s4-debug` (1.06), `s4-107`, `s3`/`s3hd`, `s3fb`, `s2`, `s1`
(modded), `s1-clean` (clean Steam exe, names inherited from `s1` by RVA),
`s1-debug`, `connections`, `revolution`, `trilogy` (Switch arm64).

Limits: `s4-107` has only the manual names and no BSim export; the 1.06 BSim
export is partial; `trilogy` is name/BSim target only, not a PC runtime.

## Output contract

Every non-trivial answer carries `build`, `program`/`sha256`, `rva`, `va`,
`name`, `confidence` and `source`. Report those with the result. If a command
fails, do not guess: `code 2` is not found/ambiguous, `3` is backend, `4` is a
missing diff target.

## Traps

- Pointer arithmetic is scaled: `param_1[0x198]` with `longlong*` is byte
  `0xCC0`; `(longlong)param_1 + 0xcc4` is `0xCC4`. `state_surface` handles this;
  do not hand-convert.
- The same RVA in two builds is not the same function. Use `map`/`diff --map`.
- `diff` compares decompiled text, so renamed locals lower similarity.
- `DAT_` names are sparse; `symbolize` will leave most data globals unchanged.
- A nucc name can be wrong despite `high`; the mapping exposes source and
  confidence, so challenge it.
- `find --mode code --semantic` is untested; symbol search is the useful path.

## Reporting

Put addresses and names in backticks. Mark claims `CONFIRMED`, `REJECTED` or
`UNPROVEN`; static analysis is `inferred`. Include the build and SHA prefix so a
wrong-build result is visible.
