# Audio and video

Storm 4 uses two sound engines: **CRI ADX2** (Atom) for BGM and voices, and
**NUS3** (`nus3bank`) for sound effects and character sounds. Video is **CRI
Mana / Sofdec** (`.usm`).

## CRI build in Storm 4 1.09 [V]

Version strings in the exe (all built Oct 6 2015):

| Component | Version |
|---|---|
| CRI AtomEx/PCx64 | 2.08.07 |
| CRI Atom | 2.09.12 |
| ACB format (high) | 1.27.02 |
| ACF format (high) | 1.13.00 |
| CRI NcVoice XAudio2 | 1.10.00 |
| CRI ASR | 1.04.03 |

Connections ships a much newer CRI SDK: function behaviour matches, struct
offsets do not.

## Banks

CRI banks are loaded from `disc:/data/sound/PC/`, voices from a language
subdirectory (`US`, `JP`, ...) [V]. Bank table at VA 0x141526C00, 0x30-byte
entries:

| Bank | Type | Index |
|---|---|---|
| `storm4.acf` | ACF (global config) | — |
| `bgm.acb` / `bgm.awb` | 0 (BGM) | — |
| `v_etc`, `v_win`, `v_spl`, `v_main00`..`v_main06`, `v_oneWord`, `v_ogiFinish`, `v_matching` | 1 (voice) | 0..12 |

messageInfo's `acbIndex` field uses its own index list (0x01 `v_win`, 0x0A
`v_ougiFinish`, 0x0B `v_matching`) [C]; the spelling `v_ougiFinish` (Toolbox) vs
`v_ogiFinish` (exe table) differs between the two sources. Earlier notes list
`v_main00-05`; the exe bank table reading gives `v_main00..06`.

Archives: `adx2.cpk`, `sound.cpk`. BGM audio: `sound/PC/BGM.awb` (AFS2 archive
of HCA streams) inside `data/patch/<N>/data.cpk` [C].

NUS3: `disc:data/sound/config.nus3conf`; character SE and voice banks are
`nus3bank` data wrapped in xfbin [V][C]. NUS3 category ids for volume: 1 BGM,
2 SE, 3 voice [V].

## Formats

| Format | Notes |
|---|---|
| ACB | cue sheet; Storm 4 accepts ≤ ACB 1.27.02. Can embed a memory AWB |
| AWB | AFS2 wave bank (`AFS2` magic); memory or streamed |
| ACF | global Atom config (`storm4.acf`), registered once with DSP bus setting `DspBusSetting_0` |
| HCA | codec used by stock BGM |
| ADX | the standard voice pool also decodes ADX (v3 / v4 header loop info). Encrypted ADX (flags 8 / 9) and AHX (encoding 0x11) are **not** playable: no key is set and no AHX decoder is linked [V]. Plain ADX type 3 (standard 500 Hz cutoff) plays |
| WAV / RIFF / raw PCM | **not playable** through the game's CRI: only ADX and HCA decoders are attached, and no Wave or RawPCM voice pool exists or can be created (the allocators are not linked) [V] |
| nus3bank | NUS3 sound bank inside xfbin |

## Video (USM)

- Cutscenes are CRI `.usm` under `data/movie/` inside `movie1/2/3.cpk` [C].
- The engine uses `CriMvEasy` with subtitle-buffer support and a
  `ccMovie: CuePoint Callback` [C].
- Whether retail USMs carry multiple audio tracks or a subtitle channel is
  **unknown** [L]. Subtitles could come from the USM subtitle channel or from
  message ids triggered by cue points (messageInfo entries can carry voice
  cues).
- Community replacement path: encode with Scaleform Video Encoder 4.0
  (Sofdec-based) and place the file at the same internal path in a patch CPK [C].
- Play-movie entry: Connections has `PlayMovieById(u32)` (1.60 off 0x566980,
  1.70 off 0x5711E0). For Storm 4 1.09 only a commented-out call to a
  string-argument movie function `sub_1404E18B0` (off 0x4E0CB0) is known [L].

## Storm 4 1.09 CRI runtime (VA) [V]

Static reading of the 1.09 exe, matched by CRI error-code strings (`E20…`),
source-order COMDAT layout of `cri_atom_ex_player.c`, and call patterns.
Cross-checked against Connections.

### Linked (usable)

| Function | VA | Signature (x64 MS ABI) |
|---|---|---|
| criAtomEx_Lock / Unlock | 0x14001A4A0 / 0x14001A4BC | `void(void)`; every public player call takes it |
| criAtomEx_SetUserFreeFunction | 0x140014EE8 | `(func, obj)` |
| criAtomEx_SetUserMallocFunction | 0x140014EFC | `(func, obj)` |
| criAtomEx_Initialize_PC (thunk) | 0x140019B10 | `(config, work, size)` |
| criAtomExPlayer_Create | 0x14001E190 | `hn(const cfg* /*NULL ok*/, work /*NULL*/, int size /*0*/)` |
| criAtomExPlayer_Destroy | 0x14001E4D4 | `void(hn)` (`E2010021530`) |
| criAtomExPlayer_SetCueId | 0x14001EE1C | `void(hn, acb, int cue_id)` (`E2010021531`) |
| internal SetCueId body (no lock) | 0x14001F89C | |
| criAtomExPlayer_Start | 0x14001F040 | `uint playbackId(hn)`; 0xFFFFFFFF on failure |
| criAtomExPlayer_Stop | 0x14001F378 | `void(hn)`; envelope release applies (`E2010021537`) |
| criAtomExPlayer_StopWithoutReleaseTime | 0x14001F3B4 | `void(hn)` |
| criAtomExPlayer_Pause | 0x14001ED2C | `void(hn, CriBool)`; sets `+0x101` |
| criAtomExPlayer_SetVolume | 0x14001F018 | `void(hn, float)`; parameter id 0 |
| criAtomExPlayer_UpdateAll | 0x14001F460 | `void(hn)` (`E2010022750`) |
| criAtomExPlayer_SetEnvelopeReleaseTime | 0x14001EE98 | `void(hn, float ms)`; parameter 0x79. Game uses 1000 ms BGM, 500 ms voice |
| criAtomExPlayer_SetAisacControlById | 0x14001EDC4 | `void(hn, uint id < 1000, float)` |
| criAtomExPlayer_SetVoicePriority | 0x14001EFD8 | int, clamped ±255 |
| criAtomExPlayer_GetStatus | 0x14001EA5C | 0 STOP, 1 PREP, 2 PLAYING, 3 PLAYEND, 4 ERROR (`+0x10`) |
| SetFaderHandle / SetStartCallback / SetStopCallback / SetSyncPlaybackId | 0x14001EEE0 / 0x14001EEE8 / 0x14001EF28 / 0x14001EF68 | |
| criAtomExAcb_LoadAcbFile | 0x14001BF9C | `(acb_binder, acb_path, awb_binder, awb_path, work, size)` |
| criAtomExAcb_LoadAcbData | 0x14001C240 | `(acb_data, size, awb_binder, awb_path, work, size)`; data must outlive the handle |
| criAtomExAcb_CalculateWorkSizeForLoadAcbData | 0x14001B894 | |
| CalcWorkSizeForLoadAcbFile | 0x14001B8E8 | |
| criAtomExAcb_Release | 0x14001BEDC | |
| criAtomExAcb_GetNumCues | 0x14001BDE4 | |
| criAtomExAcb_GetCueIdByIndex / GetCueIndexByName | 0x14001BBDC / 0x14001BCA0 | |
| criAtomAwb_LoadFromMemory | 0x1400515B4 | `(mem, size > 0x10, work, size ≥ 0x34 or both 0)`; linked, reached only internally |
| criAtomExVoicePool_AllocateStandardVoicePool | 0x14001C554 | `(cfg, work, size)` |
| criAtomEx_RegisterAcfFile (thunk) | 0x14001A904 | `(binder, path, work, size)` |
| criAtomEx_AttachDspBusSetting | 0x14001B23C | `(name, work, size)` |
| criAtomDbas_Create | 0x140018794 | |
| criAtom_CalculateAdxBitrate | 0x140015028 | `ch * rate * 0x120 >> 6` |
| criFsBinder_BindDirectory | 0x1400016A0 | `criFsBinder_BindFile` not found |
| criAtomPlayer_LimitLoopCount (low level) | 0x140015F48 | called only by the parameter applier 0x140048B48 |
| criErr_SetCallback | 0x1400120C8 | |

An older address list had 0x140014EE8 as SetFormat, 0x140014EFC as
CalculateWorkSize, 0x14001BF9C as SetSamplingRate, 0x140019B10 as
SetDataRequestCallback and 0x1400203E8 as stop/reset; those labels are wrong.
The table above is the corrected reading.

### Stripped by the linker (absent in Storm 4)

Their error strings are absent from the exe: criAtomExPlayer_SetData
(`E2010021532`), SetWaveId (`E2010021534`), SetFormat (`E2010021538`),
SetNumChannels (`E2010021539`), SetSamplingRate (`E2010021540`), SetFile
(`E2010021550/51`), SetCategoryById / ByName, SetCueIndex, SetPitch; low-level
criAtomPlayer_SetData / SetFile / SetContentId / public SetWaveId (only the
`...Unsafe` variants remain: SetWaveIdUnsafe 0x140016570,
SetDataRequestCallbackUnsafe 0x140016060); criAtomExCategory_SetVolume;
AllocateWaveVoicePool, AllocateRawPcmVoicePool; criAtomExPlayer_LimitLoopCount.

### Ex-player struct (SDK 2.08.07)

From Create, Start and SetCueId:

| Off | Meaning | Default after Create(NULL) |
|---|---|---|
| +0x10 | status | 0 |
| +0xA0 | sound-player handle | |
| +0xA8 | format bitmask | 1 = ADX (4 = HCA in Connections; unconfirmed for 2.08) |
| +0xAC | likely streaming cache id | -1 |
| +0xB0 | bits 24-29 channels, bits 0-19 sampling rate | 0x0200BB80 = 2 ch, 48000 |
| +0xB4 / +0xB5 | flags | 2 / 0 |
| +0xC8 | source type: 0 none, 1 cue id, 4 data, 5 file, 6 content id, 7 wave id | 0 |
| +0xD0 / +0xD8 | source arg 1 / 2 (acb, binder, awb or pointer / id, size or path) | 0 |
| +0xE0 | cue object (cue path only) | 0 |
| +0xFC | sync playback id | -1 |
| +0x101 | pause flag | |
| +0x108 | playback list | |
| +0x120 | parameter block | |
| +0x458..+0x478 | fader / start / stop callbacks | |

Start's body 0x14001F98C takes the cue path for source type < 4; for ≥ 4 it
calls 0x140020438, which dispatches on `+0xC8` to SoundPlayer_SetData
0x140049838 (4), SetFile 0x140049888 (5), SetContentId 0x1400497B8 (6),
SetWaveId 0x140049A4C (7), then ApplyFormat 0x1400204DC. Only the public
setters were stripped; the data paths remain. Internal clear-source
0x1400203E8: zero `+0xD0..+0xDF`, `+0xC8 = 0`, reset the sound player
(FUN_140049740), free the cue object at `+0xE0` (FUN_14004B370). (Connections'
SetData is exactly clear + set type 4 + pointer + size, at its newer offsets
`+0x100/+0x108/+0x110`.)

Looping: a fresh player has no loop-count parameter, so the ADX decoder loops on
header loop points indefinitely [L, not yet observed in game].

### How the game drives CRI

- Manager `nuccCriAdx2Manager`, singleton DAT_1416B61B0 =
  `*(ccSoundMgr**)0x141610160 + 0xE8`. Language at `adx2 + 0xA8 =
  *(0x141610160 + 0x28)`.
- Init 0x140A43260 (vfunc, from 0x140A42AD0 ← sound manager init
  0x14073E618): error callback, user malloc 0x140A44430 (counts bytes at
  `adx2 + 0xB0`) / free 0x140A443D0, `Initialize_PC` with thread model MULTI,
  server frequency 30.0, `max_virtual_voices = 16`, PC output 48000 / 2 ch.
- D-BAS: id 0, max streams 6, max bps = `AdxBitrate(2, 48000) * 8`, 4
  securement buffers; at `adx2 + 0x40`.
- One standard voice pool at `adx2 + 0x38`, config at `adx2 + 0x18`:
  `{id 0, num_voices 8, max_channels 2, max_rate 48000, streaming 1, renderer 2
  (ASR), decode_latency 0}`. Decoders: ADX 0x140014F7C and HCA 0x14006077C only
  (via criAtomPlayer_CreateStandardPlayer 0x140054FA4 → 0x140054E30).
- Five players, all `Create(NULL, 0, 0)`: `+0x48 / +0x50 / +0x58` BGM channels
  0..2 (the only Create calls, at 0x140A43477 / 0x140A4349C / 0x140A434AC),
  `+0x68` voice (ACB table at `+0x70`, count `+0x78`, 16-byte entries
  `{acb, numCues}`), `+0x80` mode 2 (ACB `+0x88`). `+0x60` = bgm.acb handle;
  `+0x90 / +0x98` cue counts.
- ACF + DSP bus registered by 0x140724668. ACB load path 0x140724544 →
  0x140A43980 → LoadAcbFile.
- BGM play 0x140A440D0 `(adx2, cue, ch, mode, tableIdx, vol, fadeMs)`:
  SetCueId, SetEnvelopeReleaseTime (`fadeMs < 0 ? 1000 : fadeMs`), Start,
  volume 0x140A43780. Callers 0x14073C2E8 (BGM) and 0x14073C350 (voice). Game
  BGM stop with fade 0x140A44330.
- Per frame 0x140A42E60 (from 0x140A0AD40) → AISAC ramp 0x140A428B0 and volume
  ramp 0x140A42E80.
- Every CRI call runs on the game main thread; the 30 Hz CRI server thread
  honours `criAtomEx_Lock`.

### Option volumes

The game uses player volume, never categories. Sound manager
`M = *(float**)0x141610160`, CRI manager `A = *(char**)(M + 0xE8)`:

| Option | Setter | Stored | CRI | NUS3 |
|---|---|---|---|---|
| master | 0x14073E410 | `M[0]` | `A + 0xC4 = v * 0.8` (not re-applied to running players) | 0x140A4C7C0 |
| BGM | 0x14073E264 | `M + 0x04` | `A + 0xC8 = v * 0.4`; each BGM channel `SetVolume(A+0xC8 * A+0xC4)` + UpdateAll | category 1 = v |
| voice | 0x14073E568 | `M + 0x08` | `A + 0xCC = v`; voice player `SetVolume(A+0xCC * A+0xC4)` | category 3 = v * M[0] |
| SE | 0x14073E52C | `M + 0x0C` | none | category 2 = v * M[0] |
| unknown | 0x14073E46C / 0x14073E4A8 | `M + 0x10` / `M + 0x14` | `A + 0xD0 = M[5] * 0.5` at init | |

Options UI 0x1406A9E10 passes `savedata_int * 0.05` (constant at 0x1412FAE84;
0..20 steps): save `+0x14` → 0x14073E4A8, `+0x18` → BGM, `+0x1C` → SE,
`+0x20` → voice, `+0x24` → 0x14073E46C. Pending block 0x1415FA450..68 applied
in 0x140564574. NUS3 category volume setter 0x140A4C890 `(sys, cat, vol)`;
NUS3 system DAT_1416B6870 (0x140A4C0A0, 0x140A4C290).

At play time BGM volume = `A+0xC8 * A+0xC4 * M[1]`, so it is
`0.32 * master * bgm²` at start and `0.32 * master * bgm` after a slider change
(a game quirk).

## Sources

| Source | Used for | Checked |
|---|---|---|
| Storm 4 1.09 exe (static), Connections exe (comparison) | CRI runtime, banks, volumes | [V] static; looping and file-stream binder behaviour unconfirmed in game |
| TheLeonX/NSUNS4-Toolbox (ACB list, nus3bank editor) | messageInfo ACB indices, nus3bank in xfbin | no |
| IklilIlm/XfbinSoundTool | xfbin-wrapped sound ↔ ACB (Connections) | no |
| TheLeonX/UltimateStormAPI | movie function leads | no |
| SonicAudioTools (AcbEditor), VGAudio, ffmpeg `adpcm_adx` | general CRI format tooling | — |
| Steam community discussions / guides | BGM.awb location, USM replacement | no |
