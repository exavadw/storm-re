# Story-mode tables and rank data

Files behind story mode ("Relive Story" in Storm 4), boss battles, adventure
mode and group battles, plus the result-grade tables and rank models of each
game. Battle definitions themselves are in [battle-param.md](battle-param.md).

## Storm 4 episode tables

| File (`data_win32/rpg/param/WIN64/`) | Chunk | Manager | Layout |
|---|---|---|---|
| `episodeParam.bin.xfbin` | `episodeParam` | `ccReliveStoryParamManager` | **unknown** |
| `episodeMovieParam.bin.xfbin` | `episodeMovieParam` | `ccReliveStoryMovieParamManager` | **unknown** |

- No public tool documents either layout. NSUNS4-Toolbox stores only their
  paths (its "Episode Editor" / "Episode Movie Editor" code is not in the public
  repo); NSUNS4-Evo-Toolbox has only the `EPISODE_xx_xx` unlock-condition ids.
- Version constant string: `CCD_RELIVE_STORY_EPISODE_PARAM_VERSION` [C].
- In-game properties: `propReliveStoryEpisodeParam`, `...EpisodeIdx`,
  `...BattleParam`, `...BossPhase`, `...MovieId`, `...SkipResult`,
  `...IsPlayAll`, `propReliveStorySaveIdx` [C][V]. So an episode row points at a
  battleParam key and/or a movie id [L].
- Episode lookup (1.09, StormRevival source) [C]: by key `sub_140595D24`, by id
  `sub_140595C64`, root `qword_1415FD2D0 + 24`.
- Battle id → battle index: FUN_14051D1DC maps `EPISODE_BATTLE_nn` /
  `BOSSBATTLE...` ids to 0..0x1FF; any other id returns -1 [V].

Scenes [C]: `ccSceneReliveStorySelect`, `...Play`, `...PlayStandDemo`,
`...Movie` (names at VA 0x141818D80..0x141818F30). The movie scene logs
`movieId: %d`.

### Not present

Searched for and not found in Storm 4: `storyModeParam`, `sceneParam`,
`eventParam`, `freeBattleParam`, `eventDuelParam`, a `data_win32/adv/` folder,
a separate decision-point file. `s4_preset_ids.txt` belongs to NSUNS4SBE, not
the game [C].

## Storm 4 boss battles

- Scripted scenes `ccSceneBoss01Root` .. `ccSceneBoss15Root`, plus
  `...Movie01`, `...Demo` variants; `ccSceneBossBattleFreeBattleRoot` replays
  bosses from free battle [C].
- Script data: `data/ia/dNN/dNN_script.xfbin`, `dNN_xml.xfbin`,
  `dNN_###.lua` [C].
- Params: `data/boss/bossParam/PLAT/boss*Param.bin.xfbin` [C].
- Dialogue message ids follow `episodeN_N_NNNN` [C].
- Boss create `sub_1406E4BC0` allocates 0x708 bytes [C].

## Storm 4 adventure mode

- `data_win32/rpg/WIN64/advCommonParam.xfbin`: `mobPlacementParam`,
  `subEventPlacementParam`, `mobLooksParam`, ... [C]
- Lua scripts: `rpg/script/rpg_script.xfbin` [C].
- `data/rpg/PLAT/stParam*.xfbin`, `ptParam_ep_*.xfbin`, many
  `data/rpg/param/PLAT/adv*.xfbin` [C].
- Scenes: `ccSceneAdventure`, `AdvSetup`, `AdvIa`, `AdvIaLoad`,
  `ccSceneChapterLoading`, `AdvWorldMap`, `AdvStaffRoll`; Lua
  `ccSetAdvMainChapter` / `ccGetAdvMainChapter` [C].

## Storm 4 group battles: gpSetting

`data/gp/setting/gpSetting.xfbin` embeds XML. Loader `sub_14043FB28` parses it
into 0x108C-byte structs [C]. Element tree:

```
id
Basic/      Script/path, battleParam, bossLoading, chapter
World/      world, start
Characters/ Character {id, role = leader | support, skill, far, life}
Players/    Player/ {Type {code, costume, role, skill, awake}, Pos, Dir, Cpu/type}
Uis/        Ui/name
Files/      File/name
```

`Basic/battleParam` keys into battleParam, like episode rows do.

## resultGradeParam (money ledger + rank thresholds)

`data/duel/resultGradeParam.bin.xfbin`. Each record is one ledger line, one
bonus, one special finish, or one rank threshold. The layout drifts between
games.

### Revolution (PC) [V]

Version 1002, 73 entries, 0x24 bytes each.

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| 0x00 | 4 | — | id | |
| 0x04 | 8 | — | label | |
| 0x0C | 4 | u32 | mode mask | mode 0 = story mode |
| 0x10 | 4 | u32 | kind | 0 ledger row, 1 counted bonus, 2 special, 3 rank |
| 0x18 | 4 | — | value | |
| 0x1C | 4 | — | extra | |
| 0x20 | 4 | — | extra2 | |

Mode 0 values: `GRADE_LIFE` 30, `GRADE_TIME` 10, `GRADE_NORMAL_BONUS` 1;
counted `NORMAL_*` 5..80; `NORMAL_CPULV` 50 + extra 200; specials
`SPECIAL_FIRST_ATTACK` 100, `_THROW_FINISH` 100, `_NINJUTSU_FINISH` 200,
`_OUGI_FINISH` 500, `_RENKEI_FINISH` 800, `_AWAKE_FINISH` 500,
`_AWAKE2_FINISH` 800, `_DRIVE2_FINISH` 500, `_SEAL_FINISH` 800, `_RINGOUT`
500, `_TEAMBONUS` 300; `RANK_S..D` thresholds 4000 / 3500 / 3000 / 1500 / 0
with money multipliers 4.0 / 3.0 / 2.0 / 1.5 / 1.0.

Note: a first-attack bonus of 300 read off a results screen in a video is the
team bonus; the data gives first attack 100.

### Storm 3 / Full Burst (from code; values unconfirmed)

Loader FUN_14025ABB4 (Storm 3 HD). 0x30-byte records:

| Off | Size | Type | Name | Notes |
|---|---|---|---|---|
| 0x00 | 8 | — | name | |
| 0x08 | — | — | label | |
| 0x18 | 4 | u32 | mode mask | |
| 0x1C | 4 | u32 | line type | 1 counted bonus, 2 special, 3 rank, 4 normal |
| 0x24 | 4 | — | base value | money, or the rank's percent multiplier |
| 0x28 | 4 | — | rank threshold | |

Lines: `GRADE_LIFE`, `GRADE_TIME`, `GRADE_NORMAL_BONUS` (counted `NORMAL_*`),
specials (`SPECIAL_FIRST_ATTACK`, `_THROW_FINISH`, `_NINJUTSU_FINISH`,
`_OUGI_FINISH`, `_RENKEI_FINISH`, `_AWAKE_FINISH`, `_RINGOUT`,
`BOSS_PENALTY_RETRY`, ...).

Storm 4 also has `resultGradeParam` with the Storm 3 layout, used by free
battle's money ledger (`ccUiBattleResult`, FUN_14072A770), not by story
battles [V].

## Rank models by game

| Game | Model | Thresholds | Saved per battle |
|---|---|---|---|
| Storm 2 | points ledger, fixed tables in the exe | S ≥ 3000, A ≥ 2500, B ≥ 1500, C ≥ 1000 | best points (rank recomputed for display) |
| Storm 3 / FB | money ledger (`resultGradeParam`); rank = highest `RANK_*` threshold ≤ total | from data (unconfirmed) | best rank 0..4, 5 = never cleared |
| Revolution | money ledger (`resultGradeParam` mode 0) | 4000 / 3500 / 3000 / 1500 | best rank 0..4 per battle, 5 = none |
| Storm 4 | factor average | factor scores 4/3/2/1 at 90/80/50/20 %; average ≥ 4 S, ≥ 3 A, ≥ 2 B, ≥ 1 C | best rank per episode slot, bonus flags per battle |
| Generations | money ledger | S ≥ 4000, A ≥ 3500, B ≥ 3000, C ≥ 1500 | nothing |

Rank index everywhere: 0 S, 1 A, 2 B, 3 C, 4 D. A lower (better) rank replaces
the saved one.

### Storm 4 (1.09) [V]

`MiniResult::Rank` FUN_14066E0B0 scores each factor `pct ≥ 90 → 4, ≥ 80 → 3,
≥ 50 → 2, ≥ 20 → 1, else 0`:

| Factor | Applies |
|---|---|
| life left percent | always |
| continues: 0 → 4, else 0 | always |
| boss QTE ratio | `BOSSBATTLExx_PHASEn` episodes (8, 12, 32 or 36 prompts) |
| secret factor | episodes 0x14 and 0x6C (secret actions out of 4 / 9) |

`rank = average of factors` → ≥ 4 S, ≥ 3 A, ≥ 2 B, ≥ 1 C, else D. Shown by the
results toast `result_s.swf` (see [ui.md](ui.md)). With save index -1 every
input reads 0, so a battle outside the episode table always ranks B (life 0 →
0, no continue → 4, (0 + 4) / 2 = 2) [V]. Memory layout of the inputs and save:
[reference](../reference/storm4-1.09.md#story-results-and-save-v).

### Storm 3 / Full Burst [V code]

- `ccUiBattleResult` (`source\Battle\UI\Result\ccUiBattleResult.cpp`): the
  score is the money earned; FUN_1402544BC picks the type-3 record with the
  highest threshold ≤ score (`RANK_S`..`RANK_D` → 0..4), then the rank's
  multiplier is applied to the money.
- Boss total (`ccUiBossBattleTotalResult`): each stage has a rank; the total is
  the first i with `average ≤ i + 0.5` over the stage ranks (FUN_1403CAB30).
  QTE ratio (`BOSS_SPECIAL_IA`), secret factor and secret action lines pay money
  only.
- Results screen `data/ui/result/result00.xfbin` (`result_main`): rank stamp
  `result_rank_%c`.
- Save struct DAT_140BEB938: battle records at +0x1187C (0x14 bytes each, 188
  records: +4 best rank, 5 = never cleared; +8..+0x10 per-partner flags); boss
  records at +0x1283C. Rank update FUN_140189CA8.
- Replay list: `data/rpg/param/chronologyParam.xfbin` (free, boss and group
  battles); FUN_14021A544 copies `advBtlSelParam` and changes to the chronology
  battle root. Layout not recorded.
- Full Burst: same logic (rank FUN_005302B0, forced S on mode 0xB).

### Storm 2 [V code]

- `ccMenuDuelResultDetail.cpp` FUN_14034ECEC: points = categories (table
  0x1407F8130: time left 5 per second, life 20 per %, ...; boss: QTE ratio 5 per
  %) + bonus items (0x1407F8510: time ≤ 40 / 30 / 20 s → 200 / 400 / 800; 100 %
  life → 4000, replacing the life line; combo tiers; ...).
- Rank FUN_140350730, thresholds at 0x1407F8108. Money = points × 1.5 / 1.3 /
  1.2 / 1.1 / 1.0 for S..D.
- Results `data/ui/result/result.xfbin`, rank stamp `br_ninka_rank{s,a,b,c,d}`.
- Mission records at `&DAT_140A27988 + 0x101B0 + idx * 0x18`: flags (get, new,
  visible, clear), best points, partner bonus flags, secret bonus. Lua:
  `ccSetMissionBattleRank` / `ccGetMissionBattleRank`, `ccSet/IsMissionBattleClear`.
- `data/rpg/rankParam.bin.xfbin` is the online battle-point rank, not a story
  rank.

### Revolution (PC) [V code]

Health = HP × 100 / max (at least 1 while alive) × 30; Time = (T − elapsed s) ×
10 with T = 99 when there is no limit (0x00650C00); bonus = Σ value × count +
extra (0x0064EFD0); CPU level count = level + 1 against a CPU (0x00652870);
specials add once per finish type (0x00651250); rank 0x0064F1A0; money
0x00651A10. Story battles `ANIME_BATTLE_MAIN_001..005`: no time limit, CPU
levels 3, 4, 5, 4, 6. Save + 0xF894 + battle × 0x14, +4 best rank. Lua:
`ccGetBattleResultRank`, `ccClearBattleResultRank`,
`ccCheckAnimeBattleResultAllS01`.

### Generations (Xbox 360) [V code]

Results screen 0x8239B038 (`ccMenuDuelResult`), scorer 0x8239DBC8; rows from
0x82057358, tiers 0x820577E0..0x820595BC; rank 0x8239BA18 over
`{4000, 3500, 3000, 1500, 0}` (0x82059658); money × 1.5 / 1.3 / 1.2 / 1.1 / 1.0
(0x820577CC). Rows: health 20 per % (100 % pays 4000 instead); time 5 per second
left of 99, plus the best of ≤ 20 / 30 / 40 s = 800 / 400 / 200; counted
actions with tiers; strong-enemy 250 + 50 × CPU level; finishes ninjutsu 80,
ultimate 400 (+200 per hit), team ultimate 800 (+400 per hit), awakening 200.
battleParam conditions add nothing. `data/rpg/rankParam.bin.xfbin` is a player
title ladder, not a battle rank.

## Sources

| Source | Used for | Checked |
|---|---|---|
| TheLeonX/NSUNS4-Toolbox | episode table paths | paths only |
| eliteace170/NSUNS4-Evo-Toolbox | `EPISODE_xx_xx` unlock ids | no |
| zealottormunds/ZealotStormTools (README) | adventure placement params | no |
| zealottormunds/nsuns4sbe | `s4_preset_ids.txt` | — |
| StormRevival client source (community) | Relive Story / boss / adventure class names and VAs, gpSetting schema, episode lookup | no; some of its names are Connections names; cross-check every address |
| Storm 2, Storm 3 HD, Full Burst, Storm 4 1.09, Revolution PC exes; Generations X360 xex | rank code, save layouts | [V] static; Storm 4 also in game |
| Revolution PC data | resultGradeParam layout and values | [V] |
