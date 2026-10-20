# Storm-engine file formats

Format notes for the PC builds of CyberConnect2's Storm-engine fighting games.
Byte layouts and algorithm descriptions only: no game data, no extracted text,
no third-party code.

## Index

| File | Covers |
|---|---|
| [cpk.md](cpk.md) | CRI CPK archives, CC2 encryption (algorithm), boot mount order, mod CPKs, the extracted-tree layout `storm-re` indexes |
| [xfbin.md](xfbin.md) | `NUCC` container: header, chunk table, pages, chunks, the `nuccChunkBinary` param-file convention |
| [battle-param.md](battle-param.md) | `battleParam` (story battles): entry, player/enemy blocks, reward block, condition vocabulary |
| [message-info.md](message-info.md) | `messageInfo` (localized text + voice cue), CRC32 id hashing, markup, `.ns4s` overrides |
| [stage-info.md](stage-info.md) | `StageInfo`, stage name lookup, stage/BGM globals |
| [cpu-param.md](cpu-param.md) | `cpuparam` (versus AI): chunks, level scripts |
| [story-tables.md](story-tables.md) | episode tables, boss/adventure/group-battle files, `resultGradeParam`, per-game rank models |
| [audio.md](audio.md) | CRI ADX2 (ACB/AWB/ACF), ADX/HCA, NUS3 (`nus3bank`), USM video, Storm 4 1.09 CRI runtime |
| [ui.md](ui.md) | Scaleform `.gfx`/`.swf` UI, invoke bridge, known movies |
| [cross-game.md](cross-game.md) | shared engine across titles, per-table drift, linked libraries |
| [../reference/storm4-1.09.md](../reference/storm4-1.09.md) | build table, Storm 4 1.09 addresses, struct offsets, button bits, action ids |

## Game names

Storm 1, Storm 2, Storm 3, Storm 3 Full Burst (2014, 32-bit), Storm 3 HD (Full
Burst HD, 2017, 64-bit), Storm Revolution, Storm 4, Storm Connections, and
Generations (Xbox 360 only). "Storm 4 1.09" = the latest Steam build of Storm 4
(Steam AppID 349040), exe version string `"1.09"`. Build identification (file
name + SHA-256 prefix) is in the [reference build table](../reference/storm4-1.09.md#builds).

## Conventions

### Endianness

| Data | Endianness |
|---|---|
| xfbin container (header, chunk table, chunk headers, the `nuccChunkBinary` size word) | big-endian |
| `nuccChunkBinary` payloads on PC (param tables) | little-endian (inner path prefix `bin_le/x64/` says so) |
| Executables | x86-64 little-endian (Storm 3 Full Burst: x86 32-bit) |

### Pointers inside param payloads

Every Storm 4 param table uses **u64 self-relative offsets** ("relptr"):
`target = address_of_field + value`. A zero relptr means null. Strings are
inline NUL-terminated ASCII placed after the fixed-size arrays.

### Addresses

| Term | Meaning |
|---|---|
| Image base | `0x140000000` for every x86-64 PC exe listed here |
| VA | virtual address in that base (what Ghidra/IDA show), e.g. `0x1407AB468` |
| RVA | `VA − 0x140000000`, e.g. `0x7AB468`. Name CSVs and `storm-re` use RVA |
| "off" (community mod APIs) | `VA − 0x140000C00`. UltimateStormAPI and ns4moddingapi compute `moduleBase = exeBase + 0xC00` and add this value; `.ns4p` patch file names use the same numbers. Convert: `VA = off + 0x140000C00` |

Some community trees (StormRevival "set B" tables) use plain VA instead of
"off". Check which convention a source uses before copying a number.

### Version scope

All Storm 4 addresses target **1.09** unless stated. Data layouts (xfbin and
param tables) are the same in 1.07 and 1.09; exe addresses differ between
builds and must be re-found per build. Storm 4 1.06 (debug), 1.07 and 1.09 share
the input front end code but not its addresses.

### Evidence tags

Every non-obvious claim carries one tag:

| Tag | Meaning |
|---|---|
| **[V]** | verified: read in the executable's code (VA given), read in a game data file, or observed in a running game, on the build named |
| **[C]** | community-sourced: taken from a public tool or template (credited in the file's Sources section) and not re-checked here |
| **[L]** | lead / unverified: plausible, single source or partial evidence; confirm before relying on it |

Where two sources disagree, both values are given and the conflict is named.

### Builds each table was checked on

| Table / format | Checked on | Notes |
|---|---|---|
| xfbin container | Storm 4 1.09 files (parser in `storm_re.assets.parse_xfbin`) | container shared by Storm 4 / Connections / ASBR |
| battleParam | Storm 4 1.09 (reward block and task order read in exe code) | rest of the entry from NSUNS4-Toolbox [C] |
| messageInfo | Storm 4 (layout from NSUNS4-Toolbox) [C]; Connections differs (48-byte entries) | |
| StageInfo | Storm 4 (version 1010, 0x130 entries, 0xB0 objects) | 010 template agrees |
| cpuparam | Storm 4 1.09 | |
| resultGradeParam | Revolution PC data [V]; Storm 3 / Full Burst from code only (values unconfirmed) | |
| CRI audio runtime | Storm 4 1.09 exe (static), cross-checked against Connections | |
| episodeParam / episodeMovieParam | not documented anywhere; layout unknown | |
