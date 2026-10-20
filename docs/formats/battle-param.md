# battleParam (story battles)

Storm 4 story-mode battle definitions. One entry = one battle: fighters,
stage, time limit, passive conditions, bonus tasks, rewards, win quotes, BGM.
Managed in game by `ccAdvBattleParamManager`. Group (mob) battle scenarios and
episode rows key into it by name (see [story-tables.md](story-tables.md)).

## File

| Item | Value |
|---|---|
| Game path | `data/rpg/PLAT/battleParam.xfbin` (exe string at VA 0x1412A4280) |
| PC disk path | `data_win32/rpg/WIN64/battleParam.xfbin` |
| Chunk | `battleParam` (`nuccChunkBinary`), inner path `bin_le/x64/battleParam.bin` |
| Payload version | 0x3F0 (1008) |
| Header | standard param header ([xfbin.md](xfbin.md#standard-payload-header-le)): count at file 0x120, entries at 0x12C |
| Entry size | 0x110, little-endian |

## Entry (0x110 bytes) [C]

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| 0x00 | 8 | relptr → str | battle id | key used by episode / scenario data (e.g. `EPISODE_BATTLE_nn`) |
| 0x08 | 8 | relptr → str | description | message id |
| 0x14 | 4 | u32 | time limit | seconds; `0x64` (100) = infinite |
| 0x18 | 1 | u8 | game-over state | |
| 0x20 | 8 | relptr → str | stage | stage id (`STAGE_...`) |
| 0x30 | 8 | relptr → block | costume / reward block | see [Block at +0x30](#block-at-0x30) |
| 0x38 | 0x70 | 14 × relptr → str | conditions | passive effects and tasks, see [Condition vocabulary](#condition-vocabulary) |
| 0xA8 | 8 | relptr → block | player | 0x58 bytes |
| 0xB0 | 8 | relptr → block | player support 1 | 0x28 bytes |
| 0xB8 | 8 | relptr → block | player support 2 | 0x28 bytes |
| 0xC0 | 8 | relptr → block | enemy | 0x60 bytes |
| 0xC8 | 8 | relptr → block | enemy support 1 | 0x2C bytes |
| 0xD0 | 8 | relptr → block | enemy support 2 | 0x2C bytes |
| 0xD8 | 4 | u32 bool | alt win quote: player | |
| 0xDC | 4 | u32 bool | alt win quote: support 1 | |
| 0xE0 | 4 | u32 bool | alt win quote: support 2 | |
| 0xE8 | 8 | relptr → str | win quote: player | message id |
| 0xF0 | 8 | relptr → str | win quote: support 1 | message id |
| 0xF8 | 8 | relptr → str | win quote: support 2 | message id |
| 0x100 | 4 | u32 | BGM id | 1000 (0x3E8) = stage default |
| 0x104 | 4 | u32 | battle-quotes id | indexes `situationVoice.bin.xfbin` |

Bytes not listed are unknown / padding.

Bonus-task order: the in-battle task tracker loads up to 7 tasks "in battleParam
+0x58 order" [V]. +0x58 is the fifth relptr of the 0x38 condition array; how
the 14 slots split between passives and tasks is not confirmed [L].

### Player block (0x58) [C]

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| 0x00 | 4 | u32 | characterId | preset id from `playerSettingParam` |
| 0x04 | 4 | u32 | skill | 0-5, 6 = default |
| 0x08 | 4 | u32 | ultimate | 0-3, 4 = default |
| 0x0C | 4 | u32 | disableTrueAwakening | |
| 0x10 | 4 | u32 | altTexture | |
| 0x14 | 4 | u32 | unknown | |
| 0x18 | 4 | u32 | unknown | |
| 0x1C | 4 | u32 | armorBreakModel | |
| 0x20 | 4 | u32 | unknown | |
| 0x24 | 4 | u32 | awakeningFromStart | |

### Enemy block (0x60) [C]

Same as the player block, with these differences:

| Off | Size | Type | Name |
|---|---|---|---|
| 0x0C | 4 | u32 | unknown |
| 0x24 | 4 | u32 | disableSubstitution |
| 0x2C | 1 | u8 | AI level |

NSUNS4-Toolbox exposes a "Mode" choice of Normal / Awakening mode. Its writer
appends the blocks after the entry array, then the strings.

### Block at +0x30

Two sources describe this block differently; both are recorded.

NSUNS4-Toolbox (0xA8-byte "costume" block) [C]:

| Off | Size | Type | Name |
|---|---|---|---|
| 0x00 | 4 | u32 | value |
| 0x08 | 0x38 | 7 × relptr → str | material ids |
| 0x40 | 0x1C | 7 × u32 | quantities |

Exe reading on Storm 4 1.09 (reward block) [V]:

| Off | Size | Type | Name |
|---|---|---|---|
| 0x08 | 8 | — | the battle's own reward |
| 0x10 | 0x38 | 7 × item id | bonus-task reward items |
| 0x48 | 4 | — | own reward quantity |
| 0x4C | 0x1C | 7 × quantity | bonus-task reward quantities |

The team setup (FUN_140517BBC) copies this block into the battle's reward table
at VA 0x141612034; the task cut-in reads from that table, and the grant is
written to the save after the battle. Field types at +0x08/+0x10 (relptr vs id)
are not pinned down [L].

## Condition vocabulary [C]

Conditions are string ids, message-backed (`t_battlecondition_NNN`,
`b_mission_NNN`). The runtime list of known conditions is
`data_win32/spc/conditionprm.bin.xfbin`; UltimateStormAPI can extend it with a
`conditionprmManager.xfbin`.

Passive (`E_*` = applies to the enemy, `S_*` = to self):

`E_ATK_UP_005..150`, `E_DEF_UP_*`, `E_HEAL_*`, `E_REVIVE`, `E_SUPER_ARMOR`,
`E_THINK_GUARD / SKILL / SPATK / SUPPORT / DODGE`, `E_AWAKE`, `E_AURA_BOSS`,
`E_SEAL_SKILL / SPATK / AWAKE / ITEM / DODGE / SUPPORT`, `S_SPD_DOWN`,
`S_LIFE_DAMAGE`, `S_SEAL_*`, `S_AWAKE`, `CHAKURA_LIMIT_00/01`,
`LIFE_LIMIT_00/01`, `ATK_UP_TWICE`, `SEAL_DODGE`, `ALWAYS_USE_AWAKE`,
`SPATK_DAMAGE_100`, `NOT_GUARD`, `NO_DAMAGE_OTHER_THAN_RING_OUT`, `MEMORY`
(flashback filter), `TOURNAMENT_TIME_30`, ...

Tasks (win / bonus objectives):

`WIN`, `FINISH`, `FINISH_SKILL / SPATK / TEAM_SKILL / AWAKE / SUPPORT`,
`COUNT_COMBO_05..30`, `COUNT_SKILL_01..15`, `COUNT_SPATK_1..5`,
`COUNT_TEAM_SKILL`, `COUNT_SUPPORT_2..10`, `COUNT_DODGE_2..10`,
`SAVE_LIFE_020..100`, `SAVE_CHAKRA_020..100`, `SAVE_TIME_10..90`,
`TIME_10..90`.

Leftovers from Storm 3 / Revolution: `GROUP_BTL_*`, `TEAM_TYPE_OUGI`.

### Runtime task types (Storm 4 1.09) [V]

The in-battle tracker stores tasks as `{int type, int param}`. Pairs observed in
game:

| Task id | type:param |
|---|---|
| `CLEAR_SAVE_LIFE_50` | 12:50 |
| `COUNT_COMBO_05` | 6:5 |
| `COUNT_SKILL_01` | 7:1 |
| `FINISH_SPATK` | 3:0 (checker = finish bit 0x4) |
| `COUNT_SUPPORT_2` | 10:2 |
| `COUNT_SPATK_1` | 8:1 |

Tracker layout and checker table: [reference](../reference/storm4-1.09.md#round-judge-and-bonus-tasks-v).

## Other games

- Generations: battleParam +0x04 is the battle's name (`mainbattlename_NNN`);
  the layout differs from Storm 4 [V].
- NSUNS4SBE (2017 "Story Battle Editor") edits the same Storm 4 file: preset ids
  for player / 2 supports / enemy × 3, stage, time (100 = infinite), a 10-slot
  condition list. Superseded by NSUNS4-Toolbox [C].

## Sources

| Source | Used for | Checked |
|---|---|---|
| TheLeonX/NSUNS4-Toolbox (fork of zealottormunds/ns4charactermanager), battleParam editor | entry, player/enemy blocks, costume block, condition list | entry size, header and +0x30 / +0x58 cross-checked against 1.09 exe code; other fields not re-checked |
| zealottormunds/nsuns4sbe | field list (release strings only) | no |
| TheLeonX/UltimateStormAPI | `conditionprmManager.xfbin` extension | no |
| Storm 4 1.09 exe (static + in-game) | reward block, task order, task type pairs | [V] |
