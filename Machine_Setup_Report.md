# Machine setup report — iccluster113

Inspection of the server provided by the teaching team, before installing anything.
All commands below are **read-only**, except `sudo perf stat`, which only reads hardware counters for the measured process and changes no system setting.

- **Date:** 2026-11-05
- **Access:** `ssh cs471-hotness@iccluster113.iccluster.epfl.ch` (shared team account, sudo available)
- **State at login:** up 17 days, 1 user, load average 0.00

---

## 1. Summary

| Item | Result | Status |
|---|---|---|
| CPU | Intel Xeon E5-2680 v3 (**Haswell-EP**), 2 sockets × 12 cores, HT on (48 logical CPUs) | ⚠️ older than Skylake (see §3) |
| Memory | 2 NUMA nodes, ~126 GB each, almost all free; distance 10/21 | ✅ |
| Kernel | `6.8.0-147-generic` (Ubuntu) | ✅ |
| `perf` | v6.8.12, usable only with `sudo` (`perf_event_paranoid = 4`) | ✅ |
| AOL counters | all available | ✅ |
| P counter | `stalls_l3_miss` missing → `stalls_l2_pending` as proxy | ⚠️ methodology difference |
| Counter budget | NMI watchdog + HT → 4 programmable counters → **2 runs per measurement** | ⚠️ |
| Frequency | `intel_cpufreq` (passive), governor `schedutil`, turbo on | ⚠️ noisy, needs control |
| NUMA balancing | `numa_balancing = 1`, demotion off | ⚠️ must be off for E1 |
| Memory tiers | **single tier** (`memory_tier4` = nodes 0-1) | ❌ NBT/TPP cannot work as is |
| PEBS | **format 2** (no timestamp in the record); `mem_load_uops_retired.l3_miss` available | ⚠️ `perf record -d` instead of the authors' tracepoint (see §10) |
| Uncore frequency driver | not available | ❌ authors' script cannot work here (see §10) |
| Toolchain | Initially missing; installed with `apt`, microbenchmark built | ✅ (see §10.4) |
| First measurements | Slow-tier emulation works: pointer chasing ~102 ns local, ~154 ns remote (~1.5×) | ✅ provisional (see §11) |
| PEBS sampling test | `perf record -d` on the stock kernel gives data addresses and timestamps | ✅ SOAR profiling feasible here (see §13) |
| **E1 (H1)** | Cold-on-DRAM +12% vs Hot-on-DRAM +43% total time | ✅ **H1 supported**, provisional (see §14) |
| GAPBS (first data) | `bc`, `bfs`, `pr`, `cc` on `urand24`: +29% to +37% on the remote node | ✅ provisional (see §12) |
| Counter anomaly | `offcore_requests_outstanding.demand_data_rd` unreliable; `cycles_with_demand_data_rd` consistent | ⚠️ derive AOL directly (see §11.3) |
| Disk | 162 GB free; `/boot` on the root partition | ✅ |
| SoarAlto artifact | Full SOAR pipeline available, but hard-wired for bc-urand on Skylake; baselines are kernel patches; local DRAM limited via GRUB `memmap` | ⚠️ SOAR needs porting to Haswell, baselines need custom kernels (see §6) |

---

## 2. CPU and memory topology

```
$ lscpu | grep -E "Model name|Vendor|Socket|Core\(s\)|Thread\(s\)|NUMA|^CPU\(s\)|L3"
CPU(s):                 48
Vendor ID:              GenuineIntel
Model name:             Intel(R) Xeon(R) CPU E5-2680 v3 @ 2.50GHz
Thread(s) per core:     2
Core(s) per socket:     12
Socket(s):              2
L3 cache:               60 MiB (2 instances)
NUMA node(s):           2
NUMA node0 CPU(s):      0,2,4,...,46   (even)
NUMA node1 CPU(s):      1,3,5,...,47   (odd)
```

```
$ numactl -H
node 0 size: 128686 MB   free: 127073 MB
node 1 size: 129012 MB   free: 128267 MB
node distances:   0: 10 21   1: 21 10
```

Notes:
- 12 cores per socket ≥ the 8 threads used in the paper.
- 30 MiB L3 per socket, far smaller than the workload footprints (8–35 GB).
- ~126 GB per node: enough to fit any workload (e.g., bc-urand ~20 GB) on a single node.
- **CPU numbering is interleaved** (even = node 0, odd = node 1): pin threads with `numactl --cpunodebind`, never with CPU ranges such as `0-11`.
- The NUMA distance (21) is a firmware estimate (ACPI SLIT), not a measurement: actual latencies are still to be measured.

---

## 3. Performance counters

### 3.1 Access

```
$ cat /proc/sys/kernel/perf_event_paranoid
4
```

`4` (Ubuntu/Debian patch) forbids counters to unprivileged users. We use `sudo perf ...` per measurement instead of lowering this setting, so that the machine configuration is not changed.

### 3.2 Available events

```
$ perf list | grep -iE "offcore_requests|cycle_activity"
offcore_requests.demand_data_rd
offcore_requests_outstanding.demand_data_rd
offcore_requests_outstanding.cycles_with_demand_data_rd
cycle_activity.stalls_l2_pending
cycle_activity.stalls_ldm_pending
... (others omitted)
```

Metrics derived from them:

| Quantity | Formula |
|---|---|
| Average latency (cycles) | `outstanding.demand_data_rd / offcore_requests.demand_data_rd` |
| Average MLP | `outstanding.demand_data_rd / outstanding.cycles_with_demand_data_rd` |
| **AOL** = Latency / MLP | `outstanding.cycles_with_demand_data_rd / offcore_requests.demand_data_rd` |
| **P** (stall ratio) | `cycle_activity.stalls_l2_pending / cycles` |

> **Update:** the first measurements show that the two formulas using `outstanding.demand_data_rd` (latency and MLP) are unreliable on this machine; see §11.3.

**Haswell limitations (methodology differences from the paper):**
- Skylake's `CYCLE_ACTIVITY.STALLS_L3_MISS` does not exist; `stalls_l2_pending` also counts stalls on L3 hits, so P is likely overestimated.
- There are no `*_L3_MISS_*` offcore variants: latency/AOL mix L3 hits (~40 cycles) with memory accesses. AOL may be "diluted" for cache-friendly workloads.

### 3.3 Multiplexing

A first run with 6 events showed multiplexing on `cycles` (61%) and `stalls_l2_pending` (39%).

```
$ cat /proc/sys/kernel/nmi_watchdog
1
```

Cause: the NMI watchdog uses the fixed cycles counter, so `cycles` falls back to a programmable counter; with HT on, only 4 programmable counters per logical CPU are available, and 5 were requested.

Fix (no system change): split each measurement into **two runs**. Both were verified to run without multiplexing:

```
# Run A — AOL
sudo perf stat -e cycles,instructions,offcore_requests.demand_data_rd,offcore_requests_outstanding.demand_data_rd,offcore_requests_outstanding.cycles_with_demand_data_rd -- <cmd>

# Run B — P
sudo perf stat -e cycles,instructions,cycle_activity.stalls_l2_pending -- <cmd>
```

Sanity values on `sleep 1` (not meaningful, too few requests, only to check that counters work): latency ≈ 41–64 cycles, MLP ≈ 1.4, AOL ≈ 29–44 cycles, P ≈ 11.6%. The latency variation between runs shows that real measurements need large workloads and repetitions (`perf stat -r N`).

Alternatives (not applied, would change the system): disable the NMI watchdog temporarily, or disable HT (8 programmable counters).

---

## 4. CPU frequency

```
$ cat .../cpu0/cpufreq/{scaling_driver,scaling_governor}; cat /sys/devices/system/cpu/intel_pstate/no_turbo
intel_cpufreq
schedutil
0
$ cat .../cpu0/cpufreq/{cpuinfo_min_freq,cpuinfo_max_freq,scaling_min_freq,scaling_max_freq,scaling_available_governors}
1200000
3300000
1200000
3300000
conservative ondemand userspace powersave performance schedutil
```

- `intel_cpufreq` = `intel_pstate` in passive mode, so generic governors can be used.
- `schedutil` + turbo on make frequency depend on load and temperature: noisy run-to-run results, and the same latency in ns corresponds to a different number of cycles.
- Planned for measurements (pending TA approval): governor `performance`, turbo off (fixed 2.5 GHz), restored afterwards.

---

## 5. Kernel tiering state

```
$ uname -r; cat /proc/sys/kernel/numa_balancing; cat /sys/kernel/mm/numa/demotion_enabled
6.8.0-147-generic
1
false
$ ls /sys/devices/virtual/memory_tiering/; cat /sys/devices/virtual/memory_tiering/memory_tier*/nodelist
memory_tier4  power  uevent
0-1
```

- `numa_balancing = 1` (classic NUMA balancing): the kernel may migrate pages and threads behind our back. For E1 (static placements, no migrations) it should be set to `0` during the runs (pending TA approval).
- Kernel 6.8 includes memory tiering mode (`numa_balancing = 2`, i.e., NBT) and demotion.
- **Both nodes are in the same memory tier.** Promotion/demotion only moves pages between different tiers, so **NBT and TPP would never migrate anything** on this setup. Offlining node 1's CPUs (as in the paper's CXL emulation) is probably not enough, since the tier depends on the node's abstract distance set by the memory driver, not on the presence of CPUs (to be verified). The artifact contains a module, `run/colloid/tpp/tierinit/tierinit.c`, that moves node 1 to a separate lower tier, but it relies on `colloid_*` helpers that are not defined in that file (presumably provided by the Colloid kernel patch).

Impact on the plan:

| Experiment | Works as is? |
|---|---|
| E1 (static placements) | ✅ placement controlled with `numactl`/`mbind` |
| E2 (AOL, P, K calibration) | ✅ counters only |
| SOAR profiling | ❓ possibly on the stock kernel with `perf record -d` instead of the `pebs:pebs` tracepoint, to be tested (see §6.3) |
| SOAR allocation (interception) | ✅ by code review no custom kernel needed (libnuma + `LD_PRELOAD`); not tested yet |
| E3 baselines NBT / TPP | ❌ need two memory tiers (kernel change or authors' setup) |
| E3 baselines Nomad / Colloid | ❌ custom kernels (follow the TA safety rules) |

---

## 6. SoarAlto repository review

Source: [MoatLab/SoarAlto](https://github.com/MoatLab/SoarAlto) — READMEs, `run/setup.sh`, `run/bc-urand/modify-uncore-freq.sh`, `run/colloid/tpp/tierinit/tierinit.c`, `src/microbenchmark/`, and all of the SOAR pipeline (`src/soar/`). Reviewed on GitHub through automated page summaries; nothing was installed or run on the machine. Details must be confirmed on the actual code once cloned.

### 6.1 Structure

| Path | Content |
|---|---|
| `src/microbenchmark/` | sequential and pointer-chasing microbenchmarks (E1) |
| `src/soar/` | SOAR: profiling (`prof/ldlib.c`, `run/prof.sh`), analysis (`run/proc_obj_e.py` → `obj_stat.csv`), allocation interception (`interc/ldlib.c`, policy in `check_trace`: `0` = fast tier, `1` = slow tier, `-1` = default), `patches/` (`nbt.patch`, `gapbs.patch`) |
| `src/alto/` | kernel patches + `compile.sh` for TPP, NBT, Nomad, Colloid (base and ALTO variants) |
| `run/` | `setup.sh`, `config.sh`, `bc-urand/` (`run.sh [type] [threads] [MLC-threads]`, type 0 NoTier … 11 SOAR; `modify-uncore-freq.sh`; `calpg.sh`), `colloid/`, `nomad_module/` |

Workloads named in `run/README.md`: bc-kron, bc-twitter, bc-urand, sssp-kron, tc-twitter, 602.gcc_s, gpt-2, redis. The repository only contains a run directory for bc-urand.

### 6.2 Findings relevant to our machine

1. **The kernel patch**: the SOAR README requires Linux v5.18 with `patches/nbt.patch`. By inspection, the only part of the patch that serves profiling is the `pebs:pebs` tracepoint (`ip`, `dla`, `tsc`); the rest (promotion rate limiting, PTE scan scaling, kswapd reset, sysctls) concerns NBT migrations. SOAR may therefore not need this kernel (see §6.3). GAPBS must be built with `-no-pie` (`patches/gapbs.patch`).
2. **Slow-tier emulation**: remote NUMA node with its uncore frequency lowered to 500 MHz (`modify-uncore-freq.sh`), giving ~190 ns on CloudLab c220g5 (Skylake), **and node 1's CPUs taken offline** (`configure_cxl_exp_cores` in `config.sh`). The script writes to `/sys/devices/system/cpu/intel_uncore_frequency`, which requires `CONFIG_INTEL_UNCORE_FREQ_CONTROL`. **Verified: this interface is not available on our machine** (§10). The uncore frequency could only be set via MSRs (to be discussed with the TA); otherwise we keep the natural remote latency.
3. **Local DRAM is limited with the GRUB `memmap=` kernel parameter** (`update-grub` + reboot), not with a memory-eating process, because tiering systems would migrate its pages. This is a persistent boot change and conflicts with the TA rule "stock kernel stays the default"; to be discussed with the TA.
4. **Baselines**: each `src/alto/*/compile.sh` switches kernel version (e.g., v6.3), applies patches, builds and installs the kernel and updates the bootloader. Must be adapted to the one-time GRUB boot procedure before use. "Colloid" in the artifact means Colloid-TPP (`colloid-skx.patch`, Skylake-specific).
5. **Reference platforms** are Skylake (Xeon Silver 4114) and Sapphire Rapids (Xeon Gold 6430); ALTO's AOL thresholds were profiled on Skylake. On Haswell, K must be recalibrated (as planned in E2).
6. **Scripts must be read before running**: `setup.sh` only runs `apt update` and installs `libgfortran5` and `vmtouch`, with errors hidden; `run.sh` hardcodes `perf` at `/tdata/linux/tools/perf/perf`, which does not exist here.
7. **Do not run `src/soar/run/prof.sh` as is**: it calls `check_cxl_conf`, which changes the whole machine: disables NMI watchdog, ASLR, KSM, NUMA balancing, THP, HT, turbo and swap, starts `pmqos`, and takes node 1's 24 CPUs offline. These changes need TA approval and a restore plan.

### 6.3 SOAR pipeline: what is needed on Haswell

| Phase | In the repository | Work required |
|---|---|---|
| Allocation tracing (`prof/ldlib.c`) | ✅ | Change the hard-coded output path `/mnt/sda4`; may not compile with recent `g++` (`throw(std::bad_alloc)` removed in C++17) |
| PEBS sampling (`run/prof.sh`) | ✅ | Porting: see the problems below; also hard-coded `perf` and GAPBS paths |
| Object scoring (`run/proc_obj_e.py`) | ✅ | Porting: event names and model constants |
| Placement (`interc/ldlib.c`) | ✅ | `check_trace` holds call-site addresses of one specific binary: to be replaced by hand with those from our profiling. Only `malloc` is placed, and only on node 0 |
| GAPBS | ❌ (patch only) | Clone it and generate the `urand` graph (~20 GB) |
| Intel MLC | ❌ | Download separately from Intel |

Haswell porting problems:

1. **PEBS timestamps**: the tracepoint reads `pebs->tsc`. From memory, this record field exists only from Skylake (PEBS format 3). **Verified: our machine uses format 2** (§10), so the value would be meaningless. Candidate alternative: standard `perf record -d`, which provides data address and time with no kernel patch, adapting the parsing and aligning its clock with the `rdtsc` timestamps of `ldlib.c`.
2. **Event names**: `mem_load_retired.l3_miss` becomes `mem_load_uops_retired.l3_miss` on Haswell (verified with `perf list`, §10), and `CYCLE_ACTIVITY.STALLS_L3_MISS` becomes `stalls_l2_pending` (also in the parser of `proc_obj_e.py`).
3. **Model constants**: the script uses `P / (24.67/AOL + 0.87)`, i.e., a = 0.87 and b = 24.67 in K = 1/(a + b/AOL), plus fixed AOL thresholds (40, 45, 60, 80). They must be recalibrated (E2).
4. **Counter budget**: profiling uses 4 `perf stat` events plus PEBS at the same time. With NMI watchdog and HT on, this exceeds the 4 programmable counters (the authors disable both).

### 6.4 Microbenchmark (E1)

`src/microbenchmark/` runs pointer-chasing (`-R 0.0`, 64 B nodes, shuffled in blocks of ~1 M nodes), sequential read (`-R 1.0`) or both on two threads (any other `-R`). Three issues for E1 on this machine, all requiring code changes:

1. **Thread pinning**: the threads are pinned to CPU 0 and CPU 1, which are on **different sockets** here (§2).
2. **Placement**: buffers come from plain `malloc` (`init_buf_reg_alloc`); `init_buf` (`numa_alloc_onnode`) is never called and `-r` has no effect, so the two buffers cannot be placed on different nodes as is. `numactl` applies to the whole process.
3. **No output**: the program has no timers and prints no results. `perf stat` gives only the total process time, not the time of each thread.

### 6.5 Impact on the status report (Nov. 12)

- **Feasible on the stock kernel**: E1 (microbenchmark, after the changes in §6.4) and E2 (counters), pending TA approval for governor/turbo/`numa_balancing`.
- **To be tested on the stock kernel**: SOAR, after the porting in §6.3.
- **Need custom kernels or boot changes**: all E3 baselines, and DRAM capacity limiting with `memmap`.

---

## 7. Original state (to restore after every experiment)

| Setting | Original value |
|---|---|
| `scaling_governor` | `schedutil` |
| `intel_pstate/no_turbo` | `0` |
| `scaling_min_freq` / `scaling_max_freq` | `1200000` / `3300000` |
| `kernel.numa_balancing` | `1` |
| `numa/demotion_enabled` | `false` |
| `kernel.nmi_watchdog` | `1` |
| `kernel.perf_event_paranoid` | `4` |
| `transparent_hugepage/enabled` | `madvise` |
| `kernel.randomize_va_space` (ASLR) | `2` |
| `ksm/run` | `0` |
| `smt/control` (HT) | `on` |
| 1 GB huge pages on node 0 (`nr_hugepages`) | `0` |
| `GRUB_DEFAULT` | `0` |
| `GRUB_TIMEOUT` / `GRUB_TIMEOUT_STYLE` | `0` / `hidden` |
| `GRUB_CMDLINE_LINUX` / `GRUB_CMDLINE_LINUX_DEFAULT` | empty |
| Kernel | `6.8.0-147-generic` |

---

## 8. Open questions for the TA

1. During our measurements, may we set the governor to `performance`, disable turbo and set `numa_balancing = 0`, restoring the original values right afterwards?
2. The kernel puts both NUMA nodes in a single memory tier, so NBT/TPP cannot promote/demote. Is there a recommended way to make node 1 a lower tier?
3. The artifact limits local DRAM with the GRUB `memmap=` parameter, which is a persistent boot change. Is this allowed (e.g., only for a one-time boot), or should we use another method?
4. The artifact lowers the remote uncore frequency to emulate CXL latency, but the uncore frequency driver is not available here. May we set it through MSR 0x620, or should we keep the natural remote latency?
5. The artifact also disables HT, swap, ASLR, KSM, THP and the NMI watchdog, and takes node 1's CPUs offline. Which of these may we apply during our runs, restoring them afterwards?
6. We installed the compiler toolchain with `apt` (`build-essential`, `libnuma-dev`) to build the microbenchmark. Is this fine, and may we also install `vmtouch` and `libgfortran5` for SOAR?
7. The artifact targets Skylake. Could we get CloudLab access (c220g5, the authors' platform) for SOAR and the baselines?
8. Which team shares this machine, and are there timeslots? Is a remote console available if a kernel does not boot?

## 9. Next steps

1. ~~Read the SoarAlto README (kernel requirements, CXL emulation, tier setup).~~ Done (§6).
2. ~~Read `src/microbenchmark/` (E1 code) and the SOAR pipeline.~~ Done (§6.3, §6.4).
3. ~~Read-only checks on the machine: PEBS format, `mem_load_uops_retired.l3_miss`, presence of `intel_uncore_frequency`, free disk space.~~ Done (§10).
4. ~~Clone SoarAlto and GAPBS in the home directory.~~ Done. Still to do: confirm the findings of §6 on the actual code.
5. ~~Build the microbenchmark and take first measurements.~~ Done (§11), provisional. Repeat under stable settings after TA approval.
6. ~~Check that no result file contains multiplexing.~~ Done (§12.3).
7. ~~Implement the three microbenchmark changes for E1, then run E1.~~ Done (§14), provisional.
8. Repeat E1 under stable settings after TA approval; test H1′ once a tiering system is available.
9. Port SOAR profiling: align the `perf` and `ldlib.c` clocks (§13).
10. Repeat `bfs` and `cc` with more trials, and add more varied workloads for E2 (§12.2).
11. Before any custom kernel: persistent journal, `/boot` space check, one-time GRUB boot (TA rules).

## 10. Additional read-only checks (2026-11-09)

### 10.1 PEBS

```
$ sudo dmesg | grep -iE "PEBS|Performance Events"
Performance Events: PEBS fmt2+, Haswell events, 16-deep LBR, full-width counters, Intel PMU driver.
```

PEBS format 2 has no timestamp field in the record, so the authors' `pebs:pebs` tracepoint cannot be used here. Since this tracepoint is the only part of `nbt.patch` relevant to SOAR, there is no reason to install Linux v5.18 for SOAR on this machine. The plan is to use `perf record -d` on the stock kernel (still to be tested).

### 10.2 Memory events

`perf list` shows, among others:

| Event | Possible use |
|---|---|
| `mem_load_uops_retired.l3_miss` | PEBS sampling for SOAR (replaces `mem_load_retired.l3_miss`) |
| `mem_load_uops_l3_miss_retired.{local_dram,remote_dram}` | Split misses between the fast and slow tiers (fraction α of the proposal); check the placement |
| `mem_load_uops_retired.l3_hit` | Estimate the part of `stalls_l2_pending` due to DRAM rather than L3 hits |
| `mem_trans_retired.load_latency_gt_*` | Latency-threshold sampling |

To be validated with the microbenchmark, where the memory node is known: from memory, some of these Haswell events have known errata.

Idea to evaluate in E2 (formula from memory, to be checked against Intel's documentation): with Intel's Top-Down method for Haswell, `P_DRAM ≈ (1 − l3_hit / (l3_hit + 7 × l3_miss)) × stalls_l2_pending / cycles`. It would require a third run per measurement.

### 10.3 Uncore frequency

```
$ ls /sys/devices/system/cpu/intel_uncore_frequency ...
no uncore sysfs
$ modinfo intel_uncore_frequency | grep -i "model:003F" ...
Haswell-X not listed
```

The authors' `modify-uncore-freq.sh` cannot work here. The second message appears both if the driver does not support Haswell-X and if the module is absent. Unless the TA approves MSR writes, the slow tier keeps the natural remote latency, which must be measured and stated in the methodology.

### 10.4 Disk and toolchain

```
$ df -h / /boot /home
/dev/sda2  182G  11G  162G  7%   (same filesystem for all three)
$ which gcc g++ make git python3 tmux numastat
/usr/bin/git  /usr/bin/python3  /usr/bin/tmux  /usr/bin/numastat
$ dpkg -l | grep -E "libnuma-dev|build-essential|vmtouch|libgfortran5"
(no output)
```

- 162 GB free is enough for graphs and results. `/boot` is on the root filesystem.
- **`gcc`, `g++`, `make`, `libnuma-dev` and `build-essential` were missing** at inspection time.
- **Update:** the toolchain was then installed with `apt`, and the microbenchmark builds. Tell the TA which packages were added, and check the list with `dpkg -l | grep -E "build-essential|libnuma-dev"`.

### 10.5 System settings and CPU topology

```
$ cat .../transparent_hugepage/enabled .../randomize_va_space .../ksm/run .../smt/control
always [madvise] never
2
0
on
$ grep -E "^GRUB_(DEFAULT|SAVEDEFAULT|TIMEOUT|CMDLINE)" /etc/default/grub
GRUB_DEFAULT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_TIMEOUT=0
GRUB_CMDLINE_LINUX_DEFAULT=""
GRUB_CMDLINE_LINUX=""
$ cat .../node0/hugepages/hugepages-1048576kB/nr_hugepages
0
$ cat .../cpu{0,2,4,6,8,10,12,14}/topology/thread_siblings_list
0,24  2,26  4,28  6,30  8,32  10,34  12,36  14,38
```

- **CPU topology:** the hyper-thread sibling of each CPU is CPU + 24. CPUs `0,2,4,6,8,10,12,14` are 8 distinct physical cores on node 0.
- **THP** is `madvise`, so plain `malloc` does not get huge pages. The authors use `never`.
- **ASLR** is on. With `-no-pie`, the binary's call-site addresses used by SOAR should stay fixed, so disabling ASLR may not be needed (to be verified).
- **GRUB:** `GRUB_DEFAULT=0` means the first menu entry, so a custom kernel with a higher version could become the default. The boot menu is hidden with no timeout, so a kernel cannot be chosen by hand at boot. Fix before any custom kernel (Roadmap, Phase 9.1).
- **1 GB huge pages** are supported by the kernel, so reserving them is a possible alternative to `memmap`; whether they can be allocated at runtime is untested, and it would need TA approval.

## 11. First measurements (2026-11-09, provisional)

**Conditions:** `src/microbenchmark` unmodified, single-thread modes only, CPU on node 0 (`numactl --cpunodebind=0`), memory on node 0 or node 1 (`--membind`), 1 GiB buffer. Governor, turbo and `numa_balancing` left at their original values, so these results are **provisional** and must be repeated under stable settings. Raw data on the server: `~/hotness/results/micro_provisional_2026-11-09_1634/` and `~/hotness/results/pc_i1_mem{0,1}.txt`.

### 11.1 Whole-program results (`-i 9`, 3 runs)

Time and P come from the P run; the other metrics from the AOL run. There was no multiplexing (checked on the raw files, §12.3).

| Configuration | Time (s) | Latency (cycles) | MLP | AOL (cycles) | P | Slowdown |
|---|---|---|---|---|---|---|
| Pointer chasing, node 0 | 25.49 | 603 | 3.7 | 162 | 0.76 | reference |
| Pointer chasing, node 1 | 37.01 | 988 | 4.2 | 236 | 0.79 | **+45%** |
| Sequential, node 0 | 23.46 | 183 | 11.7 | 16 | 0.66 | reference |
| Sequential, node 1 | 31.42 | 252 | 12.3 | 21 | 0.74 | **+34%** |

Observations:

- The direction matches the paper: the low-MLP pattern slows down more.
- P is similar for the two patterns, while AOL differs by about 10×. Two patterns are not enough to validate the predictor.
- Latency and MLP in this table are not reliable for pointer chasing (§11.3). These figures also include the setup phase (list construction and shuffling).

### 11.2 Pointer chasing without the setup phase

The setup phase is the same at any iteration count, so subtracting a `-i 1` run (3 runs) from the `-i 9` run isolates 8 traversal iterations, i.e., about 134 M steps.

| Quantity (`-i 9` minus `-i 1`) | Node 0 | Node 1 |
|---|---|---|
| Time per step | **~102 ns** | **~154 ns** |
| Core cycles per step | ~253 | ~383 |
| `cycles_with_demand_data_rd` per step | ~254 | ~385 |
| Requests relative to the steps | +35% | +38% |
| Latency from counters (cycles) | 791 | 1456 |
| MLP from counters | 4.2 | 5.2 |
| AOL from counters (cycles) | 188 | 280 |

The remote/local ratio is about **1.5×**, against about 2.1× in the paper (90/190 ns). The per-step time includes TLB misses (4 KB pages), so it is not a pure memory latency. The emulated slow tier is therefore less slow than in the paper; this must be stated in the methodology.

### 11.3 Counter anomaly

A pointer chase is serial, so MLP should be about 1. The measured MLP is 4.2–5.2, and removing the setup phase did not bring it closer to 1. A request cannot stay outstanding for 791 cycles if each step takes 253 cycles. Therefore **`offcore_requests_outstanding.demand_data_rd` is not reliable on this machine, at least for this pattern.** The cause is unknown; a Haswell erratum or an effect of hyper-threading are possible.

- `cycles_with_demand_data_rd` is consistent with the real cycles per step.
- AOL can be computed as `cycles_with_demand_data_rd / demand_data_rd`, which does **not** use the suspect counter. The authors' `proc_obj_e.py` does the same.
- The number of requests is 35–38% above the number of steps (possibly page walks, not verified), so this AOL is about 26% below the cycles per step.
- Latency and MLP derived from `outstanding.demand_data_rd` must not be reported for pointer chasing, and should be treated with caution elsewhere.

## 12. First GAPBS results (2026-11-09, provisional)

**Conditions:** GAPBS with `-no-pie`, graph `urand24` (`./converter -u24 -k16`, 16.8 M nodes, 2.2 GB), read once with `numactl --membind=0` to warm the page cache. 8 OpenMP threads on physical cores `0,2,4,6,8,10,12,14` (node 0), memory on node 0 or node 1. Governor, turbo and `numa_balancing` left at their original values. Each case ran 3 times with each of the two event sets. Summary: `gapbs_summary.log` in this repository; raw data in `~/hotness/results/gapbs_provisional_*/` on the server.

Arguments: `bc -i4 -n1`, `pr -n1`, `bfs -n8`, `cc -n8`. `sssp` needs a weighted graph and `tc` is very slow, so they were not run.

### 12.1 Results

Slowdown is computed on GAPBS's `Average Time` (algorithm only), as the mean of the 6 runs. "Whole-process slowdown" uses the elapsed time reported by `perf`, which includes graph loading. P and AOL are reported as local / remote.

| Workload | Local (s) | Remote (s) | Slowdown | Whole-process slowdown | P | AOL (cycles) |
|---|---|---|---|---|---|---|
| `bc` | 17.32 | 23.75 | **+37.1%** | +35.2% | 0.78 / 0.84 | 46 / 63 |
| `bfs` | 0.24 | 0.33 | **+35.4%** | +25.2% | 0.56 / 0.64 | 35 / 48 |
| `pr` | 4.29 | 5.74 | **+33.8%** | +30.1% | 0.87 / 0.90 | 28 / 38 |
| `cc` | 0.59 | 0.76 | **+29.1%** | +23.6% | 0.65 / 0.72 | 62 / 82 |

### 12.2 Observations

- The slowdowns are similar (29–37%), partly because the remote node is only about 1.5× slower. With such a narrow range, there is little for a predictor to explain.
- The correlation between local P and slowdown is weak (about 0.2), but with 4 points it says nothing about H2.
- `perf` counters cover the whole process, including graph loading. For `bfs` and `cc`, the algorithm takes only a small part of the 3–6 s total, so their P and AOL mostly describe the loading. More trials (`-n`) are needed. `bc` is the most reliable case, followed by `pr`.
- Latency and MLP are not reported, because of the anomaly in §11.3.

### 12.3 Multiplexing check

The compact summary command removed everything in parentheses, including any multiplexing percentages, so the raw files were checked separately:

```bash
grep -lE '\([0-9.]+%\)' ~/hotness/results/*/*.txt || echo "no multiplexing"
```

Result: **no multiplexing** in any microbenchmark or GAPBS result file.

## 13. PEBS sampling test (2026-11-10)

Goal: check whether SOAR's profiling can work on the stock kernel, since PEBS format 2 has no timestamp in the record (§10.1).

```bash
sudo perf record -d -e mem_load_uops_retired.l3_miss:P -c 3001 -o ~/hotness/results/pebs_test.data -- numactl --cpunodebind=0 --membind=0 ./bench -R 0.0 -i 1 -A 1024
sudo perf report -i ~/hotness/results/pebs_test.data --stdio --sort dso,sym
sudo perf script -i ~/hotness/results/pebs_test.data -F time,ip,sym,addr | grep pc_thread | head -10
```

Results:

- 17,814 samples were recorded.
- **Where:** `shuffle` 33.4%, `pc_thread` 31.4% (the traversal; `ptr_chase` is inlined), `init_ptr_buf` 31.1%, kernel about 4%. With one iteration, about two thirds of the misses come from the setup phase, which confirms §11.
- **Fields:** `perf script` prints the data address before the instruction address. In `pc_thread`, the instruction address is constant (`5c6c278f00e6`) and **the data address changes at every sample**.
- **Three consistency checks:**
  1. All data addresses are multiples of 64, i.e., the 64 B list nodes.
  2. Consecutive samples fall within about 57 MB, consistent with the shuffle in 64 MB blocks.
  3. Samples are about 0.316 ms apart, i.e., 3001 misses, which gives **about 105 ns per miss**. This matches the ~102 ns per step of §11.2, obtained independently from timings.
- **Timestamps** are the kernel's time since boot, in seconds. For kernel instructions, the data address field is a constant value (`1400058b4`), which is irrelevant for SOAR.

**Conclusion:** `perf record -d` provides data addresses and timestamps on the stock kernel, so **SOAR profiling is feasible on this machine without `nbt.patch` or Linux v5.18**. What remains is to align the `perf` clock with the `rdtsc` timestamps written by `ldlib.c` (Roadmap, Phase 8.3).

## 14. E1: hotness versus criticality (2026-11-10, provisional)

### 14.1 Microbenchmark changes

On the `haswell-port` branch of SoarAlto, on the server (3 files, 11 lines changed, plus timing):

1. **Pinning:** `stick_this_thread_to_core(2*header->thread_idx)` in `pc_thread` and `bw_thread`, so the two threads run on CPUs 0 and 2, i.e., two physical cores of node 0. This relies on this machine's interleaved CPU numbering. Verified with `ps -eLo tid,psr,comm`.
2. **Per-buffer placement:** both buffers are allocated with the existing `init_buf` (`numa_alloc_onnode`) instead of `malloc`, and freed with `numa_free`. New option `-b` for buffer B's node (`-r` for buffer A already existed). Buffer B gets one extra page, because `bandwidth()` writes 8 bytes past its end. Verified with `numastat -p`: A on node 0, B on node 1.
3. **Per-thread timing:** `clock_gettime(CLOCK_MONOTONIC)` around the main loop only, excluding setup (list construction and shuffle for A; `memset` and the first warm-up read for B). Output: `pc_time_s` and `bw_time_s`. Sanity check: `pc_time_s` with `-i 1` is 1.72 s, as predicted from ~102 ns × 16.8 M steps.

### 14.2 Setup

`./bench -R 0.5 -r <A node> -b <B node> -i 9 -A 1024 -B 1024`: buffer A (pointer chasing, "cold") and buffer B (sequential, "hot", 26× more passes) are both 1 GiB. Configurations are interleaved within each repetition. The program's total time is measured with the shell's `time`. Governor, turbo and `numa_balancing` were left at their original values.

| Configuration | Buffer A (cold) | Buffer B (hot) |
|---|---|---|
| All-on-DRAM | node 0 | node 0 |
| All-on-Slow | node 1 | node 1 |
| Hot-on-DRAM | node 1 | node 0 |
| Cold-on-DRAM | node 0 | node 1 |

Two runs: 5 repetitions with per-thread times (`e1_provisional.log`), then 3 repetitions adding total time (`e1_total.log`). Both logs are in this repository.

### 14.3 Results

Mean ± standard deviation, and slowdown with respect to All-on-DRAM (second run, 3 repetitions):

| Configuration | Total time (s) | Slowdown | Pointer-chasing loop (s) | Sequential loop (s) |
|---|---|---|---|---|
| All-on-DRAM | 28.95 ± 0.38 | — | 15.65 ± 0.01 | 22.10 ± 0.06 |
| All-on-Slow | 43.21 ± 0.16 | **+49.2%** | 24.15 ± 0.00 (+54.3%) | 30.84 ± 0.05 (+39.5%) |
| **Hot-on-DRAM** | 41.54 ± 0.15 | **+43.5%** | 23.30 ± 0.00 (+48.9%) | 22.03 ± 0.01 (−0.3%) |
| **Cold-on-DRAM** | 32.46 ± 0.07 | **+12.1%** | 15.98 ± 0.01 (+2.1%) | 30.83 ± 0.06 (+39.5%) |

The first run (5 repetitions) gives the same per-thread times within 1–2%. All standard deviations are below 1.5% of the mean.

Kernel page migrations during the first run: `numa_pages_migrated` went from 220,160 to 220,369 (209 pages, system-wide), against about 524,000 pages in the two buffers per run. The placement was effectively static.

### 14.4 Analysis

- **H1 is supported.** With the same fast-tier capacity, Hot-on-DRAM is **28% slower** than Cold-on-DRAM (41.54 s versus 32.46 s). The difference is about 60 times the run-to-run standard deviation.
- Placing the hot buffer in DRAM recovers only 1.7 of the 14.3 s lost by All-on-Slow; placing the cold buffer in DRAM recovers 10.8 s (about 75%).
- **The choice of metric matters.** Looking only at the main loops, the two mixed configurations lose a similar number of seconds (about 7.6 s and 8.7 s). Total time separates them because the list's setup phase (construction and shuffle) is also latency-bound, and the pointer-chasing thread determines when the program ends.
- **The sequential thread slows down by about 39% on the remote node**, more than expected for a high-MLP pattern. Its throughput drops from about 11.4 to 8.2 GB/s, which suggests a bandwidth limit of the inter-socket link rather than latency (to be verified).

### 14.5 Limitations

- Provisional measurements: governor, turbo and `numa_balancing` not fixed.
- 3 repetitions for total time.
- One microbenchmark only. The emulated slow tier is about 1.5× slower than local memory, against about 2.1× in the paper.
- H1′ (migration overhead) is not tested: it needs a tiering system.
- To check in the paper: which metric it uses for Fig. 1 (total time is assumed here).
