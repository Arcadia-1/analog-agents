"""Helper functions for cloning a testbench + its DUT hierarchy across libs.

Every function is small and single-purpose. The CLI driver
(clone_tb_full.py) composes them into the full flow.

See references/testbench-duplication.md in this skill for the full
workflow, hard-earned gotchas, and rationale behind each helper.
"""
import os
import re
import tempfile
from virtuoso_bridge import VirtuosoClient


# Explicit external libs (Cadence built-ins + custom).
_EXTERNAL_EXPLICIT = {
    "analogLib", "basic", "cdsDefTechLib",
    "functional", "ahdlLib", "rfLib", "cmos_sch",
    "US_8ths",   # rule libs
}

# Pattern-based external libs. Anything matching these is treated as
# a PDK / standard-cell / IP-drop library and kept as external reference.
# Adjust if your fab uses different conventions.
_EXTERNAL_PATTERNS = [
    re.compile(r"^tsmc(?:N?\d+)?", re.I),        # tsmcN28, tsmc16, tsmc...
    re.compile(r"^tcbn\d+", re.I),               # tcbn28*, tcbn40* (TSMC std cells)
    re.compile(r"^smic", re.I),                  # SMIC PDK
    re.compile(r"^gf\d+", re.I),                 # GlobalFoundries
    re.compile(r"^tpcn\d+", re.I),               # TSMC dual-port SRAM lib
    re.compile(r"BWP\d+T\d+P\d+(?:[A-Z]+)?$"),   # TSMC std cell suffix (rare as lib, safety)
]


def is_external_lib(name):
    """True if `name` is a PDK / std-cell / IP lib that should NOT be copied."""
    if name in _EXTERNAL_EXPLICIT:
        return True
    return any(p.search(name) for p in _EXTERNAL_PATTERNS)


# Alias for back-compat; prefer is_external_lib().
EXTERNAL_LIBS = _EXTERNAL_EXPLICIT


# Where to stash tiny temporary files we download for probing.
# Safe across platforms (Windows + Linux + no-PWD-permissions cases).
_TMP = tempfile.gettempdir()


# ── SKILL primitives ────────────────────────────────────────────────────

def sk(client, expr, timeout=30):
    """Run SKILL, return stripped output (may include trailing quotes)."""
    return (client.execute_skill(expr, timeout=timeout).output or "").strip()


def lib_path(client, lib):
    return sk(client, f'ddGetObj("{lib}")~>readPath').strip('"')


def cell_exists(client, lib, cell):
    return sk(client, f'if(ddGetObj("{lib}" "{cell}") "Y" "N")').strip('"') == "Y"


# ── hierarchy scan ──────────────────────────────────────────────────────

def scan_hierarchy(client, top_lib, top_cell):
    """Walk schematic instHeaders recursively, return list of (lib, cell).

    Uses `cv~>instHeaders` (declared refs) rather than
    `cv~>instances + inst~>master` (needs master to resolve). A child
    cell's symbol view may fail to open at scan time (Verilog-A
    blocks with broken deps, cells in non-tech libs that the current
    session can't resolve), making `inst~>master` nil — scan would
    then skip the reference entirely and miss the whole subtree.
    instHeaders carry the (libName, cellName, viewName) triple
    regardless of resolvability, so we always see every declared ref.

    Still guards the parent-schematic open behind a view-existence
    probe so leaf cells (PDK primitives, ahdlLib/analogLib sources,
    Verilog-A blocks) don't emit DB-270212 warnings.
    """
    raw = sk(client, f'''
let((visited queue result)
  visited = makeTable('v nil)
  result = nil
  queue = list(list("{top_lib}" "{top_cell}"))
  while(queue
    let((top lib cell key obj cv)
      top = car(queue) queue = cdr(queue)
      lib = car(top) cell = cadr(top)
      key = strcat(lib "/" cell)
      unless(visited[key]
        visited[key] = t
        result = cons(top result)
        obj = ddGetObj(lib cell)
        cv = if(and(obj member("schematic" obj~>views~>name))
                 dbOpenCellViewByType(lib cell "schematic" nil "r")
                 nil)
        when(cv
          foreach(ih cv~>instHeaders
            let((child_key)
              child_key = strcat(ih~>libName "/" ih~>cellName)
              unless(visited[child_key]
                queue = cons(list(ih~>libName ih~>cellName) queue))))
          dbClose(cv)))))
  reverse(result))
''', timeout=60)
    return re.findall(r'\("([^"]+)"\s+"([^"]+)"\)', raw)


def classify_pairs(pairs):
    """Split (lib,cell) list into (project_cells, external_cells)."""
    project, external = [], []
    for lib, cell in pairs:
        (external if is_external_lib(lib) else project).append((lib, cell))
    return project, external


# ── instance inspection + rebind ────────────────────────────────────────

def list_instances(client, lib, cell, view="schematic"):
    """Return [(name, decl_lib, decl_cell, decl_view), ...] for every
    instance in this cellview, based on the `instHeader` declared
    references rather than the resolved `inst~>master`.

    Why instHeaders not instances+master: if a child cell lacks the
    declared view (e.g. Verilog-A block with only a `veriloga` +
    `symbol` view but declared from its parent as `symbol`), Cadence
    can still fail to populate `inst~>master` — it returns nil.
    `foreach(inst cv~>instances when(inst~>master ...))` then drops
    those insts, and `stale_instances` never sees them, so rebind
    silently skips perfectly-valid refs that only get detected in
    the post-rebind verify pass. Declaring through `instHeaders` sees
    every inst regardless of master resolvability.

    Records are separated by `;;` rather than `\\n`: the bridge's
    response serializer is inconsistent about newline handling —
    sometimes emits literal backslash-n, sometimes a single space.
    `;;` survives both.
    """
    raw = sk(client, f'''
let((obj cv out)
  obj = ddGetObj("{lib}" "{cell}")
  cv = if(and(obj member("{view}" obj~>views~>name))
           dbOpenCellViewByType("{lib}" "{cell}" "{view}" nil "r")
           nil)
  out="" when(cv
    foreach(ih cv~>instHeaders
      foreach(inst ih~>instances
        out=strcat(out sprintf(nil "%s|%s|%s|%s;;"
                               inst~>name ih~>libName
                               ih~>cellName ih~>viewName))))
    dbClose(cv)) out)
''', timeout=60)
    result = []
    for ln in raw.strip('"').split(";;"):
        parts = ln.strip().split("|")
        if len(parts) == 4:
            result.append(tuple(parts))
    return result


def stale_instances(client, lib, cell, project_libs, view="schematic"):
    """Instances whose master libName is in project_libs."""
    return [i for i in list_instances(client, lib, cell, view)
            if i[1] in project_libs]


def rebind_instance(client, parent_lib, parent_cell, iname,
                    dst_lib, dut_cell, view):
    """Rebind one instance via delete-and-recreate (only reliable way in IC6.1.8).
    Returns status: 'ok' | 'no-cv' | 'no-inst' | 'no-new-master' | 'create-failed'.

    Why delete+recreate: `dbReplaceHierInst`, `dbReplaceMaster`,
    `dbSetInstMaster`, `inst~>libName = X`, and the schematic Property
    Editor's Library Name field all silently no-op on IC6.1.8. Even
    the official Cadence migration script (CCSmigrateDesign.il) keeps
    this same delete-and-recreate as its `recreateInst=="Yes"` branch.

    Prop preservation is NOT handled here. Two failure modes made
    per-rebind prop copy unreliable:
      (a) On `dbOpenCellViewByType` of a freshly-rsynced cellview,
          Cadence's open-time auto-remap logic drops some insts'
          `~>prop` overrides (observed for e.g. STZ_TO-linked insts in
          L1_ACTIVE — `nlAction="ignore"` present on disk, gone after
          open), so `inst~>prop` at rebind-time returns empty.
      (b) For bus-iterated instances, `dbCreateInst`'s return value
          can be a sub-instance rather than the header, so
          `dbReplaceProp` on that handle doesn't surface on the
          header's prop list.
    Prop sync is done separately by `sync_props_src_to_dst` AFTER
    rebind, reading from the stable source-library cv and writing
    back by inst name.

    Does NOT call schCheck per-inst. Finalize with `finalize_cell_check`
    once per parent after the loop (SKILL.md #6).
    """
    return sk(client, f'''
let((cv inst xy orient new_master status)
  status = "ok"
  cv = dbOpenCellViewByType("{parent_lib}" "{parent_cell}" "schematic" nil "a")
  if(null(cv) then
    status = "no-cv"
  else
    inst = car(setof(x cv~>instances equal(x~>name "{iname}")))
    if(null(inst) then
      status = "no-inst"
      dbClose(cv)
    else
      xy = inst~>xy
      orient = inst~>orient
      new_master = dbOpenCellViewByType("{dst_lib}" "{dut_cell}" "{view}" nil "r")
      if(null(new_master) then
        status = "no-new-master"
        dbClose(cv)
      else
        dbDeleteObject(inst)
        dbCreateInst(cv new_master "{iname}" xy orient)
        dbClose(new_master)
        dbSave(cv)
        dbClose(cv))))
  status)
''', timeout=60).strip('"')


def sync_props_src_to_dst(client, src_lib, dst_lib, cell, project_libs):
    """Replay each rebound inst's `~>prop` from src cellview onto dst by name.

    Runs after rebind. Reads src schematic (stable source-of-truth
    for inst-level prop overrides), builds a name→props table in
    SKILL memory, iterates dst schematic and re-applies via
    `dbReplaceProp`. Only insts whose src-side master is in
    `project_libs` are considered: PDK/analogLib/etc. insts aren't
    subject to Cadence's open-time auto-remap (their declared lib
    has no dst-local equivalent to trigger the remap), so rsync
    already carries their props intact — re-applying would be both
    wasted cycles and semantically wrong (we don't "own" PDK state).
    A MOS-heavy transistor cell has ~6000+ MOS props that all fall
    outside this scope; only a handful of block-level insts need
    sync.

    Values stay in-SKILL the whole time — types survive intact.

    Why capture-from-src instead of reading dst: `dbOpenCellViewByType`
    on a freshly-rsynced dst cellview silently drops some inst-level
    prop overrides during Cadence's open-time master auto-remap.
    Source-side reads bypass that drop entirely.
    """
    proj_list_skill = " ".join(f'"{lib}"' for lib in project_libs)
    return sk(client, f'''
let((src_cv dst_cv tbl proj touched)
  proj = makeTable('v nil)
  foreach(lib list({proj_list_skill}) proj[lib] = t)
  src_cv = dbOpenCellViewByType("{src_lib}" "{cell}" "schematic" nil "r")
  dst_cv = dbOpenCellViewByType("{dst_lib}" "{cell}" "schematic" nil "a")
  touched = 0
  when(and(src_cv dst_cv)
    tbl = makeTable('v nil)
    foreach(inst src_cv~>instances
      when(and(inst~>master proj[inst~>master~>libName])
        tbl[inst~>name] = foreach(mapcan p inst~>prop
          when(and(p~>name p~>valueType)
            list(list(p~>name p~>valueType p~>value))))))
    foreach(inst dst_cv~>instances
      let((props)
        props = tbl[inst~>name]
        when(props
          foreach(p props
            dbReplaceProp(inst nth(0 p) nth(1 p) nth(2 p)))
          touched = touched + 1)))
    dbSave(dst_cv))
  when(src_cv dbClose(src_cv))
  when(dst_cv dbClose(dst_cv))
  sprintf(nil "%d" touched))
''', timeout=120).strip('"')


def sync_props_batch(client, pairs, dst_lib, project_libs):
    """Sync inst-level props src->dst for ALL cells in one SKILL round trip,
    and `schCheck + dbSave` every touched dst cellview.

    Replaces per-cell loop of sync_props_src_to_dst. For each src inst
    whose master lib is in project_libs, capture (name valueType value)
    tuples and replay via dbReplaceProp on the dst inst with the same
    name. Returns total insts touched.

    **Why schCheck is inside this batch**: after rebind flips inst
    masters and sync rewrites props, the cell's `extracted` view is
    stale. Maestro / the netlister uses extracted, so sim fails with
    "check and save" errors until the user hand-clicks Check&Save in
    Virtuoso for every touched cell. `schCheck(dst_cv)` regenerates
    extracted from the now-correct schematic. We do it here (not in a
    separate pass) because we're already open in "a" mode and saving
    — free ride. Cost: schCheck recursively opens every child
    schematic for hierarchy validation; leaf cells without schematic
    (PDK primitives, Verilog-A blocks, analogLib sources) each emit a
    DB-270212 warning. Log noise is the tradeoff for avoiding manual
    UI clicks before every sim.
    """
    proj_skill = " ".join(f'"{lib}"' for lib in project_libs)
    jobs_skill = " ".join(
        f'list("{sl}" "{cell}")' for sl, cell in pairs)
    return sk(client, f'''
let((proj jobs total)
  proj = makeTable('v nil)
  foreach(lib list({proj_skill}) proj[lib] = t)
  jobs = list({jobs_skill})
  total = 0
  foreach(job jobs
    let((src_lib cell src_cv dst_cv tbl)
      src_lib = nth(0 job) cell = nth(1 job)
      src_cv = dbOpenCellViewByType(src_lib cell "schematic" nil "r")
      dst_cv = dbOpenCellViewByType("{dst_lib}" cell "schematic" nil "a")
      when(and(src_cv dst_cv)
        tbl = makeTable('v nil)
        foreach(inst src_cv~>instances
          when(and(inst~>master proj[inst~>master~>libName])
            tbl[inst~>name] = foreach(mapcan p inst~>prop
              when(and(p~>name p~>valueType)
                list(list(p~>name p~>valueType p~>value))))))
        foreach(inst dst_cv~>instances
          let((props)
            props = tbl[inst~>name]
            when(props
              foreach(p props
                dbReplaceProp(inst nth(0 p) nth(1 p) nth(2 p)))
              total = total + 1)))
        schCheck(dst_cv)
        dbSave(dst_cv))
      when(src_cv dbClose(src_cv))
      when(dst_cv dbClose(dst_cv))))
  sprintf(nil "%d" total))
''', timeout=300).strip('"')


def verify_no_stale_batch(client, dst_lib, parents, project_libs):
    """For every parent cell, report any instHeader still pointing at a
    project lib. One SKILL round trip for the whole parent list.
    Returns {parent: [(libName, cellName, viewName, count), ...]}.
    """
    proj_skill = " ".join(f'"{lib}"' for lib in project_libs)
    parents_skill = " ".join(f'"{p}"' for p in parents)
    raw = sk(client, f'''
let((proj out)
  proj = makeTable('v nil)
  foreach(lib list({proj_skill}) proj[lib] = t)
  out = ""
  foreach(parent list({parents_skill})
    let((cv)
      cv = dbOpenCellViewByType("{dst_lib}" parent "schematic" nil "r")
      when(cv
        foreach(ih cv~>instHeaders
          when(proj[ih~>libName]
            out = strcat(out sprintf(nil "%s|%s|%s|%s|%d;;"
              parent ih~>libName ih~>cellName ih~>viewName length(ih~>instances)))))
        dbClose(cv))))
  out)
''', timeout=120).strip('"')
    result = {p: [] for p in parents}
    for rec in raw.split(";;"):
        rec = rec.strip()
        if rec.count("|") != 4:
            continue
        parent, lib, cell, view, cnt = rec.split("|")
        result[parent].append((lib, cell, view, int(cnt)))
    return result


def finalize_cell_check(client, lib, cell):
    """Touch-open + dbSave the parent cell once after all rebinds.

    Does NOT call schCheck: schCheck recursively opens every child
    schematic for hierarchy validation, and any leaf cell without a
    schematic (PDK primitive, analogLib source, Verilog-A block) emits
    a DB-270212 warning per occurrence. rebind_instance already saves
    per-inst, so the extracted view is in a consistent state; ADE /
    the netlister will recompute the extracted view on demand the
    next time it's needed. Own execute_skill call (SKILL.md #6).
    Returns 'ok' | 'no-cv'.
    """
    return sk(client, f'''
let((cv status)
  status = "ok"
  cv = dbOpenCellViewByType("{lib}" "{cell}" "schematic" nil "a")
  if(null(cv) then
    status = "no-cv"
  else
    dbSave(cv)
    dbClose(cv))
  status)
''', timeout=60).strip('"')


# ── file-level copy + cleanup ───────────────────────────────────────────

def cp_cell_dir(client, src_lib, cell, dst_lib, is_tb=False):
    """Copy one cell dir src_lib/cell -> dst_lib/cell with the exclusion
    set below. Left here as the documented single-cell primitive;
    clone_tb_full batches all cells through cp_many_cells for speed
    (one SSH round trip instead of N).

    Excluded at copy time (rsync) rather than cleaned up after:
      *.cdslck  *.cdslck.*  — other users' / stale edit locks
      *%                    — Cliosoft SOS "not checked out" markers
      calibre_*             — Calibre DRC/LVS/PEX derived views
                              (huge — can be 100s of MB per cell —
                              and meaningless for schematic clone;
                              user will re-extract after any layout
                              edit anyway)
      av_extracted, av_netlist, starrc_*
                            — Assura / StarRC PEX output, same reason
    If the lock/SOS junk files land on disk even briefly, Cadence's
    DD caches "this cellview is being edited by someone else" and
    subsequent `dbOpenCellViewByType('a')` silently returns nil.
    rsync never lets the junk touch disk.

    Post-cp: dereference master.tag symlinks (SOS cache → real file),
    restore owner write perms (SOS sources come over r--r--r--).
    For TBs also wipe results/ and auto-run test_states snapshots.
    """
    if cell_exists(client, dst_lib, cell):
        return "exists"
    src = f"{lib_path(client, src_lib)}/{cell}"
    dst = f"{lib_path(client, dst_lib)}/{cell}"
    client.run_shell_command(
        f"rsync -a "
        f"--exclude='*.cdslck' --exclude='*.cdslck.*' --exclude='*%' "
        f"--exclude='calibre_*' --exclude='av_extracted' "
        f"--exclude='av_netlist' --exclude='starrc_*' "
        f"{src}/ {dst}/")
    client.run_shell_command(f'''
for mt in $(find {dst} -maxdepth 3 -name master.tag); do
  if [ -L "$mt" ]; then cc=$(cat "$mt"); rm "$mt"; printf '%s\\n' "$cc" > "$mt"; fi
done
chmod -R u+w {dst}
''')
    if is_tb:
        client.run_shell_command(f'''
rm -rf {dst}/maestro/results
mkdir -p {dst}/maestro/results/maestro
rm -f {dst}/maestro/test_states/Interactive.*.state
rm -f {dst}/maestro/test_states/ExplorerRun.*.state
rm -f {dst}/maestro/test_states/GlobalOpt.*.state
rm -f {dst}/maestro/test_states/MonteCarlo.*.state
''')
    return "copied"


def cp_many_cells(client, pairs, dst_lib, tb_cell=None):
    """Copy many (src_lib, cell) pairs into dst_lib in ONE SSH round trip.

    The naive per-cell cp_cell_dir does ~5 RTTs per cell (cell_exists,
    lib_path x2, rsync, post-process). For 56 cells that's ~280 RTTs
    at ~300ms each = 80+ seconds just in SSH handshake. This batches:
      - lib_path is resolved once per distinct library (SKILL batch)
      - cell_exists is resolved via one directory listing instead of
        one SKILL call per cell
      - all rsync + post-process + TB cleanup runs in a single bash
        script piped to one shell invocation
    Returns dict {cell: "copied" | "exists"}.
    """
    # Resolve paths in batch (one SKILL call per distinct lib).
    libs = sorted({l for l, _ in pairs} | {dst_lib})
    paths = {lib: lib_path(client, lib) for lib in libs}
    dst_path = paths[dst_lib]

    # Enumerate existing cells at destination via one ls.
    remote_existing = "/tmp/_tb_clone_existing.txt"
    client.run_shell_command(
        f"find {dst_path} -maxdepth 1 -mindepth 1 -type d "
        f"-printf '%f\\n' > {remote_existing}")
    local_existing = os.path.join(_TMP, "_tb_clone_existing.txt")
    client.download_file(remote_existing, local_existing)
    existing = {ln.strip() for ln in open(local_existing) if ln.strip()}

    # Build one big bash script. rsync per (src, dst) pair; then
    # one global master.tag deref + chmod pass over the whole dst_lib.
    lines = []
    result = {}
    for src_lib, cell in pairs:
        if cell in existing:
            result[cell] = "exists"
            continue
        result[cell] = "copied"
        src = f"{paths[src_lib]}/{cell}"
        dst = f"{dst_path}/{cell}"
        lines.append(
            f"rsync -a --exclude='*.cdslck' --exclude='*.cdslck.*' "
            f"--exclude='*%' --exclude='calibre_*' --exclude='av_extracted' "
            f"--exclude='av_netlist' --exclude='starrc_*' "
            f"{src}/ {dst}/")

    # Global post-process: deref ALL symlinks (master.tag, data.dm, etc.)
    # inside dst_lib. SOS-managed source libs store *.tag, data.dm, and
    # sometimes view-level .oa files as symlinks into a shared cache
    # (/home/dmanager/sos_cache/...); if those land in dst still as
    # symlinks pointing to the read-only cache, Cadence's 'a'-mode open
    # silently can't write, dbCreateInst no-ops, and rebind reports
    # 0 ok / 0 fail with no log line. Replace each symlink with a
    # regular copy of the target file (`cp --remove-destination -L`).
    lines.append(
        f"find {dst_path} -type l | while read ln; do "
        f"cp --remove-destination -L \"$ln\" \"$ln.tmp\" 2>/dev/null && "
        f"mv \"$ln.tmp\" \"$ln\"; done")
    lines.append(f"chmod -R u+w {dst_path}")

    # TB-specific wipe of maestro results + auto-run snapshots.
    if tb_cell and tb_cell not in existing:
        tb_dst = f"{dst_path}/{tb_cell}"
        lines.append(f"rm -rf {tb_dst}/maestro/results")
        lines.append(f"mkdir -p {tb_dst}/maestro/results/maestro")
        for pat in ("Interactive", "ExplorerRun", "GlobalOpt", "MonteCarlo"):
            lines.append(f"rm -f {tb_dst}/maestro/test_states/{pat}.*.state")

    # Chaining 56 rsync commands via '&&' hit a shell arg-length or
    # run_shell_command size limit and silently no-op'd. Write the
    # script to /tmp and exec it instead — one SSH round trip, no
    # length limit.
    remote_script = "/tmp/_tb_clone_copy.sh"
    local_script = os.path.join(_TMP, "_tb_clone_copy.sh")
    with open(local_script, "w", newline="\n") as f:
        f.write("#!/bin/bash\nset -e\n")
        for ln in lines:
            f.write(ln + "\n")
    client.upload_file(local_script, remote_script)
    client.run_shell_command(f"bash {remote_script}")
    return result


# ── sed patches ─────────────────────────────────────────────────────────

def patch_expand_cfg(client, dst_lib, tb_cell, project_libs):
    """Rewrite 'design <LIB>.X:view;' and 'cell <LIB>.Y binding ...' in
    expand.cfg for each project lib. Skip if no config view."""
    cfg = f"{lib_path(client, dst_lib)}/{tb_cell}/config/expand.cfg"
    probe_remote = "/tmp/_tb_clone_cfg_probe.txt"
    probe_local = os.path.join(_TMP, "_tb_clone_cfg_probe.txt")
    client.run_shell_command(
        f'[ -f {cfg} ] && echo Y > {probe_remote} || echo N > {probe_remote}')
    client.download_file(probe_remote, probe_local)
    if open(probe_local).read().strip() != "Y":
        return "no-config-view"
    exprs = []
    for slib in project_libs:
        sl = slib.replace(".", r"\.")
        exprs.append(f"-e 's#design {sl}\\.#design {dst_lib}.#g'")
        exprs.append(f"-e 's#cell {sl}\\.#cell {dst_lib}.#g'")
    client.run_shell_command(f"sed -i {' '.join(exprs)} {cfg}")
    return "patched"


def patch_maestro_files(client, dst_lib, tb_cell, project_libs):
    """sed <value>LIB</value> and 'LIB' in maestro.sdb + active.state +
    test_states/*.state for each project lib. Scoped substitution avoids
    corrupting path strings like /home/USER/.../LIB/...."""
    base = f"{lib_path(client, dst_lib)}/{tb_cell}/maestro"
    exprs = []
    for slib in project_libs:
        exprs.append(f"-e 's#<value>{slib}</value>#<value>{dst_lib}</value>#g'")
        exprs.append(f'-e \'s#"{slib}"#"{dst_lib}"#g\'')
    sed_args = ' '.join(exprs)
    client.run_shell_command(
        f"sed -i {sed_args} {base}/maestro.sdb {base}/active.state")
    client.run_shell_command(
        f"for f in {base}/test_states/*.state; do "
        f"  [ -e \"$f\" ] && sed -i {sed_args} \"$f\"; done")


# ── orchestration ───────────────────────────────────────────────────────

def clear_all_cdslck_in_lib(client, lib):
    """Remove every *.cdslck* file under the library. Defensive: called
    once before rebind in case prior failed runs left locks around."""
    path = lib_path(client, lib)
    client.run_shell_command(
        f'find {path} \\( -name "*.cdslck" -o -name "*.cdslck.*" \\) -delete')


def rebind_all_in_cell(client, parent_lib, parent_cell, project_libs,
                       dst_lib=None):
    """Batch delete+recreate every stale instance in one SKILL round trip.

    Previously rebind_instance was called per stale inst — one open,
    delete, create, save, close cycle per call. For a cell with 34
    stale insts that's 34 round trips at ~400ms each = ~13s for one
    parent. Batching opens the parent cv once, does all N rebinds
    inside a single `foreach`, and saves+closes once.

    SKILL.md #6 warned against foreach+dbDelete+dbCreate batching
    due to silent crashes — but that specifically concerned deeply
    nested `let/when/if/return`. The form below is flat `let + when`
    only, no `return`, no nested `if`, and has been validated to
    produce identical rebind results to the per-inst path.
    """
    if dst_lib is None:
        dst_lib = parent_lib
    stale = stale_instances(client, parent_lib, parent_cell, project_libs)
    if not stale:
        return 0, 0
    jobs_skill = " ".join(
        f'list("{iname}" "{dst_lib}" "{dut_cell}" "{view}")'
        for iname, _old, dut_cell, view in stale)
    out = sk(client, f'''
let((cv jobs n_ok n_fail)
  n_ok = 0  n_fail = 0
  cv = dbOpenCellViewByType("{parent_lib}" "{parent_cell}" "schematic" nil "a")
  when(cv
    jobs = list({jobs_skill})
    foreach(job jobs
      let((iname dst_lib dut_cell view inst xy orient nm)
        iname = nth(0 job)  dst_lib = nth(1 job)
        dut_cell = nth(2 job)  view = nth(3 job)
        inst = car(setof(x cv~>instances equal(x~>name iname)))
        when(null(inst) n_fail = n_fail + 1)
        when(inst
          xy = inst~>xy
          orient = inst~>orient
          nm = dbOpenCellViewByType(dst_lib dut_cell view nil "r")
          when(null(nm) n_fail = n_fail + 1)
          when(nm
            dbDeleteObject(inst)
            dbCreateInst(cv nm iname xy orient)
            dbClose(nm)
            n_ok = n_ok + 1))))
    dbSave(cv)
    dbClose(cv))
  sprintf(nil "%d|%d" n_ok n_fail))
''', timeout=120).strip('"')
    try:
        ok, fail = out.split("|")
        return int(ok), int(fail)
    except (ValueError, AttributeError):
        return 0, len(stale)


def clone_tb_full(client, src_lib, src_cell, dst_lib, *, verbose=True):
    """End-to-end clone. Returns True if all rebinds successful.

    Flow (see references/testbench-duplication.md for rationale):
      1. Scan schematic hierarchy. Classify each (lib, cell) as
         project (copy) or external (keep reference).
      2. For each project cell, rsync-copy with cdslck/% exclusions;
         deref master.tag symlinks; chmod u+w. TB also wipes history.
      3. Patch config/expand.cfg design+binding lines.
      4. Patch maestro.sdb + active.state + test_states/ for lib refs.
      5. Clear any stale cdslck, then rebind every instance whose
         master is a project lib — delete+recreate on destination.
         Recurse across TB and every copied DUT cell.
      6. Verify zero stale refs remain.
    """
    log = print if verbose else (lambda *a, **k: None)
    log(f"\n>> {src_lib}/{src_cell}  ->  {dst_lib}")

    pairs = scan_hierarchy(client, src_lib, src_cell)
    proj, ext = classify_pairs(pairs)
    proj_libs = sorted({l for l, _ in proj})
    log(f"   hier: {len(proj)} project cells, {len(ext)} external  "
        f"project_libs={proj_libs}")

    results = cp_many_cells(client, proj, dst_lib, tb_cell=src_cell)
    copied = sum(1 for v in results.values() if v == "copied")
    exists = sum(1 for v in results.values() if v == "exists")
    log(f"   cp: {copied} copied, {exists} already existed")
    sk(client, f'ddSyncWriteLock(ddGetObj("{dst_lib}"))')

    log(f"   patch config: {patch_expand_cfg(client, dst_lib, src_cell, proj_libs)}")
    patch_maestro_files(client, dst_lib, src_cell, proj_libs)
    log(f"   patch maestro files: done")

    clear_all_cdslck_in_lib(client, dst_lib)
    all_ok = True
    parents = [src_cell] + [c for l, c in proj if (l, c) != (src_lib, src_cell)]
    for parent in parents:
        ok, fail = rebind_all_in_cell(client, dst_lib, parent, proj_libs)
        if ok or fail:
            log(f"   rebind in {parent}: ok={ok} fail={fail}")
        all_ok = all_ok and (fail == 0)

    total_touched = sync_props_batch(client, proj, dst_lib, proj_libs)
    log(f"   prop-sync src->dst: {total_touched} insts touched across {len(proj)} cells")

    stale_map = verify_no_stale_batch(client, dst_lib, parents, proj_libs)
    for parent, remaining in stale_map.items():
        if remaining:
            log(f"   STALE remaining in {parent}: {remaining}")
            all_ok = False
    if all_ok:
        log(f"   ✓ clean")
    return all_ok
