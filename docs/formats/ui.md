# UI (Scaleform)

Storm 4 and Connections draw their menus and HUD with Autodesk Scaleform GFx
(ActionScript 3). C++ drives a movie by invoking AS methods and answering AS
callbacks.

## Files

| Item | Value |
|---|---|
| Storm 4 UI movies | `.gfx`, loose in `data/ui/flash/OTHER` (not inside CPKs) [V] |
| Other UI movies | `.swf` under `data/ui/flash/FLASH_PLAT/...`, some wrapped in xfbin (e.g. `data/ui/result/result00.xfbin` in Storm 3) |
| Options menu | `option.gfx` [V] |

Known movies:

| Movie | Purpose | Tag |
|---|---|---|
| `result_main/result_s.swf` | "Battle Results" toast on the winner screen (rank letter) | [V] |
| `duel_cond.swf` | battle condition / bonus-task lines | [V][C] |
| `icon_item2/cutin_get.swf` | item cut-in | [V] |
| storyBoard swf (`ccUiFlashStoryBoard`) | Relive Story chapter map | [V] |
| `msg_fin.swf` | Relive Story movie scene UI | [C] |
| `hist_cmn.swf` | Relive Story selector | [C] |

## Runtime (Storm 4 1.09)

| What | Address | Notes |
|---|---|---|
| `Movie::Invoke` | VA 0x140871310 | call with `"path.Method"`; `ObjectInterface::Invoke` faulted when used instead [V] |
| RegisterMovie | VA 0x14060759C | StormRevival source [C] |
| Invoke (bridge) | VA 0x140607BA0 | StormRevival source [C] |
| condition window UI | `sub_140604588` (`duel_cond.swf`) | [C] |
| results toast global | DAT_14161C9C0; opened by FUN_1406701E4, ranked by FUN_14066E0B0 | [V] |

Release managed `GFx::Value` results after use, or the Scaleform garbage
collector crashes [V].

### Storyboard callbacks [V]

The Relive Story map is ActionScript-driven: each chapter
(`main_outline_00000..33`) has a fixed node layout and art baked into the
movie. C++ answers:

| Callback | Meaning |
|---|---|
| `SetSaveDataInfo(index, cleared, new, opened, rank, ...)` | per node |
| `GetTotalRank` / `SetTotalRankInfo` | episode total rank |
| `CreateConditionWindow` | the battle's bonus tasks and rewards (FUN_14068FA18) |

Because node layout and art live in the movie, new content cannot be added to
the map by data alone.

## Tooling notes

- JPEXS FFDec decompiles and edits the AS3. Its bulk `-importScript` breaks
  these movies, and its compiler cannot handle `= NaN` default parameters or
  `CreateCallbackFunction` closures. Patch individual methods instead.

## Sources

| Source | Used for | Checked |
|---|---|---|
| Storm 4 1.09 exe (static + in game) | Invoke, storyboard callbacks, toast | [V] |
| StormRevival client source (community) | RegisterMovie / Invoke bridge VAs, `msg_fin` / `hist_cmn` | no |
| JPEXS Free Flash Decompiler | AS3 tooling | — |
