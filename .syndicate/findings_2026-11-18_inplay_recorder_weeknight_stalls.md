# Findings — lane `inplay-recorder-weeknight-stalls` (2026-11-18, session 7d49bbd3)

Side session of local_cbc2cd31 (M3 paper book, todo #736). Question: why did the in-play recorder stop polling
Kalshi for every market at once on the weeknight of 2026-11-16, and is a fix needed. All times are **CST (UTC-6)**,
including dates before the 11-01 DST change (those clocks read one hour later in CDT). Everything here is read-only:
recorder outputs in `C:/tmp/inplay_*`, fleet logs read at nice 19, Windows event log, and two 3-minute dry runs.

## Answer

**The recorder is starved of CPU by its own priority.** It runs at Windows Idle priority and inherits memory
priority 2 (of 5) and low I/O priority from its Task Scheduler task. In the live weeknight evening all 12 host cores
are held by Normal-priority work: the fleet VM (`vmmemwsl`), Defender, System, the remote-desktop session. An
Idle-class thread then runs only when Windows' anti-starvation boost picks it, roughly once every ~4 s. One
recorder request needs many schedulings: connect, TLS handshake, send, several response reads, the JSON parse and
the row writes. So a request that normally takes 0.2 s took 30-110 s, and on the worst evenings the whole loop
froze for minutes.

It is not Kalshi (no 429 and no error), not the network (file reads with no network froze in the same minute), and
not a pause (the fleet VM kept running throughout). The fix is to run the recorder at Normal priority. It costs about
4% of one core, 0.3% of the host. It is drafted with tests below and is not applied. It needs a loan of
`scripts/inplay_recorder.py` from lane `in-game-trading` and the user's yes, and tonight's A/B probe reading should
come first.

## 1. The 11-16 stalls, step by step

The recorder is one thread: Kalshi batches, then the fleet's Polymarket files over `\\wsl.localhost` (every 60 s),
then ESPN and OddsAPI per sport (every 60 s), then a 1 s sleep, plus a re-read of the Kalshi capture files every
10 min. Each row is stamped when its step returns, so the gap between two stamps is the duration of the step
between them. Usual durations on 11-16: Kalshi request p50 0.19 s, ESPN 0.14 s, OddsAPI 0.24 s, Polymarket
file read 0.11 s, ticker re-read 7.4 s.

**Stall 1, 7:24:58-7:26:08 PM (69.7 s): ONE Kalshi request.** The Kalshi batch stamped 7:24:58.595 was followed by
the next batch of the same cycle at 7:26:08.280. Nothing else ran in between, and no error was logged: the
`get_json` returned normally after ~70 s. Its 15 s timeout is per socket operation, so a request that keeps trickling
never trips it. The requests just before were already slow (1.3, 1.4, 5.3, 2.4, 7.1 s, against 0.2 s usually), and
so were those after (5.7, 4.1, 4.8, 15.0 s).

**Stall 2, 7:30:54-7:33:10 PM (136 s): every step, Kalshi or not.** After the last batch of a cycle (itself 4.6 s):

| step | took | usual (p50) | network? |
|---|---|---|---|
| Polymarket fleet file, NBA (`\\wsl.localhost`) | 53.7 s | 0.11 s | no |
| ESPN NBA / OddsAPI NBA | 4.2 s / 17.2 s | 0.14 / 0.24 s | yes |
| ESPN NFL / OddsAPI NFL | 6.0 s / 6.6 s | | yes |
| ESPN NHL | 3.0 s | | yes |
| Kalshi capture files re-read (3 files, `\\wsl.localhost`) | 35.6 s | 7.4 s | no |
| first Kalshi batch | 8.0 s | 0.19 s | yes |

Three different web hosts and two network-free file reads slowed together in the same two minutes: 5x for the ticker re-read, 20-500x for the rest.

**There were smaller ones the tool does not count.** `loop_stalls` counts gaps over 60 s only. At 6:59-7:01 PM three
Kalshi requests in a row took 55.2, 51.2 and 34.1 s. Through the evening, 13 minutes had a request over 10 s
(6:44, 6:52-7:02, 7:26-7:27, 7:33, 7:39, 7:53 PM).

## 2. Why it is CPU starvation, and not the alternatives

The hypotheses were written to the lane (commit `311340797`) before the probe was built.

- **H4, the `\\wsl.localhost` read alone: FALSE.** Stall 1 was a single HTTPS request with no file read.
- **H2, network or remote latency: FALSE as the cause.** The network-free 9P reads in stall 2 slowed as much as
  the HTTP calls did. On 11-17 an ESPN request died after 142 s with
  `SSLEOFError(8, 'EOF occurred in violation of protocol')`, meaning the server closed a TLS exchange the client
  had not finished. That is a slow client, not a slow server.
- **H3, a host or VM pause: FALSE.** A per-second sampler inside the fleet VM (lane nba-overlay-card-cost,
  `C:/tmp/railload/cost790_samples_1116.txt`, 23:55Z-04:00Z) kept writing through both stalls. Its longest gap at
  7:25 PM was 2.9 s. The Windows System log for 6:40-7:38 PM has no power, sleep or disk event, and there is no
  Resource-Exhaustion event since 10-18.
- **H1, host CPU starvation: SUPPORTED by five readings.**
  1. Every kind of step slowed together (section 1).
  2. **The fleet slowed in the same minutes, but far less.** The VM sampler's 1 s loop averaged 1.82 s per tick at
     7:25 PM, against 1.07-1.12 s in calm minutes. The fleet's WNCAAB live re-sim (4 jobs) took 91 s at 7:26:18 PM,
     against 30-39 s from 7:20 to 7:28 PM. NCAAB's walls are not used here: they swing from 13 to 98 s outside the
     stalls as well. The Normal-priority VM lost under 2x. The Idle-priority recorder's steps took 5-500x their
     usual time. That asymmetry is what a priority-starved process shows; a host-wide stall would hit both alike.
  3. **Per-minute join, 11-16, 5:55-10:00 PM** (recorder requests joined to the VM sampler; 241 minutes with both).
     The VM tick's minute mean was 1.37 s (median) in the 13 minutes with a recorder request over 10 s, 1.22 s in
     the 44 minutes with a slowest request of 2-10 s, and 1.07 s in the 184 minutes where every request took 2 s or
     less.
  4. **Dose-response, 11-17.** Lane layer2-board-process-split ran a fixed-work bench in the VM every 30 s
     (`C:/tmp/l2split/l2s_bench_1117.txt`). Its CPU-seconds per fixed work rise when the host gives the VM fewer
     or slower cycles. Joined with the recorder's requests in the same 30 s:

     | bench CPU-s per fixed work | half-minute windows | with a request > 10 s | with a request > 2 s |
     |---|---|---|---|
     | < 0.12 (calm) | 293 | 0.0% | 1.0% |
     | 0.12-0.16 | 143 | 0.7% | 5.6% |
     | 0.16-0.22 | 66 | 1.5% | 21.2% |
     | 0.22-0.30 | 50 | 16.0% | 50.0% |
     | >= 0.30 | 42 | 26.2% | 73.8% |

     Per request, over the same windows: calm (< 0.12), n = 1,566, p90 0.20 s, p99 0.4 s, none over 10 s;
     0.12-0.22, n = 4,027, p99 1.8 s, 0.05% over 10 s; >= 0.22, n = 1,556, p90 1.02 s, p99 13.2 s, 1.29% over 10 s.

  5. **A direct host reading at the same minutes.** Lane layer2-board-process-split read Windows `Get-Counter`:
     at 7:36 PM and 8:05 PM CST on 11-17, all 12 cores were 100% busy and the clock ran at 56-64% of nominal. At
     8:06 PM the split by class was: `vmmemwsl` 6.4 cores, System 0.8, remoting 1.1, Defender 0.3, Normal-class
     processes 0.85, Idle-class 0.2. The slowest recorder request in each half-minute from 7:35 to 7:38 PM took
     11.6-45.8 s. From 8:05 to 8:07 PM, two of the four half-minutes had one of 24.6 s and 18.9 s.

**Mechanism (consistent with the readings; not measured directly).** Windows schedules by strict priority. A ready
Idle-class thread (base priority 4) runs only when no Normal-class thread (8) wants a core. Once a second the
balance-set manager boosts threads that have been ready for about 4 s to priority 15 for a few quanta. A thread
that needs about 10-20 schedulings per request therefore takes about 40-80 s. That matches the 30-110 s requests.

**What the recorder runs at (read 2026-11-18 8:1x AM).** The nightly `pythonw` (pid 21752) reads class Idle, memory
priority 2, I/O priority 1 (low). The recorder is its child: it inherits memory priority 2 and low I/O, and then
sets Idle class itself (`scripts/inplay_recorder.py`, since `775f714f8`, 10-20). Every recording since 10-22 ran
this way.

## 3. Other nights

Two counts per night. The gap tool on main (`scripts/inplay_poll_gaps.py`) gives `loop_stalls` (gaps over 60 s
between any two Kalshi batches), 429s, and the share of time with no quote in a 60 s window (M3's entry window).
The **slow** column counts gaps over 30 s between two Kalshi batches with no `kalshi_error` logged between them,
so it excludes the 429 back-off.

| night | day | slow > 30 s | slow-request hours (UTC-6) | max | loop_stalls (s) | 429s | no quote in 60 s |
|---|---|---|---|---|---|---|---|
| 10-28 | Wed | 8 | 5-8 PM | 48 s | 0 | 111 | 2.07% |
| 10-30 | Fri | 3 | 5, 9 PM | 60 s | 0 | 232 | 0.13% |
| 10-31 | Sat | 48 | 9 AM-5 PM | 319 s | 12 (1,420) | 490 | 22.6% |
| 11-01 | Sun | 8 | 11 AM-1 PM | 183 s | 1 (183) | 157 | 1.34% |
| 11-04 | Wed | 3 | 6 PM | 84 s | 1 (84) | 236 | 0.57% |
| 11-07 | Sat | 9 | 11 AM-5 PM | 441 s | 4 (891) | 564 | 16.1% |
| 11-10 | Tue | 1 | 6 PM | 72 s | 3 (487) | 88 | 1.85% |
| 11-14 | Sat | 4 | 4-9 PM | 38 s | 0 | 1,552 | 26.7% |
| 11-15 | Sun | 2 | 5, 7 PM | 34 s | 0 | 903 | 1.43% |
| 11-16 | Mon | 7 | 6-7 PM | 136 s | 2 (206) | 93 | 1.99% |
| **11-17** | **Tue** | **19** | **7-9 PM** | **579 s** | **3 (758)** | 34 | **9.52%** |

No such stall on 10-20, 10-22, 10-23, 10-24, 10-25, 10-26, 10-27, 10-29, 11-02, 11-03, 11-08, 11-11 or 11-13
(10-26's 5 loop stalls all follow 429s). 11-05 and 11-09 each had one at about 11 PM.

- **The worst so far is the latest: 11-17, 7:17:44-7:27:23 PM, about 9.6 min with no Kalshi poll.** One Polymarket
  file read took 222 s, the next two took 40 and 54 s, and an ESPN request failed after 142 s with
  `SSLEOFError`. The fleet's 1,510 s board build ran over the same window (7:05-7:30 PM, layer2 findings,
  reading 2). On 11-17 there was no quote within 60 s for 9.5% of the time, against 2.0% on 11-16.
- On weeknights it is an evening thing: 6-9 PM CST, the live window, which is M3's entry window too.
- On Saturdays the 429 starvation (fixed by lane inplay-recorder-discovery, now on main) dominates the gaps.
  These slow requests come on top of it.

## 4. Fix (DRAFTED, NOT APPLIED)

**Run the recorder at Normal priority.** The draft adds `--priority {normal,idle}`, default `normal`, which sets
Normal class and memory priority 5. `idle` keeps today's behaviour. Each call raises if it fails, because the Idle
call once failed silently. The other nightly steps (scoreboard, sweeps), which are CPU-heavy research, stay at
Idle.

- **Cost, measured.** A dry run of the current main recorder (the new paced loop, 824 tickers, 4 sports) used
  7.16 CPU-s in 180.4 s. That is 0.040 of one core, about 0.33% of the 12-core host, running x64 Python under
  emulation on this ARM64 host (8:02-8:05 AM CST, host 68-81% busy).
- **Why not Below Normal.** Priority is strict: Below Normal (6) still loses every core to Normal (8) threads, so
  it would starve the same way.
- **Why not keep-alive connections or threads.** Fewer schedulings per request shortens a stall, but each
  scheduling still waits ~4 s. Threads in the same process starve together.
- **Why not move the recorder into WSL at nice 19.** Writing `/mnt/c` from the VM costs Defender about
  1.2-1.4 cores (layer2 findings, learnings 11-17).
- **The fix must stay in `inplay_recorder.py`.** The nightly re-syncs a fixed `RUNNER_FILES` list, so a new
  helper module would never reach `C:/tmp/inplay_runner`.
- **Rule touched:** learnings 2026-10-06, "production shares a CPU with research". The recorder stops being treated
  as research: it is a latency-bound poller whose cost is measured above.
- **Not covered:** the low I/O priority the task hands down. Changing it needs an undocumented `ntdll` call, and
  nothing here shows I/O was the bottleneck.

Draft files, outside the repo (shared notes folder, `inplay-recorder-weeknight-stalls_fix_draft/`):
`inplay_recorder.priority.patch`, against the recorder as of `a2af81258` (unchanged on main since), plus
`test_inplay_recorder_priority.py`. Tests: 7 new
+ the 8 discovery tests pass on the patched copy. A live 50 s run of the patched copy read back class Normal with
memory priority 5 (`--priority normal`) and class Idle (`--priority idle`).

## 5. Measurement owed before landing: A/B probe (PRE-REGISTERED, 2026-11-18 ~8:30 AM CST, before any evening reading)

The probe is `scripts/inplay_sched_probe.py` (this lane; 11 tests pass). Two copies run side by side, `--priority idle`
(Idle class + memory priority 2, as the nightly's recorder runs) and `--priority normal`. Every 10 s, on the same
wall-clock slot, each copy records its wake lateness, sends ONE recorder-shaped Kalshi request (50 tickers, the
recorder's own `get_json`) and reads host busy since its previous slot (`GetSystemTimes`). Run 5:30-9:30 PM CST
(23:30Z-03:30Z). Extra load: 0.2 req/s on Kalshi's public endpoint, beside the recorder's ~0.5 req/s on a weeknight
(the discovery lane validated 1.25 req/s), and about 1 ms of CPU per slot. Read with `--analyse <dir>`. A smoke run
at 8:11 AM CST read back the right class and memory priority in both copies, and both answered in 0.22 s on an
81%-busy host.

- **P1 (H1 predicts).** In slots with host busy >= 0.95 (at least 100 pairs, else NOT TESTABLE that evening), the
  Idle copy has p99 >= 5 s and >= 1% of requests over 5 s. The Normal copy has p99 <= 2 s and <= 0.2% over 5 s.
- **P2.** In slots with host busy < 0.80, both copies have p99 <= 2 s.
- **FALSIFIED (priority is not the lever)** if, in the busy slots, the Normal copy's share over 5 s is at least half
  the Idle copy's (they slow together). Also falsified if the Idle copy's p99 is under 2 s in busy minutes while
  the nightly recorder logs a request over 30 s in the same minute.

Launching the two copies needs the user's OK: they outlive this turn.
