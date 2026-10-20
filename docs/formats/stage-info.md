# StageInfo (stages)

## File

| Item | Value |
|---|---|
| Path | `data_win32/stage/WIN64/StageInfo.bin.xfbin` |
| Payload version | 1010 |
| Entry size | 0x130 |
| Object record size | 0xB0 |
| Near-area record | 0x10 bytes (from the 010 template only) [L] |

Version, entry size and object size were established on Storm 4 [V]; the
eliteace170 template `stageinfoS4.bt` agrees and adds the 0x10-byte near-area
record. A field-level layout of the 0x130 entry is not recorded in these notes;
use the template as a starting point and check fields against a file.

## Stage ids and names

- battleParam references stages by string id (`STAGE_...`, see
  [battle-param.md](battle-param.md)).
- Display names are message ids `c_sta_NN`, resolved through the message lookup
  at VA 0x140AB93D0 using message field +8 [V].

## Runtime globals (Storm 4 1.09) [C]

| What | Address |
|---|---|
| current stage id (`stageOffset`) | VA 0x141611A88 |
| `ccAdvPlayStageBgm` global (`bgmOffset`) | VA 0x141610160 (also the sound manager pointer, see [audio.md](audio.md)) |
| BGM table | off 0x1527EA0 (VA 0x141528AA0) |
| stage-change handler / default / specific | off 0x721944 / 0x5E50EC / 0x5E5110 |

Related class headers (`ccStageInfoManager`, `CustomStageSelect`) are in
zealottormunds/ns4_frameworkeditor; the exe build they target is not
verified [L].

## Sources

| Source | Used for | Checked |
|---|---|---|
| eliteace170/XFBIN-010-Editor-Binary-Templates-Master (`stageinfoS4.bt`; its comments cite 1.07 IDA addresses) | entry / object sizes, near-area record | sizes and version agree with our own reading; near-area record not checked |
| TheLeonX/NSUNS4-Toolbox | file path | no |
| TheLeonX/UltimateStormAPI | stage / BGM globals and handlers | no |
| zealottormunds/ns4_frameworkeditor | class headers | no |
