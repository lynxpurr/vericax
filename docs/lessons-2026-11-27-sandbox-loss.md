# Lessons — Sandbox loss was a shadow-stack fault (2026-11-27)

The "infra" failures of the n>=3 capability run (19 of 217 episodes) were the
sandbox guest dying in a kernel panic. This file records what the fault is,
how it was isolated, what fixes it in the images, and where the state comes
from (section 6, added on 2026-11-28).
Evidence lives in the local run directories; the specs and the image recipes
carry the requirements.

## 1. The symptom: PID 1 dies, the guest panics

The runtime reports `SandboxUnavailable` or a connection reset. The guest's
console (`logs/vm-console.log`) shows the real event: `systemd[1]: segfault
at ... error 44` followed by `Kernel panic - not syncing: Attempted to kill
init! exitcode=0x0000008b`. systemd's crash handler recurses until the 8 MB
main stack is gone (38 ms to 30 s), then PID 1 exits and the kernel panics.
The crash time is the **first** `segfault at` line, not the panic line.

No agent is needed. Idle VMs crash on their own, 3 to 53 minutes after boot,
and the loss rate rises with episode length: about 7 % for a 10-minute
episode and about 40 % for 30 minutes. The published suite mostly runs under
10 minutes, which is why the batch showed 8.8 %.

## 2. Read the kernel's error code as hexadecimal

`error 44` and `error 46` are `0x44` and `0x46`: user access, read or write,
**shadow-stack access** (bit 6, `X86_PF_SHSTK`), page not present. A day was
spent on "reserved bit plus protection key" by reading them as decimal.

With the right reading every observation lines up:

| instruction | shadow-stack operation | error | address |
|---|---|---|---|
| `ret` after a syscall (`epoll_wait`, `clone3`, `sendmsg`) | reads the token at `[SSP-8]` | 0x44 | S |
| `call` (`call getpid_cached` in the crash handler, or an indirect `call [rax+8]`) | writes the token at `[SSP]` | 0x46 | S-8 |
| explicit `push`, stores to the normal stack | none | no fault | - |

S is constant within one boot and always 0x48 below a 2 MB-aligned address.

## 3. What was ruled out, each by an experiment

| hypothesis | experiment | result |
|---|---|---|
| kernel command line (mitigations, C-state, TSC) | 9 VMs: the stable reference image's full command line, or one group of its flags, or nothing; all rebooted the same way | 7 of 9 panicked in 90 min, 2 of the 3 with the full line |
| kernel version | the reference image's kernel 6.8.0-55 copied into 3 of our VMs | 2 of 3 panicked in 27 min; the 2 controls on 6.8.0-147 also panicked |
| kernel flavour | package lists | both images run the same `-generic` binary; `-virtual` is a metapackage |
| protection keys | smaps of every process | no process holds a pkey-protected mapping |
| CET-built userland alone | 600 alternating CET-built and plain programs pinned to one vCPU | no fault; no process holds a `[shadowstack]` mapping |
| host memory, guest RAM, cgroup OOM, agent commands, parallelism | host and guest records at the crash | all normal |
| CPU mitigation path | the console of VMs with mitigations off | same fault |

## 4. The mechanism that matters for the image

Linux v6.8, `arch/x86/kernel/cpu/common.c`, `setup_cet()`, run for every CPU
in `identify_cpu()`:

```c
	kernel_ibt = HAS_KERNEL_IBT && cpu_feature_enabled(X86_FEATURE_IBT);
	user_shstk = cpu_feature_enabled(X86_FEATURE_SHSTK) &&
		     IS_ENABLED(CONFIG_X86_USER_SHADOW_STACK);
	if (!kernel_ibt && !user_shstk)
		return;
	if (user_shstk)
		set_cpu_cap(c, X86_FEATURE_USER_SHSTK);
	if (kernel_ibt)
		wrmsrl(MSR_IA32_S_CET, CET_ENDBR_EN);
	else
		wrmsrl(MSR_IA32_S_CET, 0);
	cr4_set_bits(X86_CR4_CET);
```

- Measured with a kernel module: `CR4.CET=1` on all 4 CPUs of our guest,
  `CR4.CET=0` when the CPU feature is hidden.
- The XSAVE unit has no CET state (`Enabled xstate features 0x2e7`), so the
  kernel has no way to save and restore the two user registers between
  tasks (section 6).
- Caught in the act by kernel threads reading `IA32_U_CET` and
  `IA32_PL3_SSP` on their CPU every 2 ms and logging every change to the
  serial console: 20 heartbeats of `0/0` on all CPUs, then on CPU 0
  `U_CET=0x1 PL3_SSP=0x7d9ae71fffb8`, and PID 1 dead on that CPU 170 ms
  later.

So the kernel arms CET because the CPU advertises the feature, and a
shadow-stack state left behind by a guest process (section 6) then turns the
next user-mode `ret` or `call` of whichever process runs on that CPU into a
fault. On 2026-11-27 this looked like a state "set from outside the guest":
no long-lived guest process had shadow stacks, and the process that does
enable them lives for a few milliseconds.

## 5. The fix in the images, and its validation

`clearcpuid=519` on the kernel command line. `X86_FEATURE_SHSTK` is word 16
bit 7 and has no name, so the number is the only spelling; the guest prints
`Clearing CPUID bits: 16:7` at boot. The recipe writes it through
`/etc/default/grub.d/99-vericax-cmdline.cfg` and fails the build when
`update-grub` does not carry it into `grub.cfg`.

- 3 FEniCS VMs and 3 CalculiX VMs with the parameter: all 6 ran 90 idle
  minutes without a panic.
- Untreated VMs in the same windows crashed; over the day 4 of 21 untreated
  idle VMs passed 90 minutes.
- An 8-hour idle hold on 6 VMs with the parameter (3 FEniCS, 3 CalculiX)
  ended without a panic; the three rebuilt images passed 2-hour idle soaks
  (3 VMs each) and the model-free acceptance episodes.
- `nousershstk` does not work: it clears only the synthetic `USER_SHSTK`,
  which `setup_cet()` sets again.

## 6. Root cause (2026-11-28), found from inside the guest

Found without host privileges, with one untreated VM: kernel threads on two
CPUs monopolise the CPU and poll the CET registers; threads on the other two
do the same every 2 ms and write `IA32_U_CET` and `IA32_PL3_SSP` back to zero
when they change. In 84 minutes the two busy CPUs saw no change; the two idle
CPUs saw nine, each undone within 6 ms, so the VM stayed alive and could be
inspected. A control VM on the same image and command line without the
write-back panicked after 1258 s.

1. **Trigger.** `fwupd-refresh.timer` starts `fwupd`, which runs
   `/usr/libexec/fwupd/fwupd-detect-cet`, a small helper that probes whether
   shadow stacks are enforced: it installs a SIGSEGV handler and executes a
   `call` whose return address it then discards (`mov rax,[rsp]; add rsp,8;
   jmp rax`). The helper runs with a shadow stack enabled by the kernel (a
   kprobe on `shstk_setup` fired 9 to 11 ms before each register change).
   Starting the service by hand reproduced it four times out of five.
2. **Leak.** After the helper has run, `IA32_U_CET=1` and its `IA32_PL3_SSP`
   stay in the CPU, and the next user process on that CPU faults on its first
   `call` or `ret`: in one event fwupd, systemd-journald, rsyslog's imklog and
   two apport processes, all at the same address. In an untreated VM the next
   process is often PID 1, which is the panic.
3. **Why the registers are not switched.** The CPU (AMD Ryzen 9 PRO 8945HS)
   sets CPUID 7.0.ECX bit 7 (shadow stack) but reports no CET state in CPUID
   leaf 0xD: `XCR0 = 0x2e7`. The kernel (6.8) enables user shadow stacks on
   the strength of the first bit and has no XSAVE component with which to
   save and restore the two registers between tasks. The same two leaves are
   read from the host without privileges, so this is the hardware's
   combination, not something the hypervisor removed.

`clearcpuid=519` removes the first bit; the kernel then refuses shadow stacks
altogether and the helper cannot arm anything. The fix is therefore complete
for these images, not a workaround for one trigger.

Not checked: why a reference image on the same host with its own fwupd never
crashed, and whether a kernel newer than 6.8 refuses shadow stacks on this CPU
(the host runs 7.0 with the same CPU, fwupd and the timer, and shows no
process with shadow-stack thread features).

## 7. Operational lessons

- Keep the per-episode guest console. It was the only place the crash showed,
  and it answered every question once the error code was read correctly.
- Fail-fast plus a retry with a new episode bounds the damage, but it is not
  a fix: the T1 pilot spent 41 % of its tokens on two lost attempts. Fix the
  image before running long tasks at scale.
- An idle soak is the model-free reproducer: boot, configure like an episode,
  never contact the guest, read only the container's log stream.
- One variable per experiment, a control group in the same window, and a
  check inside the guest that the knob took effect (`/proc/cpuinfo` without
  `user_shstk`; the boot line). The first attempt used bit 231 and changed
  nothing; the check caught it in 4 minutes.
- Bit numbers are kernel words: `X86_FEATURE_<X>` is `word * 32 + bit`. The
  kernel's own `Clearing CPUID bits:` line is the confirmation.
- Before ruling out a component, check what its tools actually measure: the
  EIO that `/dev/cpu/N/msr` returns for the CET registers is the device's
  own filter, not a fault from the hypervisor.
