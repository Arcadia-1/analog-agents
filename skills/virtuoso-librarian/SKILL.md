---
name: virtuoso-librarian
description: >
  Move, clone, package, archive, split, or reorganize Cadence Virtuoso
  cells and libraries at the design-data level. Use this skill whenever
  the user wants to: copy a TB to another library, reproduce a sim
  independently in a fresh library, hand off a design, prepare a
  tapeout archive, split one TB cell into several, promote a block
  between libraries, or enumerate a design's full reference
  hierarchy. Think of it as the "librarian" for your Virtuoso
  workspace — it knows which cells belong together, how to move
  them without breaking config bindings, and how to distinguish
  project cells from PDK / std-cell / analogLib references.
---

# virtuoso-librarian

Move / clone / reorganize Virtuoso designs at the library level. The
ground-floor operation is **clone a TB + every project cell it
transitively references into a target library, leaving PDK / std-cell
/ analogLib references untouched**, such that the new library
simulates identically in isolation.

## When to use this skill

Trigger phrases (rough):
- "把 TB X 复制到 Y 库" / "copy this testbench to <lib>"
- "让 X 在新库里独立复现仿真"
- "把设计打包交付"
- "把一个 TB 拆成几个独立 cell"
- "归档这个设计"

If it's just "rename a TB within the same library" without hierarchy
concerns, the `virtuoso` skill's `references/testbench-duplication.md`
covers the minimal steps. Use **this** skill when the DUT hierarchy
also needs to move.

## The canonical tool

```bash
python <skill-path>/scripts/tb_clone/clone_tb_full.py \
  SRC_LIB SRC_CELL DST_LIB
```

Or from Python:

```python
import sys
sys.path.insert(0, "<skill-path>/scripts/tb_clone")
from tb_clone_lib import clone_tb_full, scan_hierarchy, rebind_instance
clone_tb_full(client, "PLAYGROUND_AGENTS", "_TB_AMP", "Noisy_Past_Design")
```

What it does end-to-end:

1. Walks the TB schematic recursively, collects every `(lib, cell)`.
2. Classifies each as **project-owned** (copy to DST) or **external**
   (keep reference). External = `analogLib`, `basic`, any lib matching
   `^tsmc`, `^tcbn\d+`, `^smic`, `^gf\d+`, etc. See `is_external_lib`.
3. For every project cell: `rsync -a --exclude='*.cdslck*' --exclude='*%'`
   the whole cell directory, deref SOS symlinks in `master.tag`,
   `chmod u+w`. For TBs also wipes `results/` and auto-run snapshots
   in `test_states/`.
4. Patches `config/expand.cfg` (design + sub-cell bindings).
5. Patches `maestro/maestro.sdb`, `active.state`, and
   `test_states/*.state` — scoped substitution on `<value>LIB</value>`
   and `"LIB"` only, never on path strings.
6. For every copied cell's schematic, replays
   `dbDeleteObject(inst) + dbCreateInst(cv new_master name xy orient)`
   on every instance whose master was in a project lib. Multi-level —
   TB + DUT + DUT-of-DUT all get rebound.
7. Verifies zero stale project-lib references remain.

## Why the tool exists (6 hard-earned constraints)

All earned the hard way during the 2026-04-20 session cloning 8 TBs
(7 from PLAYGROUND_AGENTS + 1 from GM2026) into Noisy_Past_Design.

### 1. External-lib filter must be pattern-based, not a name list

TSMC adds HVT/LVT/ULVT track variants continuously. Hardcoding
`{"tcbn28hpcplusbwp12t30p140"}` misses `tcbn28hpcplusbwp12t30p140hvt`
and every future variant. Use regex: `^tsmc`, `^tcbn\d+`, `^smic`,
`^gf\d+`. The tool does.

Symptom if missed: std-cell library gets "copied" into the
destination (30+ cells like `BUFFD8BWP12T30P140HVT`). Obvious
smell: library-named files named like PDK conventions appear under
your project library root.

### 2. `dbReplaceHierInst` / `dbReplaceMaster` / `dbSetInstMaster` DON'T WORK on IC6.1.8

Nor does `inst~>libName = "NewLib"`. All silently succeed with no
effect. Tested at both the **individual Instance** level and the
**InstHeader** level (`ih~>libName = "X"`) — reading back *immediately*
after assignment still yields the old value. `libName` is effectively
read-only in IC6.1.8's db layer. **The only mechanism that rebinds
instance masters is delete-and-recreate:**

```skill
xy     = inst~>xy
orient = inst~>orient
; NOTE: dbProp's type accessor is `~>valueType`, NOT `~>type`.
; `~>type` silently returns nil for every prop -> snapshot becomes
; empty and dbReplaceProp later errors with `sprintf: argument #2 is nil`.
; Real accessors (via p~>?): cellView objType prop enum name object
; range value valueType assocTextDisplays.
props  = mapcar(lambda((p) list(p~>name p~>valueType p~>value)) inst~>prop)
new_master = dbOpenCellViewByType(dst_lib dut_cell view nil "r")
dbDeleteObject(inst)
new_inst = dbCreateInst(cv new_master inst_name xy orient)
foreach(p props
  when(and(nth(0 p) nth(1 p))      ; skip system props with nil name/valueType
    dbReplaceProp(new_inst nth(0 p) nth(1 p) nth(2 p))))
```

Bus-syntax names (`I21<1:0>`, `I127<20:1>`) pass as normal strings.
The instance usually binds to `symbol` view, not `schematic` — read
`inst~>master~>viewName` before rebinding.

**Must preserve `inst~>prop` across delete+create.** `dbCreateInst`
builds a fresh instance with only the master's CDF defaults, so any
per-instance override is wiped silently. Real examples seen:
`nlAction="ignore"` (device-exclude flag — losing it re-injects
intentionally-excluded instances into the netlist, changing sim
results), `vtrans_clk=...` (ahdlLib S&H threshold override), per-inst
transistor sizing. Keep prop values in-SKILL the whole time — never
round-trip through strings, since `sprintf "%L"` quotes for display
and can't be read back as the original float/int/list. Guard against
props with `nil` name or type (system/internal props that
`dbReplaceProp` rejects — you'll see
`*Error* fprintf/sprintf: ... argument #2 is nil` spam).

### 3. Copy with `rsync --exclude`, never `cp -r` + cleanup

Source libs are often held by other users with `.cdslck` lock files
(e.g., `sch.oa.cdslck.RHEL30.thu-ming.186048`). If those lock files
touch disk at the destination even briefly, Cadence's DD caches
"this cellview is being edited by someone else" and subsequent
`dbOpenCellViewByType('a')` calls silently return nil, making every
rebind fail.

`rsync -a --exclude='*.cdslck' --exclude='*.cdslck.*' --exclude='*%'`
filters at source — the junk never touches destination disk.

### 4. Copy whole cell directory, not per-view

`cp -r srclib/cell/schematic dstlib/cell/schematic` fails silently
when `dstlib/cell/` doesn't exist yet. rsync with trailing slashes
(`src/ dst/`) creates the parent.

### 5. Configs may not exist; patching must be conditional

Some TBs bind their maestro directly to `schematic` (no config view
at all). `patch_expand_cfg` probes and skips cleanly in that case.

### 6. Nested SKILL with `let` + `if/when` + `return` crashes silently

SKILL's `return` inside deep `let/when/if` branches doesn't always
unwind properly. Use explicit `if/then/else` with a `status`
variable. Flat `let + when` inside `foreach` is safe though — that's
what the batched `rebind_all_in_cell` relies on. The harder failure
mode to avoid is `return` from nested branches.

### 7. Bridge's `\n` handling is non-deterministic; separate records with `;;`

`virtuoso-bridge-lite`'s response serializer sometimes returns a
SKILL `sprintf(nil "%s\\n" ...)` as literal backslash-n, sometimes
converts newlines to single spaces. The same exact SKILL code can
return different separators across calls. A parser that splits on
`\\n` then silently returns one giant line as a single record, so
`stale_instances` underreports and rebind silently misses ~40% of
its work while still logging `✓ clean`. Emit multi-record SKILL
output with a dedicated separator like `;;` that's opaque to any
whitespace rewrite.

### 8. Walk hierarchy via `instHeaders`, not `instances + inst~>master`

`foreach(inst cv~>instances when(inst~>master ...))` skips any inst
whose master can't be resolved at open time — e.g. a Verilog-A-only
child cell referenced from the parent as `symbol`, where Cadence
fails the lookup and `inst~>master` is nil. Those insts silently
drop out of scan/stale lists. `cv~>instHeaders` carries the
declared `(libName, cellName, viewName)` triple regardless of
resolvability, so every declared ref is visible.
Both `scan_hierarchy` and `list_instances` use the instHeaders path.

### 9. Prop snapshot: use `p~>valueType`, never `p~>type`

On IC6.1.8 every dbProp's `~>type` slot returns nil (real slot is
`~>valueType` returning `"string" | "int" | "float" | "boolean" | "ILList"`).
Accessor list via `p~>?`: `(cellView objType prop enum name object
range value valueType assocTextDisplays)`. A naive prop-copy that
reads `~>type` captures nothing AND triggers
`*Error* fprintf/sprintf: ... argument #2 is nil` when later fed
to `dbReplaceProp`.

### 10. Cadence's open-time auto-remap drops inst props silently

When `dbOpenCellViewByType` opens a freshly-rsynced dst cellview
whose insts' declared libs now have local equivalents in the dst
library (because we just copied them), Cadence rewrites those
header refs to point at the local copies — a hidden "auto-remap"
pass. During that pass some insts' `~>prop` overrides are
**silently discarded**. Empirically the loss is inst-specific and
unpredictable: two scalar insts in the same cell with the same
master-lib can behave differently; one survives, one gets wiped.
Reading props from the dst cv after the open is therefore
unreliable as a source-of-truth.

**Workaround**: capture inst-level props from the *source* cellview
(which never triggers the remap — its refs already resolve in-place)
and re-apply by inst-name to dst after rebind. This is what
`sync_props_src_to_dst` does. Only sync for insts whose master lib
is in `project_libs`: PDK/analogLib etc. insts don't trigger the
remap (the declared lib has no dst-local equivalent) so rsync's
byte-identical copy already carries their props intact — syncing
them would be wasted work and semantically wrong (not our data).

### 11. SOS-managed sources: dereference every symlink in dst, not just `master.tag`

Cliosoft SOS-managed libs (FIRAS, 2025_CMFE, ...) store `data.dm`,
`*.oa`, and other artifacts as symlinks into a shared cache
(`/home/dmanager/sos_cache/SOS_T28.cac/...`). rsync preserves the
symlinks by default. If `data.dm` lands in the dst lib still
pointing to the read-only cache, Cadence's `dbOpenCellViewByType`
in `"a"` mode succeeds in READ-mode semantics but can't commit
writes. `dbDeleteObject + dbCreateInst` then silently no-op,
rebind reports `ok=0 fail=0` with no log line, and cells end up
with stale refs. The old rule (only deref `master.tag`) was
learned on non-SOS libs; for SOS sources you must
`find {dst} -type l | while read ln; do cp --remove-destination -L
"$ln" "$ln.tmp" && mv "$ln.tmp" "$ln"; done` to replace ALL
symlinks with regular file copies before Cadence touches the lib.

### 12. Same cell name in two source libs silently collapses to first-copied

`cp_cell_dir` skips when the destination already has a cell of the
same name. If two project libs contribute a cell with the same name
(e.g. `FCT2026/L4_SWITCH_4` and `FFCT_ICTDSM/L4_SWITCH_4` both
referenced in one clone), the second source is silently skipped
and every instance that pointed to either one gets rebound to the
single dst copy. When the two sources happen to be byte-identical
(shared block drop), this is fine. When they differ, sim behavior
changes without warning. We've only observed the identical case in
real designs; if you hit a divergent collision, either rename one
source cell or sequence clones so only one variant feeds the dst.

### 14. Must `schCheck` after rebind or sim fails with "check and save"

After we flip inst masters via delete+create and re-apply props, the
cell's `extracted` view (the hierarchical netlist cache Maestro /
spectre uses) is stale — it still reflects the pre-rebind hierarchy.
`dbSave` alone doesn't refresh it. The user then opens Maestro, hits
run, and gets `Error: check and save required` on every modified
schematic. They'd have to hand-open each cell in Virtuoso and press
Check&Save before sim can start.

`schCheck(cv)` regenerates the extracted view from the schematic,
which is what "Check and Save" does. It must run on every cell we
modified.

`sync_props_batch` calls it just before its per-cell `dbSave` — free
ride since the cv is already open. **Don't remove it** even if the
`DB-270212 cellview does not exist` warnings come back: those are
schCheck recursively opening every child schematic for hierarchy
validation, and leaf cells (PDK primitives, Verilog-A blocks,
analogLib sources) legitimately don't have a schematic view. The
warnings are noise; the alternative is manual UI clicks per cell,
which is worse.

### 13. Exclude PEX-output views from rsync (`calibre_*`, `av_extracted`, `starrc_*`)

Post-layout parasitic-extraction views live inside the cell directory
alongside `schematic/` and `layout/` — e.g. `calibre_r/`, `calibre_cc/`,
`av_extracted/`, `starrc_*/`. Each can be hundreds of MB (sometimes GB)
per cell because the extracted view includes every parasitic R/C as
a separate dbProp bag. For a schematic-level library clone they have
zero value: any layout change invalidates the extraction, and the
user will re-run PEX in the new library context anyway. Excluding
them at rsync time turns a cell that would take 30s to copy into a
sub-second copy, and makes the overall clone scale with the actual
schematic/symbol/layout content rather than with the extraction
history.

Patterns currently filtered:
`--exclude='calibre_*'  --exclude='av_extracted'  --exclude='av_netlist'  --exclude='starrc_*'`

Add your site's PEX tool outputs if you use something else (e.g.
Quantus `qrc_*`, Synopsys `hspicelnetlist`, ...).

## Reference

- **`references/testbench-duplication.md`** (in this skill) — the
  deep mechanics doc: `data.dm` binary prop bag format, `maestro.sdb`
  XML surgery, SOS metadata (`*%`, symlink `master.tag`),
  `dbCopyCellView` quirks, per-step sed patterns. The tool scripts
  implement what this doc teaches.
- For general SKILL / Maestro / schematic / layout API reference,
  use the global **`virtuoso` skill**'s `references/` (maestro-skill-api,
  schematic-skill-api, layout-skill-api, etc.).
- Tool internals rely on `virtuoso-bridge-lite` primitives:
  `client.execute_skill()`, `client.run_shell_command()`,
  `client.download_file()`, `client.upload_file()`.

## Files in this skill

```
virtuoso-librarian/
├── SKILL.md
└── scripts/
    └── tb_clone/
        ├── clone_tb_full.py   (~40 lines, CLI driver)
        └── tb_clone_lib.py    (~300 lines, single-purpose helpers)
```

Each helper function in `tb_clone_lib.py` is 10-30 lines and
single-purpose — `scan_hierarchy`, `classify_pairs`, `cp_cell_dir`,
`patch_expand_cfg`, `patch_maestro_files`, `rebind_instance`,
`rebind_all_in_cell`, `clear_all_cdslck_in_lib`. Read the docstrings
before modifying; they encode the "why" for each constraint above.

## Typical failure modes and recoveries

| Symptom | Cause | Fix |
|---|---|---|
| `rebind in X: ok=0 fail=N` | Stale `.cdslck` at destination | `clear_all_cdslck_in_lib(client, dst_lib)` then rerun; check source library for locks you didn't know about |
| `STALE remaining in X: [...]` shows a cell whose lib isn't in `project_libs` | The cell was in a library not classified as project (e.g., an IP drop not matching patterns) | Either add the lib to `_EXTERNAL_PATTERNS` (if it's really a PDK/IP-drop) or to your project set (will then get copied) |
| "no-new-master" | Target cell wasn't copied, OR a required view (usually `symbol`) missing at destination | Check `ddGetObj(dst_lib cell)~>views~>name`; rerun the copy step for that specific cell |
| 30+ PDK-named cells in destination | `is_external_lib` filter let them through | Hotfix: `rm -rf` them, extend `_EXTERNAL_PATTERNS`, rerun |
| Scripts see fewer project cells than expected | Source lib not in `cds.lib` → scan can't descend into its cells | Add library definitions to `cds.lib`, then rerun scan (tool's `ddReleaseObj(ddGetLibList())` idiom forces reload) |

## Related workflow: history cleanup

After packaging, the destination maestros still carry per-run history
pointers in `maestro.sdb` and auto-saved states in `test_states/`.
These are harmless but clutter the history picker. If the user wants
a clean package, use the companion cleaner — see
`virtuoso` skill's `references/testbench-duplication.md` for the
"clean only the latest history" approach, or ask; a similar
`clean_maestro_history.py` exists in project logs from the same
session.
