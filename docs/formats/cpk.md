# CPK archives

Storm-engine games ship their data in CRI Middleware CPK archives (CriFs).
This page covers what is Storm-specific: the CC2 encryption layer, the Storm 4
boot mount order, mod CPKs, and the extracted-tree layout `storm-re` indexes.
The generic CPK container (CRI's own table format) is not re-documented here;
use a CRI-aware extractor.

## Magic

| Off | Size | Value |
|---|---|---|
| 0x00 | 4 | `CPK ` (`43 50 4B 20`) |

A file that should be an xfbin but starts with `CPK ` is still CPK-compressed
(see [xfbin.md](xfbin.md#header-0x1c-bytes)).

## CC2 encryption

CyberConnect2 CPKs on PC are encrypted with an **xorshift-generated keystream**
XORed over the data [V]. Decryption = generate the same keystream and XOR again
(the operation is its own inverse). The reference description is the public
QuickBMS script `CC2_CPK_Decrypter.bms`; a clean-room Python port of the same
algorithm was used for this research. The generator constants are not recorded
in these notes; take them from that script.

Do not run bundled third-party executables to decrypt; the algorithm is small
enough to reimplement.

## Storm 4 1.09 boot mount order

From ns4moddingapi's re-implementation of the game's boot CPK routine [C]:

| Order | Mount path |
|---|---|
| 1 | `sim:data/patch/12/launch.cpk` (patch) |
| 2 | `sim:data/launch/data1.cpk` |
| 3 | `stage1.cpk` |
| 4 | `sound.cpk` |
| 5 | `disc:data/launch/dataRegion.cpk` |
| 6 | `adx2.cpk` |
| 7 | `movie1.cpk` |
| 8 | `disc:data/launch/<lang>/dataRegion.cpk`, chosen by region id |

Region id → language folder: 2 fre, 3 / 0x13 spa, 4 ger, 5 ita, 8 rus, 9 kokr,
0xA chi, 0x10 por, 0x12 pol, 0x14 arae.

Further archive names present as exe strings: `data2.cpk`, `stage2.cpk`,
`movie2.cpk`, `movie3.cpk`, `dlcpackdata.cpk`, and the format
`sim:data/patch/%d/%s.cpk` [C]. `data/patch/12/` holds `data.cpk`,
`launch.cpk`, `sound.cpk` [C].

Patch CPKs override files by internal path across archives (a replacement
`data/movie/*.usm` inside a rebuilt `patch/12/*.cpk` takes effect) [C].

### Runtime entry points (1.09, "off" convention, VA = off + 0x140000C00) [C]

| What | off |
|---|---|
| Game boot CPK routine (hooked by ns4moddingapi, 15-byte hook) | 0x854F3C |
| `MountCpk(cpkdata* {const char* path; int priority})` | 0x56B74C |
| `MountCpkWithPriority(cpkdata*, int)` | 0x56B7D4 |
| Region id | `*(qword at VA 0x1416663C8) + 0x1D4` |

## Mod CPKs (community mod loaders)

| Item | Format | Source |
|---|---|---|
| `moddingapi/mods/<mod>/<any>.cpk` + `<any>.cpk.info` | `.info` = 4 bytes, byte 0 = mount priority; default 0x0D | ns4moddingapi wiki [C] |
| `moddingapi/mods/base_game/modmanager_assets.cpk` | priority 0x20 | NSUNS4-ModManager [C] |
| `data_win32_modmanager.cpk` | priority 0x21 | NSUNS4-ModManager [C] |
| `.ns4p` | raw byte patch; file name = exe "off" in hex | ns4moddingapi wiki [C] |
| `.ns4e` | script patch | ns4moddingapi wiki [C] |
| `info.txt` | conflict: ns4moddingapi wiki = one line `Name\|Description\|Author`; UltimateStormAPI reads 4 separate lines (name, desc, author, state). A file valid for both needs checking | [C] |

UltimateStormAPI does not load CPKs or `.ns4s` files (no CPK code in its tree);
those come from ns4moddingapi [C]. Whether the two are normally installed
together is inferred, not verified [L].

A loose-file alternative exists in the StormRevival client source: hooks on
`CreateFileA/W` and `FindFirstFile` redirect `.cpk .xfbin .usm .acb .awb .lua
.swf` opens [C].

## Path conventions inside Storm 4 archives

Game-side paths use `PLAT`; on disk the PC tree uses `data_win32/.../WIN64/`.
Example: game path `data/rpg/PLAT/battleParam.xfbin` → on disk
`data_win32/rpg/WIN64/battleParam.xfbin` [C]. UI `.gfx` files are loose in
`data/ui/flash/OTHER`, not inside CPKs [V].

## Extracted tree layout (storm-re `assets_root`)

`storm-re asset index` expects archives already extracted:

```
<root>/CPKS.tsv                              game<TAB>cpk rows (lines starting with # or "game\t" are skipped)
<root>/<game>/<cpk dir>/<cpk name>/<entry>   extracted archive members
<root>/<game>/<other path>                   loose disc files (no owning CPK)
```

- The `cpk` column is the archive path relative to `<root>/<game>/`, with or
  without the `.cpk` suffix. Longest prefix wins when archives nest.
- Each indexed file records `game, rel, cpk, entry, ext, size, magic`; `magic`
  is the first 4 bytes as ASCII when printable, else hex.
- Files ending in `.tmp` or under a `.tmp/` directory are skipped.
- Files with magic `NUCC` get their chunk table parsed (see [xfbin.md](xfbin.md)).

## Sources

| Source | Used for | Checked |
|---|---|---|
| `CC2_CPK_Decrypter.bms` (QuickBMS script, community) | encryption algorithm | algorithm reimplemented and used on Storm CPKs |
| zealottormunds/ns4moddingapi (+ wiki) | mount order, region ids, mount functions, `.cpk.info`, `.ns4p`, `.ns4e` | not re-checked |
| TheLeonX/NSUNS4-ModManager | mod CPK names and priorities | not re-checked |
| TheLeonX/UltimateStormAPI | `info.txt` format, absence of CPK loading | not re-checked |
| StormRevival client source (community) | loose-file redirect | not re-checked |
| Steam community guide on cutscene replacement | patch CPK override by internal path | not re-checked |
