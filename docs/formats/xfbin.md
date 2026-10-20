# xfbin (NUCC container)

`.xfbin` is the CyberConnect2 NUCC chunk container used by Storm 4,
Connections and ASBR (same container; see [cross-game.md](cross-game.md)).
Models, textures, animations and every param table are xfbin chunks.

**The container is big-endian.** `nuccChunkBinary` payloads on PC are
little-endian (see [Param files](#param-files-one-nuccchunkbinary)).

The reader in this repo is `storm_re.assets.parse_xfbin`; this page and that
function agree on every field the function reads.

## Header (0x1C bytes)

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| 0x00 | 4 | char[4] | magic | `NUCC`. `CPK ` here = file still CPK-compressed |
| 0x04 | 4 | u32 | nucc id / version | `0x79`. `parse_xfbin` returns this as `version` |
| 0x08 | 8 | u8[8] | padding | zero |
| 0x10 | 4 | u32 | chunk table size | excludes the chunk-reference block |
| 0x14 | 4 | u32 | min page size | the xfbin_lib writer uses 3 |
| 0x18 | 2 | u16 | nucc id | `0x79` |
| 0x1A | 2 | u16 | — | 0 |

Header example: `4E 55 43 43 00 00 00 79` (`NUCC`, id 0x79).

## Chunk table (starts at 0x1C)

### Counts (0x1C..0x44)

| Off | Size | Type | Name |
|---|---|---|---|
| 0x1C | 4 | u32 | typeCount |
| 0x20 | 4 | u32 | typeSize (bytes of the type string block) |
| 0x24 | 4 | u32 | pathCount |
| 0x28 | 4 | u32 | pathSize |
| 0x2C | 4 | u32 | nameCount |
| 0x30 | 4 | u32 | nameSize |
| 0x34 | 4 | u32 | mapCount |
| 0x38 | 4 | u32 | mapSize |
| 0x3C | 4 | u32 | mapIndicesCount |
| 0x40 | 4 | u32 | referencesCount |

### Variable part (from 0x44, in order)

| Block | Layout |
|---|---|
| type strings | `typeSize` bytes, `typeCount` NUL-terminated strings (chunk class names) |
| path strings | `pathSize` bytes, `pathCount` strings (inner file paths) |
| name strings | `nameSize` bytes, `nameCount` strings (chunk names) |
| align | pad to 4 bytes |
| chunk map | `mapCount × {u32 typeIdx, u32 pathIdx, u32 nameIdx}` (12 bytes each) |
| references | `referencesCount × {u32 nameIdx, u32 mapIdx}` |
| map indices | `mapIndicesCount × u32`: global map index for each page-local slot |

String encoding: xfbin_lib reads the string blocks as cp932; `parse_xfbin`
decodes UTF-8 with replacement. The two agree for the ASCII names seen in
practice.

`parse_xfbin` reads the counts, the three string blocks and the chunk map, and
drops `nuccChunkNull` entries from its result. It does not read the reference
or map-index blocks.

## Pages and chunks

After the chunk table comes a stream of chunks:

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| +0x00 | 4 | u32 | size | data size |
| +0x04 | 4 | u32 | pageLocalMapIndex | index into the current page's window of `mapIndices` |
| +0x08 | 2 | u16 | nucc id | `0x79` |
| +0x0A | 2 | u16 | — | 0 |
| +0x0C | size | u8[] | data | |

- Chunks are grouped into **pages**. A page ends with a `nuccChunkPage` whose
  data is `{u32 pageSize, u32 referenceSize}`; it advances the page-local index
  window into `mapIndices`.
- The first page starts with a `nuccChunkNull` (the xfbin_lib writer always
  emits one).
- `nuccChunkIndex` is a virtual map entry; it is never written as a chunk.

### Known chunk types

`nuccChunkNull, Page, Index, Binary, Texture (.nut / NTP3), Model (.nud /
NDP3), Clump, Coord, Material, Anm, AnmStrm, Camera, Dynamics, Particle,
Sprite, Sprite2, Font, Billboard, Trail, LightDirc, LightPoint, LightSet,
Ambient, MorphPrimitive, LayerSet, ...` [C]

- `nuccChunkTexture` wraps a NUT (`NTP3`) texture with DDS payloads [C].
- `nuccChunkModelPrimitiveBatch`: one 010 template gives a 0x1C-byte header up
  to chunk version 0x76 and 0x20 bytes after [L].

## Param files: one `nuccChunkBinary`

A param table is an xfbin holding one `nuccChunkBinary`. Its data is
`{u32 BE payloadSize, payload}`; the payload is little-endian.

### Worked example: the 300-byte header NSUNS4-Toolbox writes for battleParam [C]

| Item | Value |
|---|---|
| types | `nuccChunkNull, nuccChunkBinary, nuccChunkPage, nuccChunkIndex` |
| paths | `""`, `"bin_le/x64/battleParam.bin"` |
| names | `""`, `"battleParam"`, `"Page0"`, `"index"` |
| 0xF4, 0x100 | two null chunks (12-byte headers, size 0) |
| 0x10C | Binary chunk header (`size`, `mapIdx = 1`, `0x79`) |
| 0x118 | BE u32 payload size |
| 0x11C | payload start |

### Standard payload header (LE)

| Payload off | File off (example) | Size | Type | Name | Notes |
|---|---|---|---|---|---|
| 0x00 | 0x11C | 4 | u32 | version | per-table constant, e.g. battleParam 0x3F0 = 1008 |
| 0x04 | 0x120 | 4 | u32 | entryCount | |
| 0x08 | 0x124 | 8 | relptr | entries | = 8 → entries start right after, file 0x12C |

The same 0x120 / 0x12C shape is used by messageInfo [C]. The game checks a
per-table version constant; exe strings name them, e.g.
`CCD_ADV_BATTLE_PARAM_VERSION`, `CCD_RELIVE_STORY_EPISODE_PARAM_VERSION` [C].

## Runtime (Storm 4 1.09, VA) [C][L]

From the StormRevival client source, not re-checked:

| What | VA |
|---|---|
| find loaded xfbin by path | 0x140A03D30 |
| row lookup by hashed key | 0x140A139F0 |
| load table payload | 0x140AAFB10 |
| hash string | 0x140A01EB0 |

## Sources

| Source | Used for | Checked |
|---|---|---|
| SutandoTsukai181/xfbin_lib (now mosamadeeb/xfbin_lib) | header, chunk table, page/chunk layout | yes: `parse_xfbin` implements the header + table independently and reads Storm 4 1.09 files |
| TheLeonX/XFBIN_LIB, TheLeonX/XFBIN_PARSER | chunk-type list (C# port of xfbin_lib) | not re-checked |
| TheLeonX/NSUNS4-Toolbox | param header worked example | example decoded by hand; consistent with the container layout |
| eliteace170/XFBIN-010-Editor-Binary-Templates-Master | ModelPrimitiveBatch header lead | no |
| StormRevival client source (community) | resource API addresses, version-constant strings | no |
