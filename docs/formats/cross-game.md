# Cross-game notes (shared CC2 engine)

The Storm series and CyberConnect2's later fighting games share one engine
(class prefix `cc`, `nucc` runtime, xfbin assets). Container formats carry
over; individual param tables drift.

## What is shared

| Layer | Shared by | Notes |
|---|---|---|
| xfbin container + chunk formats | Storm 4, Connections, ASBR | same header, chunk table, pages ([xfbin.md](xfbin.md)) |
| Param table conventions | Storm 4, Connections | LE payloads, u64 relptrs, version + count + relptr header |
| Param layouts across Storm 4 builds | 1.07 = 1.09 | exe addresses differ; data does not |
| CRI ADX2 function behaviour | Storm 4, Connections | struct offsets differ (Storm 4 SDK 2.08.07, Connections much newer) ([audio.md](audio.md)) |
| Input front end code | Storm 4 debug 1.06, 1.07, 1.09 | identical code (XInput poll, edges, raw input, pad Ctrl / PreCtrl / CommandFunc, limiter) |
| Render-thread GPU timestamp `GetData` spin | Storm 1, 2, 3 HD, 4, Connections | not in Full Burst |

Community tools for Connections (maxcabd/nuccbin, cosprm, accprm,
message-info-localizer; IklilIlm/XfbinSoundTool; TheLeonX NSC-* tools) and ASBR
(KojoBailey's tools, `nucc-binary-asbr-lib-rs`, `xfbin-lib-rs`) are therefore
good leads for container work. Check every individual table against a file from
the target game.

## Table drift examples

| Table | Storm 4 | Other game |
|---|---|---|
| messageInfo entry | 40 bytes, 2 text relptrs, ACB index / cue at +0x1E / +0x20 | Connections: 48 bytes, 3 text relptrs ([message-info.md](message-info.md)) |
| resultGradeParam record | Storm 3 layout, 0x30 bytes (free battle only) | Revolution: version 1002, 0x24 bytes, different field order ([story-tables.md](story-tables.md#resultgradeparam-money-ledger--rank-thresholds)) |
| battleParam | +0x00 battle id relptr, +0x08 description | Generations: +0x04 battle name |
| Ex-player struct (CRI) | source type at +0xC8, args +0xD0 / +0xD8 | Connections: +0x100 / +0x108 / +0x110 |
| `nuccChunkModelPrimitiveBatch` header | — | 0x1C bytes up to chunk version 0x76, 0x20 after (template lead) [L] |
| Movie playback | string-argument lead only [L] | Connections: `PlayMovieById(u32)` |

## Executable facts per game

### Linked libraries [V]

| Game | Libraries |
|---|---|
| Storm 1 | Bullet; statically linked dlmalloc |
| Storm 2, Storm 3 | Lua + tolua, Bullet |
| Full Burst, Revolution, Generations | Lua + tolua |
| Storm 4 | Lua + tolua, Bullet, zlib 1.2.7, curl 7.29.0 |
| Connections | all of the above; zlib 1.2.7 and 1.2.11, curl 7.50.1 |

Storm 4 Steam interfaces: SteamUser016, SteamFriends013, SteamMatchMaking009,
SteamNetworking005, SteamUserStats011; Storm 1-3 match them [V].

Connections has 6002 RTTI classes [V].

### Symbols

The Switch *Storm Trilogy* build ships full C++ symbols (~123k functions;
namespaces `ns1::` / `ns2::` / `ns3::` = Storm 1 / 2 / 3 Full Burst). It is the
main source for naming the stripped PC builds. Names transferred to the PC exes
(BSim, string anchors, call-graph propagation, RTTI / vtables, chained PC ↔ PC)
are published as a
[community symbol set](https://github.com/exavadw/naruto-storm-symbols)
(v1.2.0, ~141.6k names; Ghidra, IDA, PDB and x64dbg outputs). Approximate
coverage (2026-10): Storm 1 52 %, Storm 2 50 %, Storm 3 HD 52 %, Full Burst
35 %, Storm 4 release 23 %, Storm 4 debug 21 %, Revolution 28 %, Connections
15 %.

### Storm 4 1.07 → 1.09 [V]

Enum renumbering, new DLC character ids (0xE1 / 0xE3 / 0xE4), a few 30/fps
fixes (e.g. the substitution gauge in CtrlCounter), Thai language, EULA screen.

### Storm 4 frame timing [V]

The 30/fps scaling already exists in debug 1.06. See the
[reference](../reference/storm4-1.09.md#frame--timing-v).

## Rank and result systems

Each game grades battles differently (points, money ledger, factor average);
summary in [story-tables.md](story-tables.md#rank-models-by-game).

## Sources

| Source | Used for | Checked |
|---|---|---|
| PC exes of Storm 1, 2, 3 HD, Full Burst, 4 (1.06 debug, 1.07, 1.09), Revolution, Connections; Switch Trilogy | libraries, interfaces, input code, symbols | [V] |
| maxcabd/nuccbin | Connections messageInfo layout | no |
| eliteace170/XFBIN-010-Editor-Binary-Templates-Master | MPB header lead | no |
| KojoBailey ASBR crates, IklilIlm/XfbinSoundTool, TheLeonX NSC-* | same-engine leads | no |
