# Machine requirements

What we need to reproduce *Tiered Memory Management Beyond Hotness* (SOAR, baselines, CXL emulation).

## Required

**Hardware**
- **Intel CPU, Skylake or newer**: AOL uses Intel offcore counters (`OFFCORE_REQUESTS.DEMAND_DATA_RD`, `OFFCORE_REQUESTS_OUTSTANDING.*`); SOAR uses PEBS.
- **Two memory tiers**: dual-socket NUMA server (remote node = emulated CXL), or a real CXL expander.
- **RAM**: ≥ ~64 GB per node (workload RSS 8–35 GB, bc-urand ~20 GB).

**Access**
- **Bare metal** (no VM): PEBS, offcore counters and uncore frequency are usually not exposed in a VM.
- **Root**: `perf` counters, uncore frequency via MSRs, disabling remote cores, cgroups/`numactl`, kernel installs.
- **Custom kernels + reboot**: Nomad and Colloid are kernel patches; TPP/NBT depend on the kernel version.
- **Exclusive use** during measurements.

**Software**
- `perf`, `libnuma`/`numactl`, cgroups v2, gcc/make, git, Python
- SOAR code (`MoatLab/SoarAlto`), GAPBS

## Nice to have

- **Remote console (IPMI/iDRAC)** to recover from a kernel that does not boot
- **Intel MLC** to validate tier latencies (~90/190 ns)
- **Intel PCM** for uncore bandwidth/traffic
- **Control over turbo, C-states, hyper-threading** for stable measurements
- **≥ 8–10 cores per socket** (paper uses 8 threads)
- **Second machine with real CXL** (Sapphire Rapids or newer)
- **Tens of GB of disk** for kernels, graphs, logs
- **`tmux`/`screen`** for long runs

> **Ask the TA first:** bare metal + root + ability to change kernels.






<!-- NOTE -->
<!-- GASPR credentials, sudo given, follow setting up default kernel as recovery mode so that we can cover mess up. -->
<!-- cloudlab in case no PMU -->