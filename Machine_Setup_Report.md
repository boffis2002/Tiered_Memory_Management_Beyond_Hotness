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
- **Both nodes are in the same memory tier.** Promotion/demotion only moves pages between different tiers, so **NBT and TPP would never migrate anything** on this setup. Offlining node 1's CPUs (as in the paper's CXL emulation) is probably not enough, since the tier depends on the node's abstract distance set by the memory driver, not on the presence of CPUs (to be verified).

Impact on the plan:

| Experiment | Works as is? |
|---|---|
| E1 (static placements) | ✅ placement controlled with `numactl`/`mbind` |
| E2 (AOL, P, K calibration) | ✅ counters only |
| SOAR (first placement) | ✅ probably |
| E3 baselines NBT / TPP | ❌ need two memory tiers (kernel change or authors' setup) |
| E3 baselines Nomad / Colloid | ❌ custom kernels (follow the TA safety rules) |

---

## 6. Original state (to restore after every experiment)

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

## 7. Open questions for the TA

1. During our measurements, may we set the governor to `performance`, disable turbo and set `numa_balancing = 0`, restoring the original values right afterwards?
2. The kernel puts both NUMA nodes in a single memory tier, so NBT/TPP cannot promote/demote. Is there a recommended way to make node 1 a lower tier?

## 8. Next steps

1. Read the SoarAlto README (kernel requirements, CXL emulation, tier setup).
2. Measure real local/remote latencies (e.g., Intel MLC) and compare with the paper's 90/190 ns.
3. Before any custom kernel: persistent journal, `/boot` space check, one-time GRUB boot (TA rules).
