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
2. **Slow-tier emulation**: remote NUMA node with its uncore frequency lowered to 500 MHz (`modify-uncore-freq.sh`), giving ~190 ns on CloudLab c220g5 (Skylake), **and node 1's CPUs taken offline** (`configure_cxl_exp_cores` in `config.sh`). The script writes to `/sys/devices/system/cpu/intel_uncore_frequency`, which requires `CONFIG_INTEL_UNCORE_FREQ_CONTROL`. From memory, this driver does not support Haswell (to be verified); if so, uncore frequency would have to be set via MSRs (to be discussed with the TA).
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

1. **PEBS timestamps**: the tracepoint reads `pebs->tsc`. From memory, this record field exists only from Skylake (PEBS format 3); Haswell uses format 2, so the value would be meaningless (to be verified). Candidate alternative: standard `perf record -d`, which provides data address and time with no kernel patch, adapting the parsing and aligning its clock with the `rdtsc` timestamps of `ldlib.c`.
2. **Event names**: `mem_load_retired.l3_miss` should become `mem_load_uops_retired.l3_miss` on Haswell (to be verified with `perf list`), and `CYCLE_ACTIVITY.STALLS_L3_MISS` becomes `stalls_l2_pending` (also in the parser of `proc_obj_e.py`).
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
| Kernel | `6.8.0-147-generic` |

---

## 8. Open questions for the TA

1. During our measurements, may we set the governor to `performance`, disable turbo and set `numa_balancing = 0`, restoring the original values right afterwards?
2. The kernel puts both NUMA nodes in a single memory tier, so NBT/TPP cannot promote/demote. Is there a recommended way to make node 1 a lower tier?
3. The artifact limits local DRAM with the GRUB `memmap=` parameter, which is a persistent boot change. Is this allowed (e.g., only for a one-time boot), or should we use another method?
4. The artifact lowers the remote uncore frequency to emulate CXL latency. May we change the uncore frequency on this Haswell machine, and through which interface (driver or MSRs)?
5. The artifact also disables HT, swap, ASLR, KSM, THP and the NMI watchdog, and takes node 1's CPUs offline. Which of these may we apply during our runs, restoring them afterwards?
6. If SOAR cannot run on the stock kernel, is installing Linux v5.18 + `nbt.patch` (one-time boot) acceptable?

## 9. Next steps

1. ~~Read the SoarAlto README (kernel requirements, CXL emulation, tier setup).~~ Done (§6).
2. ~~Read `src/microbenchmark/` (E1 code) and the SOAR pipeline.~~ Done (§6.3, §6.4).
3. Read-only checks on the machine: PEBS format, `mem_load_uops_retired.l3_miss`, presence of `intel_uncore_frequency`, free disk space.
4. Clone SoarAlto and GAPBS in the home directory; confirm the findings of §6 on the actual code.
5. Measure real local/remote latencies (e.g., Intel MLC) and compare with the paper's 90/190 ns.
6. Before any custom kernel: persistent journal, `/boot` space check, one-time GRUB boot (TA rules).
