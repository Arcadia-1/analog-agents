# Duplicate a Testbench Cell (Same or Different Library)

Workflow for cloning an existing testbench — schematic + config + maestro —
to a new cell name, **same library or a different one**. The mechanism is
file-level copy plus a couple of targeted text patches. Both same-lib and
cross-lib cases share the same flow; the only extra work for cross-lib is
one additional substitution (the library name).

> **Shortcut for the full cross-lib-with-DUT-hierarchy case:** this
> skill bundles `../scripts/tb_clone/clone_tb_full.py`, which
> encapsulates everything below plus multi-level rebind:
> ```
> python <this-skill>/scripts/tb_clone/clone_tb_full.py SRC_LIB SRC_CELL DST_LIB
> ```
> This doc is the **mechanics reference** (SKILL API quirks, file
> formats, SOS handling) the tool is built on. Use the manual
> procedure below when you need a different shape (rename in-place,
> partial copy, etc.) or want to understand what the tool does
> under the hood.

## Why not rebuild from scratch

If you already have a working TB, **do not** rebuild it via
`schematic.edit()` + `maeCreateTest` / `maeSetAnalysis` / `maeAddOutput`.
That path silently drops fidelity:

- Plot window layout, spec ordering, spec targets
- Save-all / save-node preferences per analysis
- Fine-grained CDF instance params that weren't explicitly scripted
- Maestro corner definitions, per-corner variable overrides
- Output expressions (`dB20(VF(x)/VF(y))`, `phaseMargin(...)`, etc.)

`dbCopyCellView` + shell `cp` + targeted sed preserves the sdb verbatim.
Start there. Only reach for "rebuild" when the source is unrecoverable.

## The three views, three copy mechanisms

| View | Mechanism | Why |
|------|-----------|-----|
| `schematic` | `dbCopyCellView` | Standard DFII cellview |
| `config` | shell `cp -r` + text patch | CDB, not db; `dbCopyCellView` returns nil |
| `maestro` | shell `cp -r` + text patch | SDB (XML), not db; `dbCopyCellView` returns nil |

`dbCopyCellView` on config or maestro **silently returns nil** — no error
raised. You must shell-cp those directories.

## Procedure

Parameters used below:

```python
SRC_LIB = "PLAYGROUND_AGENTS"; SRC = "_TB_CMP_PNOISE"
DST_LIB = "PLAYGROUND_LLM";    DST = "_TB_CMP_PNOISE_COPY"
# Same-lib case: DST_LIB == SRC_LIB
```

### 1. Sanity check

```python
r = client.execute_skill(f'ddGetObj("{SRC_LIB}" "{SRC}")~>views~>name')
# e.g. ("maestro" "schematic" "config")

r = client.execute_skill(f'if(ddGetObj("{DST_LIB}") "EXISTS" "missing")')
assert r.output.strip('"') == "EXISTS"

r = client.execute_skill(f'if(ddGetObj("{DST_LIB}" "{DST}") "EXISTS" "free")')
assert r.output.strip('"') == "free"
```

### 2. Copy schematic via SKILL

```python
r = client.execute_skill(f'''
let((src new)
  src = dbOpenCellViewByType("{SRC_LIB}" "{SRC}" "schematic" nil "r")
  new = dbCopyCellView(src "{DST_LIB}" "{DST}" "schematic" nil)
  dbClose(src)
  when(new dbClose(new))
  if(new "OK" "FAIL"))
''')
assert r.output.strip('"') == "OK"
```

This creates `{DST_LIB}/{DST}/schematic/` on the filesystem and registers
the new cell in the destination library.

### 3. Copy config + maestro directories via shell

```python
src = f"/path/to/{SRC_LIB}/{SRC}"   # from ddGetObj(SRC_LIB, SRC)~>readPath
dst = f"/path/to/{DST_LIB}/{DST}"   # from ddGetObj(DST_LIB)~>readPath + "/" + DST

# Use rsync with --exclude so known-harmful files never transfer.
# DON'T use `cp -r` and then clean up — the race lets Cadence see the
# stale lock before you remove it, after which dbOpenCellViewByType('a')
# silently returns nil and every rebind call fails.
client.run_shell_command(
    f"rsync -a "
    f"--exclude='*.cdslck' --exclude='*.cdslck.*' --exclude='*%' "
    f"{src}/config/ {dst}/config/ && "
    f"rsync -a "
    f"--exclude='*.cdslck' --exclude='*.cdslck.*' --exclude='*%' "
    f"{src}/maestro/ {dst}/maestro/")

# Post-copy cleanup — for things rsync-exclude can't handle:
client.run_shell_command(f'''
    # (c) SOS cache symlinks for master.tag — replace with real file
    for mt in {dst}/config/master.tag {dst}/maestro/master.tag; do
      if [ -L "$mt" ]; then
        content=$(cat "$mt")
        rm "$mt"
        printf '%s\\n' "$content" > "$mt"
      fi
    done
    # (d) SOS-owned files come over as r--r--r--. Restore owner write.
    chmod -R u+w {dst}
    # (e) old run history from the source TB — those Interactive.N.* files
    #     belong to the ORIGINAL cell's sdb, not the clone. Cadence will
    #     happily display them in the history picker if you keep them,
    #     misleading anyone who opens the clone. Wipe and recreate empty.
    rm -rf {dst}/maestro/results
    mkdir -p {dst}/maestro/results/maestro
''')
```

Items (a) and (b) from the previous version — `*.cdslck*` and `*%` —
are handled at copy time via rsync `--exclude`, which is strictly
better than "cp everything then delete": it never puts the junk on
disk, so there's no race window where Cadence sees the stale lock and
caches the "cellview is being edited by someone else" fact.

Each of those cleanups addresses a specific failure you'll hit if you
skip it:

- Skip `*.cdslck*` exclusion: `close_session` emits stale-lock warnings
  and later `dbOpenCellViewByType('a')` silently returns nil for every
  rebind (the most painful failure — rebind fails with no error info).
- Skip `*%` exclusion: `maeMakeEditable` refuses — Cadence sees `*%`
  and treats the view as SOS-managed-and-not-checked-out. Config view
  in particular silently stays read-only.
- Skip (c): `master.tag` still points at someone else's
  `~/sos_cache/.../FIRAS#_tb_L3_FCT_v6#config_gmr_9820_sospack/PACK/...`.
  Cadence follows the symlink on read; if that cache is pruned or
  permissions change, the view becomes unreadable. Snapshot the
  content as a plain file so the clone is self-contained.
- Skip (d): every file copied from the SOS worktree is `r--r--r--`
  (SOS's "checked in" state). Even with correct ownership you can't
  save edits.
- Skip (e): the clone inherits the source's full run history
  (`results/maestro/Interactive.*.{log,msg.db,rdb}`, possibly hundreds
  of MB). These files reference the source's test name / sdb
  structure, not the clone's. They don't break new runs (Cadence
  allocates a fresh `Interactive.N` after scanning existing files),
  but they pollute the history picker with runs from a different
  testbench and waste disk space.

Identifying an SOS source: `ls -la src/{config,schematic}/master.tag`
— if it's a symlink into a path containing `sos_cache` or
`#_sospack`, you're cloning from SOS and all four cleanups matter.

### 4. Refresh the destination library index

```python
client.execute_skill(f'ddSyncWriteLock(ddGetObj("{DST_LIB}"))')

r = client.execute_skill(f'ddGetObj("{DST_LIB}" "{DST}")~>views~>name')
# ("maestro" "schematic" "config")
```

Skip this and Library Manager won't show the new views until Virtuoso
restarts.

### 5. Patch `config/expand.cfg`

The config file has exactly two refs to the old cell (+ the old lib, if
cross-lib):

```
config {SRC};
design {SRC_LIB}.{SRC}:schematic;
```

Use `sed -i` in one shot — this is the recommended path. Pick a delimiter
(`#` below) that doesn't appear in either library or cell name to avoid
escape noise:

```python
client.run_shell_command(
    f"sed -i "
    f"-e 's#config {SRC};#config {DST};#g' "
    f"-e 's#design {SRC_LIB}\\.{SRC}:schematic;#design {DST_LIB}.{DST}:schematic;#g' "
    f"{dst}/config/expand.cfg"
)
```

For same-lib (`DST_LIB == SRC_LIB`), the second substitution still works
— it just swaps in the identical lib name.

### 6. Patch `maestro/maestro.sdb`

Two substitutions:

1. **Cell name everywhere**: `{SRC}` → `{DST}`, ~10-30 occurrences
   (authoritative design bindings + historical breadcrumb paths).
2. **Library name in XML bindings only** (cross-lib only):
   `<value>{SRC_LIB}</value>` → `<value>{DST_LIB}</value>`.

Crucial: for #2, substitute **only inside `<value>` tags**, not raw
`{SRC_LIB}` strings. The sdb also holds references to other libraries as
sub-cells (e.g. `<value>Async_SAR_11b</value>`), and URL-path strings
that may contain `{SRC_LIB}` as a path segment. You don't want to touch
those.

#### Method A (recommended): remote `sed`

For both substitutions — simple literal replacement, idempotent enough
for a one-shot clone:

```python
# Substitution 1: cell name (runs on all occurrences)
# Substitution 2: lib name — ONLY in <value> tags
client.run_shell_command(
    f"sed -i "
    f"-e 's#{SRC}#{DST}#g' "
    f"-e 's#<value>{SRC_LIB}</value>#<value>{DST_LIB}</value>#g' "
    f"{dst}/maestro/maestro.sdb"
)
```

Zero scp, zero local artifacts. Works for this case because neither cell
name nor lib name contains `!`, `/`, `#`, or any other csh-hostile char.

**If you need to re-run**, sed will turn `{DST}` into `{DST}_2_suffix`
style concatenations. For one-shot duplication that's fine. For
idempotent flows, see Method B.

#### Method B: upload a Python patcher, run it remotely

Use when you need Perl-style regex (negative lookahead for idempotency,
backreferences, multiline) that basic POSIX sed can't express:

```python
patcher = r'''
import re, sys
p, src, dst, src_lib, dst_lib = sys.argv[1:6]
t = open(p, "r", encoding="utf-8").read()
t = re.sub(rf"{re.escape(src)}(?!{re.escape(dst[len(src):])})", dst, t)   # idempotent
if src_lib != dst_lib:
    t = t.replace(f"<value>{src_lib}</value>", f"<value>{dst_lib}</value>")
open(p, "w", encoding="utf-8").write(t)
'''
client.upload_text(patcher, "/tmp/patch_sdb.py")
client.run_shell_command(
    f"python3 /tmp/patch_sdb.py {dst}/maestro/maestro.sdb "
    f"'{SRC}' '{DST}' '{SRC_LIB}' '{DST_LIB}'"
)
```

Small script upload + one shell exec. Python regex is unrestricted.

#### Method C (last resort): download-edit-upload

Only when you need **local verifiability**: count substitutions before
committing, produce a diff, or keep a local backup. Has real overhead
(two scp trips for a potentially multi-MB sdb) and leaves local
artifacts.

```python
import re, shutil
client.download_file(f"{dst}/maestro/maestro.sdb", "tmp/sdb.edit")
text = open("tmp/sdb.edit", "r", encoding="utf-8").read()
before = text.count(SRC)
new = re.sub(rf'{re.escape(SRC)}(?!_COPY)', DST, text)
if SRC_LIB != DST_LIB:
    new = new.replace(f"<value>{SRC_LIB}</value>",
                      f"<value>{DST_LIB}</value>")
print(f"cell subs: {before} → {new.count(DST)} (orphans: "
      f"{len(re.findall(rf'{re.escape(SRC)}(?!_COPY)', new))})")
shutil.copy("tmp/sdb.edit", "tmp/maestro.sdb")   # rename before upload!
open("tmp/maestro.sdb", "w", encoding="utf-8", newline="").write(new)
client.upload_file("tmp/maestro.sdb", f"{dst}/maestro/maestro.sdb")
```

### 6b. Patch the other text files under `maestro/` — NOT just `maestro.sdb`

`maestro.sdb` alone is not enough. The cellview also has auxiliary XML
files that encode the current active test, saved test states, etc.
Cadence re-reads these on open; if they still reference `{SRC}` when
the sdb says `{DST}`, `maeGetSetup` returns the test name but
`maeGetEnabledAnalysis` / `maeGetTestOutputs` return **nil**.

Files that need the same cell-name substitution:

- `maestro/active.state` — XML describing the currently-active test
  (analyses, vars, outputs). Test names here embed `{SRC}`.
- `maestro/test_states/*.state` — one per saved named state. Same
  embedding as `active.state`.
- `maestro/data.dm` — **skip, see next block** — DO NOT sed.

```python
client.run_shell_command(
    f"sed -i 's#{SRC}#{DST}#g' "
    f"{dst}/maestro/active.state "
    f"{dst}/maestro/test_states/*.state"
)
```

Results/history files (`maestro/results/**/*.rdb|*.log|*.msg.db`) are
SQLite/binary and contain old paths, but Cadence treats them as
breadcrumbs only — it walks `{dst}/maestro/results/maestro/` at open
time and rebuilds the history list. Leave them alone.

### 6c. Replace — don't sed — `maestro/data.dm`

`data.dm` is a **DFII binary property bag** (magic `gE# \x01` /
`0x01234567` LE). It stores view-level properties like
`viewSubType=maestro`, `testName=<test>`, tool version, build stamp.
Format:

```
+0x00  magic 67 45 23 01 + version fields (LE16 major.minor = 5.3)
+0x10  descriptor table: 8-byte LE words (mix of absolute in-file
       offsets, property tag IDs, -1 sentinels)
...
+0x5xx env/tool pool: tool version, build stamp, unix timestamps
+0x7xx user property pool: "viewSubType\0maestro\0testName\0<name>\0"
       — tightly NUL-terminated, NOT individually 8-byte padded
```

The descriptor table stores **absolute offsets**. If you sed a string
in the pool and its length changes, every subsequent offset is wrong.
Cadence then reports:

```
*WARNING* (DB-260009): dbOpenBag: Fail to open prop. bag for 'maestro' in 'r' mode
*WARNING* (DB-260009): dbOpenBag: Fail to open prop. bag for 'maestro' in 'a' mode
```

**Fix**: copy the source's `data.dm` verbatim — don't rewrite it. The
`testName` string inside will still point at the old cell's test name,
but that's harmless metadata: Cadence treats `active.state` / the sdb
as authoritative and uses the filesystem path for the cell identity.

```python
client.run_shell_command(f'cp {src}/maestro/data.dm {dst}/maestro/data.dm')
```

If you already ran a bulk `sed` over the maestro tree and see
DB-260009, the fix is the same — overwrite `data.dm` with the source's
copy. No need to patch the sdb again.

### 7. Verify

```python
from virtuoso_bridge.virtuoso.maestro import open_session, close_session

sess = open_session(client, DST_LIB, DST)   # background, no GUI
r = client.execute_skill(f'maeGetSetup(?session "{sess}")')
# Lists test names, session opens without errors

# Critical sanity check: analyses + outputs must resolve.
# If either returns nil, active.state / test_states weren't patched.
test = r.output.strip('"()').split()[0].strip('"')
r = client.execute_skill(f'maeGetEnabledAnalysis("{test}" ?session "{sess}")')
assert r.output.strip() not in ("", "nil"), "active.state probably still has {SRC}"

close_session(client, sess)
```

Or eyeball the design binding in the sdb:

```python
# Should show DST and DST_LIB as siblings under <option>cell / <option>lib
client.run_shell_command(
    f"grep -A1 '<option>cell\\|<option>lib' {dst}/maestro/maestro.sdb | head -20"
)
```

Or open the GUI:

```python
from virtuoso_bridge.virtuoso.maestro import open_gui_session
open_gui_session(client, DST_LIB, DST)
```

Confirm the design-binding row shows `{DST_LIB}/{DST}/config`.

## Cross-lib with full DUT hierarchy (the "package a design" case)

When the goal is **"make DST_LIB fully self-contained so the TB can be
simulated without the original libs"**, the basic procedure isn't
enough — every cell in the DUT hierarchy (all sub-circuits the TB's
config pulls in) must also be copied, AND every instance reference
must be rebound to point at the copies.

### The additional work on top of the basic flow

1. **Enumerate hierarchy**: walk the TB schematic recursively, collect
   every reachable `(lib, cell)` via `inst~>master`. Classify each:
   - **External** (analogLib / basic / `tsmc*` / `tcbn*` / any PDK) —
     keep reference, never copy.
   - **Project-owned** — must be copied to DST_LIB.

2. **Copy each project cell** with `cp -r` of the WHOLE cell dir (not
   per-view — per-view `cp` into a missing parent dir fails silently).
   Apply the same SOS / lock / `chmod` cleanup as for the TB.

3. **Multi-level rebind.** OA stores instance master references as
   `(lib, cell, view)` triples. `cp -r` preserves them verbatim, so
   every copied cell's schematic still points at source lib. For
   every copied cell (the TB + every project DUT) you must rebind
   all instances whose `master~>libName` is a source project lib.

4. **`dbReplaceHierInst` / `dbReplaceMaster` / `dbSetInstMaster` /
   `inst~>libName = "NewLib"` do not work in IC6.1.8.** The only
   reliable mechanism is delete + recreate:
   ```skill
   xy     = inst~>xy
   orient = inst~>orient
   new_master = dbOpenCellViewByType(dst_lib dut_cell view nil "r")
   dbDeleteObject(inst)
   dbCreateInst(cv new_master inst_name xy orient)
   ```
   Bus-syntax names (`I21<1:0>`, `I127<20:1>`) pass as strings.
   The instance usually binds to `symbol` view (not `schematic`) —
   read `inst~>master~>viewName` before rebinding.

5. **SOS-locked source files bite twice.** Source schematics often
   have `*.cdslck.<distro>.<host>.<pid>` from other users. These
   come along with `cp -r`, and if left in place, `dbOpenCellViewByType`
   with mode `"a"` returns nil — rebind silently fails. Nuke all
   `*.cdslck*` across the destination lib before attempting any rebind.

6. **Filter external libs by pattern, not name list.** New std-cell /
   IP libs crop up (TSMC adds HVT / LVT variants, different track
   heights, PDK revs). Hardcoding names (`tcbn28hpcplusbwp12t30p140`)
   misses variants. Use regex: `^tcbn\d+`, `^tsmc`, `^smic`, `^gf\d+`.

### Canonical tool

This skill's bundled `../scripts/tb_clone/` implements all six
points. Helper functions are one-purpose-each (`scan_hierarchy`,
`classify_pairs`, `cp_cell_dir`, `patch_expand_cfg`,
`patch_maestro_files`, `rebind_instance`, `rebind_all_in_cell`,
`clear_all_cdslck_in_lib`).
`clone_tb_full(client, src_lib, src_cell, dst_lib)` composes them.

Worked example: 2026-04-20 session cloned 7 TBs from `PLAYGROUND_AGENTS`
+ 1 from `GM2026` (inclusive of each's DUT hierarchy — up to
5-deep for `tb_L2_FCG_CT`) into `Noisy_Past_Design`, leaving only
`analogLib` / `basic` / `tsmcN28` / `tcbn28*` as external references.

## Gotchas

### `dbCopyCellView` silently returns nil for non-db views

No exception, no log message — just a quiet nil. Always check the
return value for `schematic`/`symbol` views, and don't bother calling it
at all for `config`/`maestro`.

### csh eats `!` in `run_shell_command`

`client.run_shell_command(cmd)` is implemented as `csh("...")` in SKILL.
csh treats `!` as history expansion and silently mangles any command
containing it before executing. Perl's negative-lookahead (`(?!foo)`)
will not work as written.

Avoid `!` entirely — either rephrase without lookahead (plain sed), or
upload a patcher script (Method B) so the shell never sees the regex
text.

### `upload_file` preserves the **source** basename

`client.upload_file(local, remote)` tars the file at `local`, extracts
into `dirname(remote)`, and keeps the source basename. If your local
file is named `sdb_edit.xml` but the target is `maestro.sdb`, you'll
end up with `sdb_edit.xml` in the target directory, not the intended
`maestro.sdb`.

**Rename locally first:**

```python
import shutil
shutil.copy("tmp/sdb.edit", "tmp/maestro.sdb")
client.upload_file("tmp/maestro.sdb", f"{dst}/maestro/maestro.sdb")
```

### `run_shell_command` stdout is not returned to Python

It returns `t` (success) or `nil` (fail) — stdout goes to the CIW log,
not back to Python. For debug / verification, either:

- Redirect to a file and `download_file` it
- Read the file via SKILL `infile` / `gets` / `close`
- Re-probe filesystem state via `getDirFiles` / `isFile` / `ddGetObj`

### `open_gui_session` matches window titles by substring

If `DST` is a prefix or substring of `SRC` (e.g. cloning
`_TB_AMP_5T_D2S_DC_AC` → `_TB_AMP_5T_D2S_DC`), and a GUI session for
`SRC` is still open, `open_gui_session(..., DST)` will see the
substring match and silently **reuse the `SRC` session**. You'll get
back the wrong session and `maeGetEnabledAnalysis` on the new test
name returns nil.

Before verifying / editing a freshly-cloned maestro, close any GUI
session whose title contains `SRC`. Example:

```python
# Find and close the source GUI session first
r = client.execute_skill(
    f'let((found) '
    f'foreach(s maeGetSessions() '
    f'  when(and(null(found) maeGetSetup(?session s) '
    f'           equal(car(maeGetSetup(?session s)) "{SRC_TEST_NAME}")) '
    f'    found = s)) '
    f'found)')
src_sess = (r.output or "").strip().strip('"')
if src_sess and src_sess != "nil":
    close_gui_session(client, src_sess, save=True)
```

### Pruning analyses/outputs: edit `active.state` XML, not SKILL

`maeSetAnalysis(?enable nil)` works for disabling an analysis, but
`maeDeleteOutput` is finicky about the `?name` argument and silently
no-ops on some output shapes (outputs without a display `name`, only
`uniqueName`). For mass pruning, it's faster and more reliable to edit
`active.state` directly with lxml:

```python
from lxml import etree
tree = etree.parse(f"{dst}/maestro/active.state")
root = tree.getroot()

# Drop analyses not in keep_set
ana_container = root.find('.//analyses[@Name="analysis"]')
for ana in list(ana_container):
    if ana.tag == "analysis" and ana.get("Name") not in KEEP_ANA:
        ana_container.remove(ana)

# Drop outputList_N whose uniqueName not in keep_set, then renumber
out_list = root.find('.//field[@Name="outputList"][@Type="skillList"]')
kept = []
for sub in list(out_list):
    if sub.tag == "field" and sub.get("Name", "").startswith("outputList_"):
        uname_field = sub.find('./field[@Name="uniqueName"]')
        uname = (uname_field.text or "").strip().strip('"').replace(r'\"', '"')
        if uname in KEEP_OUT:
            kept.append(sub)
        else:
            out_list.remove(sub)
for i, elem in enumerate(kept):                      # renumber sequentially
    elem.set("Name", f"outputList_{i}")
    idx = elem.find('./field[@Name="index"]')
    if idx is not None: idx.text = str(i + 1)

tree.write(f"{dst}/maestro/active.state", xml_declaration=True, encoding="UTF-8")
```

Then `upload_file` back (remember to rename locally to `active.state`
first). Cadence reloads the new state on next open — no session
acrobatics required.

### Stale history paths in the new sdb are harmless

After substitution, URL-path fragments like
`/path/to/OLD_LIB/NEW_CELL/maestro/results/maestro/Interactive.N.log`
may point at directories that never existed. This is fine. Cadence
rediscovers histories by walking `{cellview_path}/results/maestro/` at
open time; the breadcrumb paths in the sdb are informational, not
load-bearing. New simulations write to the correct `{DST_LIB}/{DST}/`
tree automatically.

### Cross-lib: other-lib references must survive

The sdb may reference cells from libraries *other* than `SRC_LIB` — e.g.
sub-cells pulled in by the testbench (`<value>Async_SAR_11b</value>`,
`<value>tsmcN28</value>`). Your lib substitution must scope to
`<value>{SRC_LIB}</value>` **exactly**, not a global
`{SRC_LIB}` replace, or you'll mis-point sub-cells.

### Same-lib cloning only needs substitution #1

Skip the `<value>SRC_LIB</value>` replacement when `DST_LIB == SRC_LIB`.
The library name is already correct after file copy.

## Reference substitution counts

Typical cross-lib duplication of a testbench with ~6 analyses + ~10
historical runs:

| File | Action | `{SRC}` → `{DST}` subs | `<value>{SRC_LIB}</value>` → `<value>{DST_LIB}</value>` subs |
|------|--------|-----------------------|------------------------------------------------------------|
| `config/expand.cfg`          | `sed`      | 2      | 1 (inside the `design` line) |
| `maestro/maestro.sdb`        | `sed`      | 10-30  | 6-12 (one per test's `<option>lib` binding + aux) |
| `maestro/active.state`       | `sed`      | 10-50  | — (design lib in a separate field; patch with XML editor if cross-lib) |
| `maestro/test_states/*.state`| `sed`      | 5-20/file | — (same as above) |
| `maestro/data.dm`            | **`cp` from SRC** | — | — (binary prop bag; sed corrupts offsets → DB-260009) |
| `maestro/maestro.sdb.cdslck` | **`rm`**   | — | — (stale source lock) |
| `maestro/results/**`         | **`rm -rf` + recreate empty** | — | — (belong to source's run history; inheriting pollutes history picker + wastes disk) |

If counts are dramatically higher (100+), the sdb likely contains
Monte-Carlo or sweep bloat — still safe to substitute wholesale, just
confirms you want the full replace.
