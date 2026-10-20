# Storm 4 1.09 reference

Known addresses, struct offsets, button bits and action ids for Storm 4 1.09
(Steam AppID 349040), plus notes on other builds. Conventions and evidence tags
([V] / [C] / [L]) are defined in [../formats/README.md](../formats/README.md).

All addresses are **VA** with image base `0x140000000` unless marked "off".
Community mod-API "off" values convert as `VA = off + 0x140000C00`; both are
given where a community source was the origin.

## Builds

Identify a build by SHA-256, not by file name (several builds share a name).

| Build | File name | SHA-256 prefix | Notes |
|---|---|---|---|
| Storm 1 (Steam) | `NSUNS1.exe` | `a68ea53d` | clean Steam exe |
| Storm 1 (Steam, modded) | `NSUNS1.exe` | `10231093` | community-modded copy: 4 extra sections, ~80 call patches, same RVAs as `a68ea53d` |
| Storm 1 debug | `NSUNS1_debug.exe` | `d209f8d0` | |
| Storm 2 | `NSUNS2.exe` | `69748801` | |
| Storm 3 HD (Full Burst HD, Steam 2017) | `NSUNS3.exe` | `55b726e9` | 64-bit; preferred Storm 3 target |
| Storm 3 Full Burst (2014) | `NS3FB.exe` | `5373bfd6` | 32-bit, D3D9 |
| Storm Revolution (Steam) | `NSUNSR.exe` | not recorded | |
| **Storm 4 1.09** (Steam) | `NSUNS4.exe` | `147e52a3` | linked 2020-06; Steam public build 5376895 (2020-08-06); version string `"1.09"` at VA 0x14139304C, after `dlc/%d` |
| Storm 4 1.07 | `NSUNS4.exe` | `c3582656` | exe dated 2017-01-26 (final content patch, released 2017-02-03 per Steam); added 60 FPS |
| Storm 4 1.06 debug | debug client exe | `8324cc6d` | |
| Storm Connections | `NSUNSC.exe` | `cecf0405` | |

Both community mod APIs hard-target 1.09. UltimateStormAPI detects Connections
1.60 / 1.70 by PE `TimeDateStamp` / `SizeOfImage` and Storm 4 by pattern-scanning
for the version-string function [C].

## Player / input [V]

| What | Address / offset | Notes |
|---|---|---|
| `ccPlayer` character id | `+0xC8C` | |
| `ccPlayer` current action | `+0xCC0` | do not confuse with the id |
| `ccPlayer` previous action | `+0xCC4` | |
| `ccPlayerPad` | `ccPlayer + 0x218` | |
| one-frame press word | `ccPlayerPad + 0x404` | read by battle accessors |
| `ChangeAction` | 0x1407AB468 | RVA 0x7AB468 |
| `ccPlayerLeader::UpdatePadState` | 0x1407E10E0 | runs Ctrl only if IsEnableInput; clears if `player + 0xD50` |
| `CtrlInputPad` | 0x1407E0214 (off 0x7DF614) | → vfunc +0xE88 = FUN_1407AD3F8 (chakra-dash gate), FUN_1407AD12C (cancel frames from data) |

Input front end (XInput poll, edges, raw input, nuccSys update, `ccPlayerPad`
Ctrl / PreCtrl / CommandFunc, limiter) is identical code in debug 1.06, 1.07
and 1.09. Pads are polled once per frame (30.0 / s at 30 FPS); a tap shorter
than one frame is lost by sampling in every build.

### Button bits (`padFrame.on`) [V]

| Button | Bit |
|---|---|
| Back | 0x0001 |
| L3 | 0x0002 |
| R3 | 0x0004 |
| Up | 0x0010 |
| Right | 0x0020 |
| Down | 0x0040 |
| Left | 0x0080 |
| RT (guard) | 0x0200 |
| LB | 0x0400 |
| RB | 0x0800 |
| Y | 0x1000 |
| B | 0x2000 |
| A | 0x4000 |
| X | 0x8000 |

### Character ids [V]

Ids observed in testing: 1, 2, 8, 25, 32, 94 (internal code `3kbt`), 98, 104.
DLC ids 0xE1 / 0xE3 / 0xE4 are new in 1.09. The full id ↔ code table is
`data_win32/spc/characode.bin.xfbin`.

### Action ids (`ccPlayer + 0xCC0`) [V]

| Id | Action |
|---|---|
| 1 | idle |
| 4, 8 | jump |
| 0x10, 0x15 | chakra dash |
| 0x3F | strike |
| 0x43 | shuriken throw |
| 0x49 | guard |
| 0x4A | guard hit |
| 0x4D | ninjutsu |
| 0x84 | chakra charge |

## Combat [V]

| What | Address / offset | Notes |
|---|---|---|
| guard-hit handler | 0x140788B4C | calls `SetAttackResult` from 0x140788BA8 |
| `SetAttackResult(attacker, 3)` | 0x1407824B8 | |
| attack result | `attacker + 0x14054` | cleared on ChangeAction |
| hit id (u16) | `defender + 0xFB7C` | |
| current attack id | `attacker + 0x140A0` | |

Same code in 1.07.

CPU AI: see [cpu-param.md](../formats/cpu-param.md). Possible reaction gate
0x141611F08 [L]; AI countdown `ai + 0x1A58` carries across battles.

## Frame / timing [V]

- FPS setter FUN_140A0C290: fps must divide 60; `+0x4A0` = 60 / fps. The fps
  byte is 30 or 60. The 30 / fps scaling already exists in debug 1.06.
- State-timer idiom (`-(3000 / fps)` init, compare against `N / (30 / fps)`) is
  correct at 60 FPS. Real 60 FPS bugs are per-frame constants (`+= c`, `*= k`,
  ±1), velocity / hit sampling, UI input, substitution.
- `nuccSys + 0x942` = 30 or 60 (not a divisor).
- "Fight" start: 0x1405B8088.
- Menu-settle crash at 0x140A11CB9 if a battle is launched before the mode-select
  background loads.

## Render / perf [V]

- Render-thread GPU timestamp `GetData` spin FUN_14019F400 (wastes about one
  core; same bug in Storm 1, 2, 3 HD, Connections; not in Full Burst).
- `nummSkinningThreadGPU::WaitForEnd` also spins.
- Shadow cascades FUN_140A40150 / FUN_140A40060.
- MSAA 2× costs about half the 1080p frame on an Intel UHD 770 iGPU.

## UI / text

| What | Address | Tag |
|---|---|---|
| Scaleform `Movie::Invoke` (`"path.Method"`) | 0x140871310 | [V] |
| message lookup | FUN_140ABD020 | [V] |
| `MsgToString(msgId)` | 0x140AB9320 (off 0xAB8720) | [C] |
| stage-name lookup (`c_sta_NN`, message field +8); `MsgToString` alternate variant | 0x140AB93D0 (off 0xAB87D0) | [V][C] |

More in [ui.md](../formats/ui.md) and [message-info.md](../formats/message-info.md).

## Round judge and bonus tasks [V]

One object at battle global + 0x170, updated every frame by FUN_14074D248:

| Off | Field |
|---|---|
| +0x3C | bonus tasks[7] `{int type, int param}`, battleParam +0x58 order |
| +0x74 | task count |
| +0x78 | time-limit countdown in ticks (< 0: no limit) |
| +0x80 | int[3] ticks elapsed per round (FUN_14074E240(global) = round index) |
| +0xBC | result: 0 running, 1 draw, 2 P1 wins, 3 P2 wins (copy at +0xC0) |
| +0xC4 | finish bits of the decided round |

- Ticks are 1/60 of a game second: a 60 s limit starts the countdown at 3600.
  A copy running logic at 30 FPS advances one tick per frame.
- Finish bits from the loser's KO kind (`FUN_1407C8CBC(loser, k)`): kind 3 →
  0x2, 4 → 0x4, 5 → 0xC, 6 or 15 → 0x10, 9 → 0x80, 2 → 0x800, 8 → 0x1000, 7 →
  0x20; time up 0x40; 0x1 always. KO kinds match Revolution's finish types (2
  throw, 3 ninjutsu, 4 ultimate, 5 team ultimate, 6 awakening, 9 ring out). A
  plain KO gives 0x1 in game; the ultimate / awakening bits are read from code
  only.
- Task checkers: table 0x1410A4AA0 indexed by task type, called by
  FUN_14074D068. `FUN_14074D0FC(judge, i) != 0` = task i done (the game's own
  post-battle call, FUN_1406C9858).
- Count checkers read the fighter's battle-stat block
  (`FUN_14074E220(global, side, member)`): u16 at +0x16 combo, +0x2A, +0x2C,
  +0x2E, +0x30 (names beyond combo unconfirmed).
- Task type pairs: [battle-param.md](../formats/battle-param.md#runtime-task-types-storm-4-109).

## Story results and save [V]

- Results toast: `result_s.swf`, global DAT_14161C9C0, opened by FUN_1406701E4,
  ranked by `MiniResult::Rank` FUN_14066E0B0, both called from the episode
  battle end scene ctor FUN_1406C8FFC. Rank written to `mini + 0x1FC` (0 S ..
  4 D); `mini + 0x200 = 1` marks a new best on an S-able episode. Algorithm:
  [story-tables.md](../formats/story-tables.md#storm-4-109-v).
- Save slot `idx` = `propReliveStorySaveIdx` (0xC / 0xE / 0x10 map to 0xB / 0xD
  / 0xF); -1 = no slot, every input reads 0.
- Life inputs: FUN_14074B0E4 / FUN_14074B134 on battle global + 0x18.
- In-memory save DAT_14161FEB0 (0x20000 bytes):

| Offset | Content |
|---|---|
| +0x208 + idx × 0x20 | per-battle record (battle index from FUN_14051D1DC) |
| +0xE23C + idx × 7 | per-battle bonus flags |
| +0x1BF84 + idx × 4 | best rank per episode slot |
| +0x1C390 + idx × 0x28 | per-episode result: +0 life max, +4 life, +8 QTE max, +0xC QTE got, +0x10 secret max, +0x14 secret got, +0x18 continues |

- Current / previous rank arrays: DAT_14161CA20[idx] / DAT_14161CE20[idx].
- Episode cleared / opened / new bits: DAT_14163BDD4 / DAT_14163BDF4 /
  DAT_14163BE14.
- Continues: `BossBattleContinueManager + 0x60`.
- Reward table: 0x141612034 (filled by FUN_140517BBC from battleParam +0x30).
  Task line + cut-in FUN_14064348C; save grant FUN_1406C9858 → FUN_14050D260;
  item / money grant with cut-in FUN_140521A68.
- `ccBattleDropItemManager` (built FUN_1404AE278, update FUN_1404AE9D8): as a
  fighter's life passes each tenth it may queue a `COSTUME_MATERIAL_nnn` drop
  (FUN_140516818 → pending list DAT_14161C9D0, later committed to the
  inventory).
- Free-battle money ledger: `ccUiBattleResult` FUN_14072A770.
- Save file on disk: `STORM4.S` in the Steam userdata `remote` folder for app
  349040.

## Sound

Sound manager pointer at 0x141610160 (`*(ccSoundMgr**)`), CRI manager at
`+0xE8`. Full CRI map: [audio.md](../formats/audio.md#storm-4-109-cri-runtime-va-v).

## Community-sourced offsets (UltimateStormAPI / ns4moddingapi) [C]

Taken from the public mod APIs; not re-checked unless noted. Spot checks:
`CtrlInputPad`, the duel camera and the movie lead convert to VAs that match
our own reading.

### Scene manager

| Function | off | VA |
|---|---|---|
| instance pointer (global) | — | `*(0x1416BDA18)` |
| `Push(mgr, u32 scene)` | 0xAB4D20 | 0x140AB5920 |
| `Pop(mgr)` | 0xAB5020 | 0x140AB5C20 |
| `PopAll(mgr)` | 0xAB5410 | 0x140AB6010 |
| `Execute(mgr)` | 0xAB4C10 | 0x140AB5810 |
| `Change(mgr, u32 scene)` | 0xAB54D0 | 0x140AB60D0 |
| `PushPromptly(mgr, u32)` | 0xAB4EA0 | 0x140AB5AA0 |
| `PopTo(mgr, u32)` | 0xAB52C0 | 0x140AB5EC0 |
| `SearchSceneRank(mgr, u32)` | 0xAB5B00 | 0x140AB6700 |
| `EntryCreateSceneCommand(mgr, int, __int64)` | 0xAB57D0 | 0x140AB63D0 |
| `EntryCreateSceneCommandJump(mgr, name, num, addr)` | 0x6E436C | 0x1406E4F6C |
| `GetCurrentSceneKey(mgr)` | 0xAB5A70 | 0x140AB6670 |

Scene factory table: `SceneEntry {u32 id; u8 pad[4]; u64 startFn; char
name[0x80];}`, 0x90 bytes, terminated by id -1. Storm 4 table at off 0x14F9300
(VA 0x1414F9F00); scene count patched at off 0x6E43D2 (VA 0x1406E4FD2).

### Battle

| What | off | VA |
|---|---|---|
| `ccSceneBattleRootBase` property setup | 0x6D6908 | 0x1406D7508 |
| `ccSceneFreeBattle::Initialize` | 0x6D8144 | 0x1406D8D44 |
| `ccSceneFreeBattle::Finalize` | 0x6D7954 | 0x1406D8554 |
| scene-name symbol cut | 0x5996C0 | 0x14059A2C0 |
| `ccGameProperty::SetProperty(mgr, int* idx, const char* name, void* val)`; mgr = `((__int64*)0x1416BDA20)[1]` | 0x46FDD0 | 0x1404709D0 |
| stage-change handler | 0x721944 | 0x140722544 |
| stage-change default / specific | 0x5E50EC / 0x5E5110 | 0x1405E5CEC / 0x1405E5D10 |
| `CtrlInputPad` | 0x7DF614 | 0x1407E0214 |
| skip opening movie (int32 patch → 0x63) | 0x862D62 | 0x140863962 |
| title idle before opening (int16 → 0xFFFF) | 0x71B4B2 | 0x14071C0B2 |
| gauge init / set rate | 0x63FE2C / 0x640E90 | 0x140640A2C / 0x140641A90 |
| `SpecialCondParam::Create` | 0x7C5334 | 0x1407C5F34 |
| condition (status effect) add | 0x7F4450 | 0x1407F5050 |
| `ccCameraOperatorDuel::Ctrl` | 0x743F3C | 0x140744B3C |
| memory pool sizes (App / UI / Param / Texture / Stage / Player / Sound) | near 0x563F98 | near 0x140564B98 |

Free-battle scene allocation sizes (0x4F8 → 0x1BF8 in UltimateStormAPI) are
patched at off 0x6DCBDF, 0x6DD7BF, 0x6DD17F, 0x6DE39F, 0x6DDDAF, 0x6E13CB,
0x6E335B, 0x6E191B, 0x6E1FFB, 0x6E24FB (FreeBattle / Practice / League /
Tournament / Survival + 5 network scenes). FreeBattle init registers property
`advDemoId` at `scene + 5040`. Stage id global 0x141611A88, BGM global
0x141610160, BGM table off 0x1527EA0.

### Lua (tolua)

| What | off | VA |
|---|---|---|
| `ns2_tolua_ccRegistScript_open` | 0x849A68 | 0x14084A668 |
| `tolua_function(L, name, fn)` | 0x9AA9C0 | 0x1409AB5C0 |
| `tolua_endmodule` | 0x9AA9B0 | 0x1409AB5B0 |
| `tolua_isnoobj` | 0x9A9C90 | 0x1409AA890 |
| `tolua_error` | 0x9A9A60 | 0x1409AA660 |
| `ccSetFade(from, to)` | 0x537470 | 0x140538070 |
| `ccLoadTitleUi` | 0x535494 | 0x140536094 |
| `ccOpenTitleUi` | 0x4B9988 | 0x1404BA588 |
| `ccCloseTitleUi` | 0x4B95FC | 0x1404BA1FC |
| `ccAdvPlaySound_2D(id)` | 0x4DC7D0 | 0x1404DD3D0 |
| `ccAdvYesNoSelectWindowOpen(title)` | 0x4DCE4C | 0x1404DDA4C |
| `ccAdvSelectWindowAddItem(item)` | 0x4DCA2C | 0x1404DD62C |
| `ccDisableFcv` | 0x536260 | 0x140536E60 |

### Movies and CPKs

- String-argument movie function lead `sub_1404E18B0` (off 0x4E0CB0),
  commented out in UltimateStormAPI [L].
- CPK mount entry points: [cpk.md](../formats/cpk.md#runtime-entry-points-109-off-convention-va--off--0x140000c00-c).

### StormRevival client source [C][L]

Uses plain VA. Its scenario / scene hooks were disabled after a crash, and some
names are Connections 1.60 names; cross-check each address.

| What | Address |
|---|---|
| Relive Story scene names | 0x141818D80..0x141818F30 |
| episode lookup by key / id | `sub_140595D24` / `sub_140595C64`; root `qword_1415FD2D0 + 24` |
| boss create (allocates 0x708) | `sub_1406E4BC0` |
| gpSetting XML loader (0x108C-byte structs) | `sub_14043FB28` |
| `ConvertSelectCharaInfo` | RVA 0x05B83C0 |
| `SetConvertSelectCharaInfo` string | 0x1412C4228 |
| `battleParam.xfbin` string | 0x1412A4280 |
| xfbin resource API | see [xfbin.md](../formats/xfbin.md#runtime-storm-4-109-va-cl) |
| Scaleform RegisterMovie / Invoke | 0x14060759C / 0x140607BA0 |

The free-battle setup struct (character / stage selection) is unmapped; leads
are `ConvertSelectCharaInfo`, `ccSceneFreeBattleChangeParam`,
`propReliveStoryBattleParam` and `advDemoId` [L].

## Other builds

- **Storm 1** (`a68ea53d`): statically linked dlmalloc (`gm_` at RVA 0x8DA210);
  nucc memory blocks are mspaces on VirtualAlloc regions; VirtualAlloc IAT
  entry at RVA 0x64B238 [V].
- **Storm 4 1.07 → 1.09**: enum renumbering, new DLC ids, a few 30/fps fixes
  (substitution gauge in CtrlCounter), Thai language, EULA screen [V]. Data
  layouts are unchanged; addresses move.
- **Storm 4 debug 1.06**: same input front end and 30/fps scaling as release
  [V].

## Sources

| Source | Used for | Checked |
|---|---|---|
| Storm 4 1.09 / 1.07 / debug 1.06 exes (static and in game) | all [V] rows | [V] |
| TheLeonX/UltimateStormAPI | scene manager, battle hooks, Lua helpers, version detection | spot-checked (CtrlInputPad, duel camera, movie lead) |
| zealottormunds/ns4moddingapi | `MsgToString`, Lua helpers, CPK mount | no |
| StormRevival client source (community) | Relive Story / boss / gpSetting / resource API addresses | no |
| [community symbol set](https://github.com/exavadw/naruto-storm-symbols) | function names (RVA) | used as names only |
| SteamDB patch notes for app 349040 | Steam build number and date | no |
