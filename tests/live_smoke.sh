#!/bin/sh
# Live smoke test. Run on a host that has the DB and MCP access.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUN="python3 -m storm_re"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "== builds"
$RUN builds
echo "== resolve name"
$RUN resolve ccPlayer::ChangeAction -b s4
echo "== resolve VA"
$RUN resolve 0x1407AB468 -b s4
echo "== resolve RVA"
$RUN resolve 0x7AB468 -b s4
echo "== decomp (sig)"
$RUN decomp ccPlayer::ChangeAction -b s4 --detail sig
echo "== xrefs"
$RUN xrefs ccPlayer::ChangeAction -b s4 --limit 10
echo "== diff"
$RUN diff ccPlayer::ChangeAction --from s4 --to s4-debug
echo "== state surface"
$RUN state_surface ccPlayer -b s4 --limit 10
echo "== input path"
$RUN input_path -b s4
echo "== frame tick"
$RUN frame_tick -b s4 --limit 10
echo "== net session"
$RUN net_session -b s4 --limit 10
echo "== scene dispatch"
$RUN scene_dispatch -b s4 --limit 10
echo "== patch diff"
$RUN patch_diff --from s4 --to s4-debug --limit 3
$RUN patch_diff --from s1-clean --to s1 --limit 3
echo "== export"
$RUN export input --out /tmp/storm-re-input-smoke.md --limit 5
echo "== find"
$RUN find ChangeAction -b s4 --limit 5
echo "== stat"
$RUN stat
