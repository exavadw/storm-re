# cpuparam (versus AI)

Storm 4 versus AI is data-driven. Difficulty is a script per level
in `cpuparam.xfbin`, not hard-coded behaviour.

## File (Storm 4 1.09) [V]

`cpuparam.xfbin` holds four chunks:

| Chunk | Content |
|---|---|
| `cpu_script` | not mapped |
| `cpu_strength` | 11 level scripts; each sets an `int str[20]` strength array |
| `cpuPlayerParam` | not mapped |
| `cpuActionParam` | not mapped |

- Level index is clamped to ≤ 10. Level ≥ 11 crashes [V].
- `cpu_strength` script command 5 = `SetParam` [V]; the eliteace170
  `cpu_strength.bt` template agrees and adds full opcode / command enums
  (unverified) [C].
- Byte layouts of the four chunks are not recorded here.

## Runtime (Storm 4 1.09)

| What | Address / offset | Tag |
|---|---|---|
| possible reaction gate | VA 0x141611F08 | [L] needs a runtime read |
| AI countdown | `ai + 0x1A58`; carries over between battles | [V] |

battleParam's enemy block carries an AI level byte at +0x2C (see
[battle-param.md](battle-param.md#enemy-block-0x60)).

## Sources

| Source | Used for | Checked |
|---|---|---|
| Storm 4 1.09 exe (static) | chunk list, level clamp, command 5 | [V] |
| eliteace170/XFBIN-010-Editor-Binary-Templates-Master (`cpu_strength.bt`) | opcode / command enums | command 5 agrees; rest not checked |
| eliteace170/NSUNS4-Evo-Toolbox (CpuParam codec) | — | targets a mod's data, not retail; not used |
