# Roadmap — Tiered Memory Management Beyond Hotness

CS-471 project (Mayeul Besnard, Sergio Boffi). Written on 2026-11-08.
Companion document: [Machine_Setup_Report.md](Machine_Setup_Report.md). Section numbers such as "report §6.3" refer to it.

## How to read this document

Every command has a risk tag:

| Tag | Meaning | Rule |
|---|---|---|
| `[RO]` | Read-only | Safe to run |
| `[HOME]` | Writes only inside `~/` | Safe to run |
| `[PERF]` | `sudo perf`: reads counters, changes no setting | Safe to run |
| `[SYS]` | Changes system state, reversible, reset by a reboot | **Needs TA approval.** Log it, restore it right after |
| `[BOOT]` | Changes kernel, GRUB or reboots | **Needs TA approval.** Follow Phase 9 exactly |

Items marked ⚠️ **verify** come from code summaries or from memory, not from a test on our machine.
Commands are written for the `cs471-hotness` account on `iccluster113`.

## Golden rules

- [ ] Before any measurement: `uptime` (load near 0) and `who` (nobody else running).
- [ ] **Never run these scripts as they are:** `src/soar/run/prof.sh`, `run/bc-urand/run.sh`, `src/alto/*/compile.sh`. `prof.sh` calls `check_cxl_conf`, which changes the whole machine and takes 24 CPUs offline.
- [ ] Read every script line by line before running it.
- [ ] Never run `grub-set-default` with a custom kernel (TA rule).
- [ ] Note every `[SYS]` and `[BOOT]` change in `~/hotness/CHANGELOG.md`, with date, command and previous value.
- [ ] Leave the machine in its original state when you finish (report §7).
- [ ] Run long jobs inside `tmux`, so an SSH disconnection does not kill them.
- [ ] Tell your teammate before starting a measurement: the account is shared.

## Timeline

| Date | Goal | Phases |
|---|---|---|
| Sun Nov 8 | TA questions sent, read-only checks, workspace ready | 0, 1, 2 |
| Mon Nov 9 | Build, first real counters, latencies, stable environment | 3, 4 |
| Tue Nov 10 | E1 | 5 |
| Wed Nov 11 | Preliminary E2 | 6 |
| **Thu Nov 12** | **Status report deadline** | 7 |
| Nov 13–20 | SOAR on bc-urand | 8 |
| Nov 20–27 | Baselines and E3 | 9, 10 |
| Dec 4 | Optional: E4 on PolyRack | 11 |
| **Thu Dec 10** | **Poster deadline** | 12 |
| **Thu Dec 17** | **Poster session** | 12 |
| **Sun Dec 20** | **Final report deadline** | 12 |

The proposal promised E2 complete and first SOAR results by Nov 12. With the setup starting now, this is not realistic: the status report should present E1, a preliminary E2, and the feasibility analysis, with an updated plan.

---

## Phase 0 — Coordination (today)

- [ ] Commit or discard the pending changes in the project repository (including `Machine_Setup_Report.md` and this file).
- [ ] Split the work with your teammate and agree on who uses the machine when.
- [ ] Send the TA one message with the questions from report §8, plus these:
  - [ ] Which team shares `iccluster113`, and how are timeslots assigned?
  - [ ] Is remote console access (IPMI/iDRAC) available if a kernel does not boot?
  - [ ] This machine is Haswell, and the artifact targets Skylake. Can we get **CloudLab access (c220g5)** for SOAR and E3?
  - [ ] May we install small packages (`libnuma-dev`, `vmtouch`) with `apt`?

**Exit criterion:** message sent. Phases 1–3 do not depend on the answer.

---

## Phase 1 — Remaining read-only checks

Inspection already completed: CPU, NUMA, `perf`, counters, frequency, tiers (report §1–5).

### 1.1 PEBS

Decides how SOAR profiling can work.

```bash
cat /sys/bus/event_source/devices/cpu/caps/pmu_name                 # [RO] expected: haswell
sudo dmesg | grep -iE "PEBS|Performance Events"                     # [RO] expected: "PEBS fmt2"
sudo journalctl -k -b | grep -iE "PEBS|Performance Events"          # [RO] use this if dmesg has rotated
perf list 2>/dev/null | grep -iE "mem_load_uops|mem_trans_retired"  # [RO]
```

- [ ] Record the PEBS format. Format 2 confirms that `pebs->tsc` is unusable here (report §6.3).
- [ ] Confirm `mem_load_uops_retired.l3_miss` exists.
- [ ] Note any `mem_load_uops_l3_miss_retired.{local,remote}_dram` events: they would separate fast-tier and slow-tier accesses.

### 1.2 Uncore frequency

Decides whether we can reach the paper's ~190 ns.

```bash
ls /sys/devices/system/cpu/intel_uncore_frequency 2>/dev/null || echo "no uncore sysfs"  # [RO]
grep -i UNCORE_FREQ /boot/config-$(uname -r)                                             # [RO]
modinfo intel_uncore_frequency 2>/dev/null | grep -i "model:003F" || echo "Haswell-X not listed"  # [RO]
```

`003F` is the Haswell-X model number. If it is not listed, the artifact's script cannot work here.

### 1.3 Disk, packages, tools

```bash
df -h / /boot /home                                                 # [RO] need ~50 GB for graphs, ~1 GB in /boot per kernel
lsblk                                                               # [RO]
free -h; swapon --show                                              # [RO]
which gcc g++ make git python3 tmux numastat                        # [RO]
dpkg -l | grep -E "libnuma-dev|build-essential|msr-tools|vmtouch|libgfortran5|qemu-system-x86"  # [RO]
```

### 1.4 Complete the record of the original state

Add these values to report §7 before changing anything.

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled                     # [RO] the value in [brackets] is the active one
cat /proc/sys/kernel/randomize_va_space                             # [RO]
cat /sys/kernel/mm/ksm/run                                          # [RO]
cat /sys/devices/system/cpu/smt/control                             # [RO]
cat /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages  # [RO]
grep -E "^GRUB_(DEFAULT|SAVEDEFAULT|TIMEOUT|CMDLINE)" /etc/default/grub  # [RO]
cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list      # [RO] which logical CPU shares core 0
lscpu -e=CPU,NODE,SOCKET,CORE                                       # [RO] full CPU map
```

**Exit criterion:** every result is written in the report, and §7 is complete.

---

## Phase 2 — Workspace

```bash
mkdir -p ~/hotness/{src,results,logs}                               # [HOME]
touch ~/hotness/CHANGELOG.md                                        # [HOME]
tmux new -s hotness                                                 # [HOME] reattach later with: tmux attach -t hotness
cd ~/hotness/src
git clone https://github.com/MoatLab/SoarAlto.git                   # [HOME]
git clone https://github.com/sbeamer/gapbs.git                      # [HOME]
git -C SoarAlto rev-parse HEAD | tee ~/hotness/logs/soaralto.commit # [HOME]
git -C gapbs rev-parse HEAD | tee ~/hotness/logs/gapbs.commit       # [HOME]
git -C SoarAlto switch -c haswell-port                              # [HOME] keeps our changes separate from upstream
```

Confirm on the real code what report §6 says from summaries:

```bash
cd ~/hotness/src/SoarAlto
grep -n "stick_this_thread_to_core\|init_buf" src/microbenchmark/src/main.c  # [RO] pinning and allocation
grep -n "buf_size_b\]" src/microbenchmark/src/main.c                         # [RO] write past the buffer end
grep -n "objs\[\]\|numa_alloc_onnode\|strstr" src/soar/interc/ldlib.c        # [RO] placement logic
grep -n "mnt/sda4" -r src/soar run                                           # [RO] hard-coded paths
grep -n "STALLS_L3_MISS\|24.67" -r src/soar/run                              # [RO] Skylake-specific parts
cat src/soar/prof/Makefile src/soar/interc/Makefile                          # [RO] C++ standard flags
```

- [ ] Correct the report wherever the real code differs.

**Exit criterion:** both repositories cloned, commits recorded, §6 confirmed.

---

## Phase 3 — Build and first real measurements

### 3.1 Build the microbenchmark

```bash
cd ~/hotness/src/SoarAlto/src/microbenchmark/src
make                                                                # [HOME]
```

If it fails on `numa.h`, `libnuma-dev` is missing: `sudo apt install libnuma-dev` `[SYS]`, after TA approval.

### 3.2 Define the two measurement sets

Two runs per measurement, to avoid multiplexing (report §3.3).

```bash
export AOL_EV=cycles,instructions,offcore_requests.demand_data_rd,offcore_requests_outstanding.demand_data_rd,offcore_requests_outstanding.cycles_with_demand_data_rd
export P_EV=cycles,instructions,cycle_activity.stalls_l2_pending
```

### 3.3 Single-thread sanity runs

Single-pattern modes run on CPU 0 and work without code changes. Keep buffer sizes multiples of 64 MB, because the shuffle works in blocks of 64 MB.

```bash
cd ~/hotness/src/SoarAlto/src/microbenchmark/src
uptime
time numactl --cpunodebind=0 --membind=0 ./bench -R 0.0 -i 3 -A 1024   # [HOME] pointer chasing, local memory
time numactl --cpunodebind=0 --membind=1 ./bench -R 0.0 -i 3 -A 1024   # [HOME] pointer chasing, remote memory
time numactl --cpunodebind=0 --membind=0 ./bench -R 1.0 -i 3 -B 1024   # [HOME] sequential, local memory
time numactl --cpunodebind=0 --membind=1 ./bench -R 1.0 -i 3 -B 1024   # [HOME] sequential, remote memory
```

While a run is active, confirm the placement from a second terminal:

```bash
numastat -p $(pgrep -x bench)                                       # [RO] memory per node for the process
```

- [ ] Memory is on the requested node.
- [ ] Pointer chasing slows down clearly more than sequential on the remote node. This is the core effect of the paper.

### 3.4 First counters

Check that a single run lasts a reasonable time, then run the loop inside `tmux`.

```bash
OUT=~/hotness/results/micro_$(date +%F); mkdir -p "$OUT"
for mem in 0 1; do
  for mode in pc seq; do
    if [ "$mode" = pc ]; then ARGS="-R 0.0 -i 9 -A 1024"; else ARGS="-R 1.0 -i 9 -B 1024"; fi
    sudo perf stat -r 5 -e "$AOL_EV" -o "$OUT/${mode}_mem${mem}_aol.txt" -- numactl --cpunodebind=0 --membind=$mem ./bench $ARGS
    sudo perf stat -r 5 -e "$P_EV"   -o "$OUT/${mode}_mem${mem}_p.txt"   -- numactl --cpunodebind=0 --membind=$mem ./bench $ARGS
  done
done                                                                # [PERF]
```

Check the results:

- [ ] No percentage in parentheses at the end of a line (no multiplexing).
- [ ] Pointer chasing: MLP close to 1. Sequential: clearly higher.
- [ ] Pointer chasing on `mem1`: latency clearly above `mem0`.
- [ ] Standard deviation across the 5 repetitions is small.

### 3.5 Real latencies

Option A, without any tool: read the latency in cycles from the 3.4 pointer-chasing runs, and convert to ns with the core frequency. Before Phase 4 the frequency is not fixed, so this is approximate.

Option B, Intel MLC: download it yourself from Intel's site (it requires accepting a license), and copy it with `scp` to `~/hotness/src/mlc/`.

```bash
cd ~/hotness/src/mlc/Linux && ./mlc --latency_matrix -r             # [HOME] do NOT use sudo
```

Without `sudo`, MLC cannot alter the prefetcher MSRs, and `-r` uses random accesses so prefetchers matter less. ⚠️ **verify** the flag with `./mlc --help`.

- [ ] Record local and remote latency, and their ratio. Compare with the paper's 90/190 ns (ratio ~2.1).

**Exit criterion:** numbers in `results/`, and the remote/local slowdown is visible.

---

## Phase 4 — Stable environment `[SYS]` (after TA approval)

Apply only for the duration of a measurement session.

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor /sys/devices/system/cpu/intel_pstate/no_turbo /proc/sys/kernel/numa_balancing  # [RO] record first
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor   # [SYS]
echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo                     # [SYS]
echo 0 | sudo tee /proc/sys/kernel/numa_balancing                                   # [SYS]
```

Restore at the end of the session:

```bash
echo schedutil | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor     # [SYS]
echo 0 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo                     # [SYS]
echo 1 | sudo tee /proc/sys/kernel/numa_balancing                                   # [SYS]
```

Then verify with the first `cat` command above that the values match report §7.

Only if the TA approves them, and only when needed:

| Setting | Apply | Restore | Why |
|---|---|---|---|
| NMI watchdog | `echo 0 \| sudo tee /proc/sys/kernel/nmi_watchdog` | `echo 1 \| sudo tee ...` | Frees one counter; needed for SOAR profiling (Phase 8) |
| THP | `echo never \| sudo tee /sys/kernel/mm/transparent_hugepage/enabled` | the value recorded in 1.4 | The authors disable it |
| Page cache | `echo 3 \| sudo tee /proc/sys/vm/drop_caches` | none needed | Clean state between runs |

Pin threads to physical cores only, using the CPU map from 1.4. Assuming logical CPUs 24–47 are the hyper-threads (⚠️ **verify** with `lscpu -e`), 8 physical cores on node 0 are `0,2,4,6,8,10,12,14`.

- [ ] Repeat 3.4 under these settings and keep the new results as the reference.

**Exit criterion:** repetitions are stable (standard deviation well below the differences we want to detect).

---

## Phase 5 — E1: is hotness a faithful metric? (H1)

### 5.1 Changes to the microbenchmark

Write these yourselves, on the `haswell-port` branch. All three are needed (report §6.4).

- [ ] **Pinning:** put the two threads on physical cores of the same socket (e.g., CPUs 0 and 2), not CPUs 0 and 1.
- [ ] **Placement:** add one option per buffer to choose its NUMA node, using the existing but unused `init_buf` (`numa_alloc_onnode`).
  - Memory from `numa_alloc_onnode` must be released with `numa_free`, not `aligned_free`.
  - `bandwidth()` writes 8 bytes **past** the end of the buffer. With `numa_alloc_onnode` and a size that is a multiple of the page size, this may crash: reserve extra space, or fix the write.
- [ ] **Per-thread timing:** measure and print each thread's elapsed time for its main loop only, excluding allocation and list construction.

### 5.2 Validate the changes

- [ ] `numastat -p $(pgrep -x bench)` shows each buffer's size on the expected node.
- [ ] `ps -eLo pid,tid,psr,comm | grep bench` shows both threads on the expected CPUs.

### 5.3 Run

Each configuration at least 5 times, with `-R 0.5 -i 9 -A 1024 -B 1024`. "Hot" is the sequential buffer (B), "cold" is the pointer-chasing buffer (A).

| Configuration | Buffer A (cold, pointer chasing) | Buffer B (hot, sequential) |
|---|---|---|
| All-on-DRAM | node 0 | node 0 |
| All-on-Slow | node 1 | node 1 |
| Hot-on-DRAM | node 1 | node 0 |
| Cold-on-DRAM | node 0 | node 1 |

Slowdown of each thread: `T(config) / T(All-on-DRAM) - 1`.

- [ ] Run with `perf stat` runs A and B as in 3.4, so the same data also feeds E2.
- [ ] Note that once one thread finishes, the other runs without interference.

### 5.4 Decide

- [ ] **H1 supported** if Cold-on-DRAM is faster than Hot-on-DRAM, with the difference larger than the run-to-run standard deviation.
- [ ] Plot one bar chart: slowdown per configuration and per thread, with error bars.
- [ ] The H1′ test (migration overhead) needs a tiering system: postpone it to Phase 10 and say so in the status report.

**Exit criterion:** chart and conclusion ready for the status report.

---

## Phase 6 — E2: a better metric (H2)

### 6.1 Calibration data

A problem to solve first: K = 1/(a + b/AOL) has **two parameters**. Pointer chasing and sequential alone give only two points, so the fit would be exact and prove nothing.

- [ ] Add a parameter to the pointer-chasing thread that follows **N independent chains in the same loop**, so that MLP is about N. Use N = 1, 2, 4, 8, 16 (Haswell has about 10 L1 fill buffers, so expect saturation).
- [ ] For each N, measure the slowdown (node 1 versus node 0), plus AOL and P.
- [ ] ⚠️ **verify** in the paper (§3) which run provides P and AOL. Record counters on both nodes anyway.

### 6.2 Fit

From `S = P × K`, each point gives `1/K = P/S`. Then fit `P/S = a + b/AOL` with linear regression on `1/AOL`.

- [ ] Report a, b and the fit quality. Compare with the artifact's a = 0.87, b = 24.67 (Skylake).
- [ ] Remember that AOL is in cycles, so a and b depend on the core frequency: calibrate only with the Phase 4 settings.

### 6.3 Test workloads (not used for calibration)

```bash
cd ~/hotness/src/gapbs
patch -p1 < ../SoarAlto/src/soar/patches/gapbs.patch                # [HOME]
make -j 8                                                           # [HOME]
mkdir -p benchmark/graphs
./converter -u24 -k16 -b benchmark/graphs/urand24.sg                # [HOME] small graph for debugging
./converter -g24 -k16 -b benchmark/graphs/kron24.sg                 # [HOME]
```

The full `urand` graph is `-u27` (about 20 GB), used from Phase 8.

```bash
export OMP_NUM_THREADS=8
CPUS=0,2,4,6,8,10,12,14   # verify with lscpu -e
G=benchmark/graphs/urand24.sg
for mem in 0 1; do
  for app in bc pr sssp cc bfs; do
    sudo env OMP_NUM_THREADS=8 perf stat -r 3 -e "$AOL_EV" -o ~/hotness/results/${app}_mem${mem}_aol.txt -- numactl --physcpubind=$CPUS --membind=$mem ./$app -f $G -n 1
    sudo env OMP_NUM_THREADS=8 perf stat -r 3 -e "$P_EV"   -o ~/hotness/results/${app}_mem${mem}_p.txt   -- numactl --physcpubind=$CPUS --membind=$mem ./$app -f $G -n 1
  done
done                                                                # [PERF]
```

### 6.4 Compare the predictors

For each workload, compute the predicted slowdown and compare it to the measured one.

| Predictor | Definition |
|---|---|
| P | `stalls_l2_pending / cycles` |
| P × K | P × 1/(a + b/AOL) |
| Stalls per miss (H2′) | stall cycles / LLC misses, no fit |
| Hotness | access counts from sampling (can wait for Phase 8) |

- [ ] Pearson correlation and MAE for each predictor.
- [ ] Scatter plot, predicted versus measured.
- [ ] Discuss the Haswell limit: `stalls_l2_pending` also counts L3 hits.

**Exit criterion for Nov 12:** preliminary fit, and at least P versus P × K on a few workloads.

---

## Phase 7 — Status report (Nov 12, 10 points)

Reference: `../sample_status_report.pdf` (5 pages) and lecture L02, slide 50, which asks for the progress since the proposal, the hypotheses being tested, any anomaly and update to the hypothesis tree, and the challenges and help needed.

Skeleton: [Status Report/StatusReport.tex](Status%20Report/StatusReport.tex). Fill in every `\todo`, then remove them all before submitting.

- [ ] **§1 Research Problem:** recap, and whether the focus changed since the proposal.
- [ ] **§2.1 Methodology and Testing Environment Updates:** machine, emulation, two-run counters, Haswell differences (`stalls_l2_pending`, no L3-miss offcore events).
- [ ] **§2.2 Current Status of Research Questions:** Insight, Experiment and Status for each of Q1–Q4, stated honestly.
- [ ] **§2.3 Anomalies and Updates to the Hypothesis Tree:** include the updated figure if the tree changes.
- [ ] **§3 Progress, Results, and Analysis:** setup, E1 results and conclusion on H1, preliminary E2, SOAR feasibility.
- [ ] **§4 Challenges:** single memory tier, Skylake-specific artifact, `memmap`, uncore frequency.
- [ ] **§4.4 Help Needed from the Teaching Team:** the open questions from report §8 still unanswered, and CloudLab access.
- [ ] **§5 Plan:** updated milestones, including the CloudLab decision, and the division of work.
- [ ] Compile it and check that no red `\todo` remains. `hyperref` was left out because it breaks the local LaTeX installation.

---

## Decision gate — where to run SOAR and E3 (Nov 12–13)

Decide with the TA's answers and Phase 1 results.

| Situation | Decision |
|---|---|
| CloudLab c220g5 available | Run SOAR and E3 there, with the authors' configuration; keep E1/E2 on Haswell as an extra comparison |
| No CloudLab, PEBS sampling works | Port SOAR to Haswell (Phase 8), and run only the baselines that are feasible (Phase 9) |
| No CloudLab, PEBS sampling unusable | Scope down to E1/E2, ask the TA about alternatives |

**On CloudLab:** reservations expire, so copy results off regularly. The artifact's scripts should work with far fewer changes, but the rule of reading them first still applies. There, the machine is yours for the reservation, so `check_cxl_conf` is acceptable.

---

## Phase 8 — SOAR on bc-urand

Steps for Haswell. On CloudLab, skip 8.2 and the event/constant changes.

### 8.1 Prepare

```bash
cd ~/hotness/src/gapbs
./converter -u27 -k16 -b benchmark/graphs/urand.sg                  # [HOME] large and slow: use tmux
python3 -m venv ~/hotness/venv                                      # [HOME]
~/hotness/venv/bin/pip install -r ~/hotness/src/SoarAlto/src/soar/run/requirements.txt  # [HOME]
```

### 8.2 Test whether profiling works on the stock kernel

This is the key feasibility test.

```bash
cd ~/hotness/src/SoarAlto/src/microbenchmark/src
sudo perf record -d -e mem_load_uops_retired.l3_miss:P -c 3001 -o ~/hotness/results/pebs_test.data -- numactl --cpunodebind=0 --membind=0 ./bench -R 0.0 -i 1 -A 1024   # [PERF]
sudo perf script -i ~/hotness/results/pebs_test.data -F time,event,ip,addr | head -20                 # [RO]
```

- [ ] Each line has a plausible data address (not 0) and a timestamp.
- [ ] Addresses fall inside the buffer's range.

### 8.3 Port the code

Write these yourselves, on `haswell-port`.

- [ ] `prof/ldlib.c`: change the `/mnt/sda4` output path. Fix compilation if needed (`throw(std::bad_alloc)` does not build under C++17).
- [ ] Timestamps: `ldlib.c` uses raw `rdtsc`, while `perf` has its own clock. Use one clock for both, e.g., `clock_gettime(CLOCK_MONOTONIC)` in `ldlib.c` and `perf record -k CLOCK_MONOTONIC`.
- [ ] `proc_obj_e.py`: it reuses `addr.csv` (`time`, `addr` columns) if present, so generate that file from `perf script` instead of changing the PEBS parser.
- [ ] `proc_obj_e.py`: replace `CYCLE_ACTIVITY.STALLS_L3_MISS` with `cycle_activity.stalls_l2_pending` (check the event-name case that `perf stat` prints).
- [ ] `proc_obj_e.py`: replace 24.67 and 0.87 with the Phase 6 values, and reconsider the AOL thresholds (40, 45, 60, 80).

### 8.4 Profile

Needs the NMI watchdog off (`[SYS]`, TA approval): 3 counting events plus PEBS then fit in 4 programmable counters, with `cycles` back on its fixed counter. Without this, expect multiplexing.

Replicate `prof.sh` manually, **without** `check_cxl_conf`:

```bash
cd ~/hotness/src/SoarAlto/src/soar/prof && make                     # [HOME]
cd ~/hotness/src/gapbs
OUT=~/hotness/results/prof_bc_urand; mkdir -p "$OUT"
EV=cycles,cycle_activity.stalls_l2_pending,offcore_requests.demand_data_rd,offcore_requests_outstanding.cycles_with_demand_data_rd

env LD_PRELOAD=$HOME/hotness/src/SoarAlto/src/soar/prof/ldlib.so OMP_NUM_THREADS=8 \
  numactl --physcpubind=0,2,4,6,8,10,12,14 --membind=0 ./bc -f benchmark/graphs/urand.sg -i4 -n1 > "$OUT/log" 2>&1 &
APP=$!
sleep 1
sudo perf record -d -k CLOCK_MONOTONIC -e mem_load_uops_retired.l3_miss:P -c 3001 -p $APP -o "$OUT/pebs.data" &
sudo perf stat -e "$EV" -I 1000 -p $APP -o "$OUT/perf.data" &
wait $APP                                                           # [PERF]
```

- [ ] `$APP` is the `bc` process itself (check with `ps`), since `numactl` replaces itself with the program.
- [ ] Confirm `perf.data` has no multiplexing percentages.
- [ ] Measure the workload's peak memory (RSS) without the profiler: `/usr/bin/time -v`.

### 8.5 Analyze and place

```bash
sudo perf script -i "$OUT/pebs.data" -F time,addr > "$OUT/pebs_addr.txt"   # [RO] then convert to addr.csv
cp ~/hotness/src/SoarAlto/src/soar/run/proc_obj_e.py "$OUT/"
cd "$OUT" && ~/hotness/venv/bin/python proc_obj_e.py <directory-with-data.raw-files>   # [HOME]
```

- [ ] Inspect `obj_stat.csv`: do the objects and scores make sense?
- [ ] Fill `objs[]` in `interc/ldlib.c` by hand with the call-site addresses of the top-ranked objects. These are valid only for this exact `bc` binary.
- [ ] Build it: `cd ~/hotness/src/SoarAlto/src/soar/interc && make`.

### 8.6 Limit the fast-tier capacity

A slow-tier ratio of x% caps DRAM at (100−x)% of RSS, identically for every policy. Two options:

| Option | Tag | Notes |
|---|---|---|
| GRUB `memmap=` (authors' method) | `[BOOT]` | Conflicts with "stock kernel stays default" unless the TA allows it |
| Reserve 1 GB huge pages on node 0 | `[SYS]` | No reboot, and these pages cannot be migrated. ⚠️ **verify** with the TA; not used by the authors |

```bash
echo N | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages   # [SYS] N = GB to take away from node 0
numastat -m | head -20                                              # [RO] confirm the free memory on node 0
echo 0 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages   # [SYS] restore
```

### 8.7 First comparison

- [ ] NoTier: `numactl --physcpubind=...  ./bc ...` with DRAM capped (first touch, then spill to node 1).
- [ ] SOAR: the same, with `LD_PRELOAD=.../interc/ldlib.so`.
- [ ] All-on-DRAM as reference. Slowdown versus All-on-DRAM, at least 3 runs each.
- [ ] Check that `numa_balancing = 0`, so that no migrations occur.

**Exit criterion:** SOAR versus NoTier on bc-urand, at one or two ratios.

---

## Phase 9 — Custom kernels `[BOOT]` (only after TA approval)

Prefer CloudLab for this phase. On `iccluster113`, follow every TA rule.

### 9.1 Safety setup (once)

```bash
sudo mkdir -p /var/log/journal                                      # [SYS] keep boot logs across reboots
sudo systemctl restart systemd-journald                             # [SYS]
df -h /boot                                                         # [RO]
sudo cp /etc/default/grub /etc/default/grub.bak.$(date +%F)         # [SYS] backup
sudo nano /etc/default/grub                                         # [BOOT]
```

In `/etc/default/grub`:

- `GRUB_DEFAULT=saved`
- `GRUB_SAVEDEFAULT` must **not** be `true`: it would make the last booted kernel the default.

```bash
sudo update-grub                                                    # [BOOT]
sudo awk -F"'" '/menuentry |submenu /{print $2}' /boot/grub/grub.cfg  # [RO] exact entry names
sudo grub-set-default "Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-147-generic"   # [BOOT] STOCK kernel only
sudo grub-editenv list                                              # [RO] must show saved_entry = the stock kernel
```

Pin the default to the stock kernel explicitly: a custom kernel with a higher version number would otherwise take the first menu position.

- [ ] Ask the TA whether to add `panic=30`, so that a crashed kernel reboots itself back to stock.

### 9.2 Build a kernel (do not run `compile.sh`, read it and repeat its steps)

```bash
cat ~/hotness/src/SoarAlto/src/alto/nbt/compile.sh                  # [RO] find the kernel version and patch order
cd ~/hotness/src && git clone https://github.com/torvalds/linux.git # [HOME] large
cd linux && git checkout <version-from-compile.sh>                  # [HOME]
git apply ../SoarAlto/src/alto/<system>/<patch>                     # [HOME]
cp /boot/config-$(uname -r) .config                                 # [HOME]
make olddefconfig                                                   # [HOME]
make -j 24 LOCALVERSION=-hotness-<system>                           # [HOME]
```

If `make` stops on the Ubuntu certificate options, disable them with `scripts/config --disable SYSTEM_TRUSTED_KEYS --disable SYSTEM_REVOCATION_KEYS`.

### 9.3 Test in a VM first (TA rule)

```bash
qemu-system-x86_64 -enable-kvm -m 4G -smp 4 -nographic -no-reboot \
  -kernel arch/x86/boot/bzImage -append "console=ttyS0 panic=-1"    # [HOME]
```

- [ ] The kernel boots until it reports it has no root filesystem. That is expected here, and it proves the kernel starts.

### 9.4 Install and boot once

```bash
df -h /boot                                                         # [RO]
sudo make modules_install                                           # [BOOT]
sudo make install                                                   # [BOOT]
sudo update-grub                                                    # [BOOT]
sudo grub-editenv list                                              # [RO] saved_entry must still be the stock kernel
sudo grub-reboot "Advanced options for Ubuntu>Ubuntu, with Linux <custom-version>"   # [BOOT] this boot only
sudo grub-editenv list                                              # [RO] next_entry = the custom kernel
sudo reboot                                                         # [BOOT]
```

After reconnecting:

```bash
uname -r                                                            # [RO]
journalctl -b -1 -p err                                             # [RO] errors of the previous boot
```

### 9.5 End of every session

- [ ] `sudo reboot` with no `grub-reboot`, which returns to the stock kernel.
- [ ] `uname -r` shows `6.8.0-147-generic`.

### 9.6 Clean up

Check every path before deleting, and delete only our own versions.

```bash
ls /boot | grep hotness; ls /lib/modules | grep hotness             # [RO]
sudo rm /boot/*-<custom-version>                                    # [BOOT] never with a wildcard for the version
sudo rm -r /lib/modules/<custom-version>                            # [BOOT]
sudo update-grub                                                    # [BOOT]
```

### 9.7 Baselines, in order of feasibility

| Order | System | Needs |
|---|---|---|
| 1 | NBT | Kernel with `numa_balancing = 2`, and two memory tiers |
| 2 | TPP | `tpp.patch`, two memory tiers |
| 3 | Nomad | `nomad.patch`, `nomad_module` |
| — | Colloid | `colloid-skx.patch` is Skylake-specific: expect it not to work on Haswell |

Getting two memory tiers: study `run/colloid/tpp/tierinit/tierinit.c`, which moves node 1 to a separate tier and depends on helpers from the Colloid patch.

---

## Phase 10 — E3: SOAR versus the state of the art

- [ ] Workloads: bc-urand first, then whichever others are ready (bc-kron, sssp-kron, ...).
- [ ] Slow-tier ratios: 10, 30, 50, 70, 90% of RSS, identical capacity for every policy.
- [ ] Policies: All-on-DRAM, NoTier, SOAR, and each baseline available.
- [ ] At least 3 runs each; mean and standard deviation.
- [ ] Record migrations and occupancy:

```bash
grep -E "pgpromote|pgdemote|numa_pages_migrated|pgmigrate_success" /proc/vmstat   # [RO] before and after each run
numastat -p <pid>                                                                 # [RO] during the run
```

- [ ] H1′: compare migrated pages and slowdown of tiering systems with static placements.
- [ ] Consider two policies different only if means differ by more than the run-to-run standard deviation (as in the proposal).

**Exit criterion:** slowdown-versus-ratio figure, as sketched in the proposal.

---

## Phase 11 — E4 on PolyRack (optional, Dec 4)

Only if Phase 10 finishes on time. Otherwise, state it as future work.

- [ ] Ask the TA whether PolyRack hardware or a model of it is available.
- [ ] Decide whether Haswell-versus-Skylake comparison would be a better use of the time.

---

## Phase 12 — Deliverables

Poster and report are worth 65 of 100 points: Problem Definition 10, Survey of Previous Works 10, Your Contribution 10, Methodology and Experiment 15, Poster Presentation 20.

- [ ] Freeze experiments by about Dec 5.
- [ ] Poster (Dec 10): problem, why hotness fails, AOL, SOAR, setup, E1, E2, E3, conclusions.
- [ ] Rehearse the poster presentation before Dec 17.
- [ ] Final report (Dec 20): add a section on differences from the paper (Haswell, counters, emulation).
- [ ] **Possible contribution:** does AOL hold on older hardware with less precise counters?
- [ ] Clean up the machine: remove custom kernels, and confirm the state in report §7.

---

## Keeping results reproducible

- [ ] One directory per experiment in `~/hotness/results/`, named with experiment and date.
- [ ] Save the context next to each experiment:

```bash
{ date; uname -a; cat /proc/cmdline; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor; cat /sys/devices/system/cpu/intel_pstate/no_turbo; cat /proc/sys/kernel/numa_balancing; git -C ~/hotness/src/SoarAlto rev-parse HEAD; } > "$OUT/context.txt"   # [HOME]
```

- [ ] Copy results to your Mac regularly (run this on the Mac):

```bash
scp -r cs471-hotness@iccluster113.iccluster.epfl.ch:~/hotness/results ./results
```

- [ ] Keep graphs and raw PEBS data out of the git repository, because of their size.
