# messageInfo (localized text)

Every UI and dialogue string is looked up by a message id. The id string is not
stored in the file; entries are keyed by its CRC32. An entry can also carry a
voice cue, so voiced subtitle lines are a native concept.

## File

| Item | Value |
|---|---|
| Path | `data_win32/message/WIN64/<lang>/messageInfo.bin.xfbin` |
| Languages (folder names, 13) | `arae chi eng esmx fre ger ita kokr pol por rus spa jpn` |
| Header | standard param header ([xfbin.md](xfbin.md#standard-payload-header-le)): count at file 0x120, entries at 0x12C |

## Entry: Storm 4 (40 bytes, LE) [C]

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| 0x00 | 4 | u32 | crc32 | CRC32 of the message id string |
| 0x08 | 8 | relptr → str | extraText | |
| 0x10 | 8 | relptr → str | mainText | |
| 0x1E | 2 | u16 | acbIndex | voice bank index; 0xFFFF = none |
| 0x20 | 2 | u16 | cueId | cue within that bank |
| 0x22 | 2 | u16 | voiceOnly | |

(Offsets 0x1E / 0x20 / 0x22 = decimal +30 / +32 / +34.)

Known `acbIndex` values [C]: 0x01 `v_win.acb`, 0x0A `v_ougiFinish.acb`,
0x0B `v_matching.acb`. The full bank list is in [audio.md](audio.md#banks).

Stage names (`c_sta_NN`) are read through the message field at +8 by the
lookup at VA 0x140AB93D0 [V].

### Connections differs

nuccbin's Connections messageInfo has **48-byte** entries with **3** text
pointers. Storm 4 has 40-byte entries with 2 text pointers and ACB / cue at
+0x1E / +0x20. Check every table against a file from the target game. See
[cross-game.md](cross-game.md).

## Id hash

| Parameter | Value |
|---|---|
| Algorithm | CRC-32/BZIP2 |
| Poly | 0x04C11DB7, MSB-first (non-reflected) |
| Init | 0xFFFFFFFF |
| Xorout | 0xFFFFFFFF |
| Storage | little-endian u32 |

NSUNS4-Toolbox and UltimateStormAPI implement the same hash [C]. The game's own
lookup hashes the id at runtime (see below).

## Markup

Strings can contain inline tags, e.g. `<icon btn_2 />`, `<color red>`,
`<ruby>` [C].

## Runtime lookup (Storm 4 1.09)

| Function | Address | Source |
|---|---|---|
| `MsgToString(const char* msgId) -> const char*` | off 0xAB8720 (VA 0x140AB9320) | UltimateStormAPI, ns4moddingapi [C]. Release hook length 19 bytes, debug 14 |
| alternate variant | off 0xAB87D0 (VA 0x140AB93D0) | same [C]; this is the stage-name lookup above [V] |
| message lookup | VA 0x140ABD020 (FUN_140ABD020) | own reading [V] |

The relation between `MsgToString` at VA 0x140AB9320 and FUN_140ABD020 is not
recorded; treat them as separate entry points until checked [L].

## Overrides without editing messageInfo

- ns4moddingapi `.ns4s`: a mod file of `id\0text\0` pairs that adds or replaces
  ids [C].
- ns4moddingapi's `MsgToString` hook returns an id prefixed with `+` literally,
  which lets raw text be shown without a table entry [C].

## Sources

| Source | Used for | Checked |
|---|---|---|
| TheLeonX/NSUNS4-Toolbox, messageInfo editor + CRC code + ACB list | entry layout, languages, CRC parameters, ACB indices | not re-checked against a file |
| TheLeonX/UltimateStormAPI | CRC implementation, `MsgToString` address | no |
| zealottormunds/ns4moddingapi (+ wiki) | `MsgToString` address, `.ns4s`, `+` prefix | no |
| maxcabd/nuccbin, maxcabd/message-info-localizer | Connections 48-byte layout | no |
| Storm 4 1.09 exe | stage-name lookup, FUN_140ABD020 | [V] |
