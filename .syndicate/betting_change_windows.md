# Betting-change windows — live-betting changes load only here

**User decision, 2026-11-18 ~12:05 PM CST:** "batch the betting changes into rare windows".
Lane `betting-change-windows`.

## Why

- The adopted scale-up gate counts graded games submitted after the last live-betting change. It needs 800, and the
  live book grades about 24 games a day, so the gate needs about 33-36 change-free days.
- On 11-17/18, seven betting changes loaded in about 32 hours (BC-042, 045, 046, 047, 048, 049, 050). Each restarted
  the count (finding F12 in `findings_2026-11-18_portfolio_monitor.md`).
- Changes that land one at a time, every few hours, can neither be measured one by one nor let the gate ever read.

Effective from: `2026-11-18T18:00:00Z`

(Loads before this instant predate the rule and are not checked.)

## The rule

1. **A live-betting change loads only inside a window below.**
   - A live-betting change is any fleet load (code or env) that changes which live bets are placed, how they are
     sized, or how they are held or exited (`scripts/betting_change.py`'s definition).
   - Display-only, ledger-only, paper-only and shadow-only changes are not betting changes and may load at any time.
2. **Between windows, betting changes queue.** A fleet ff ships ALL of main, so a queued change must either:
   - land on main **default-off** (absent env = old behaviour) and be switched on in a window; or
   - wait on its branch until the window.

   A change that is on by default must not reach main between windows, or the next unrelated ff loads it.
3. **Each window loads its batch together:** one ff and one drained down/up where possible. Each change is still
   registered as its own `yes` row. Changes in one window are measured together against the period before it.
4. **A window may load nothing.** Then the gate's count simply continues. Two quiet windows in a row (about 4 weeks)
   is what lets the gate reach 800 at today's volume.
5. **Exceptions, allowed outside a window and recorded with their reason:**
   - **(a) a revert** of a change that is misbehaving;
   - **(b) a pure risk reduction:** kill switch, lower stakes or caps, pausing a defective money path (never a market
     switch for performance reasons, learnings line 1056);
   - **(c) a fix for a broken money path:** orders failing, mis-sized, or unreconciled.

   Pass `--outside-window "<reason>"` to `deploy_preflight.py` and to `betting_change.py add`/`resolve`, and say why
   in deploys.md.
6. **Enforced by:**
   - `deploy_preflight.py --betting-change yes`: outside a window, without `--outside-window`, it returns
     `OUTSIDE_WINDOW` (exit 8). The deploy guard blocks any deploy whose preflight is not CLEAR.
   - `betting_change.py add --kind yes --loaded-at <t>` and `resolve`: a load time outside every window is refused
     without `--outside-window`, and the reason is written into the row.
   - `--betting-change` is declared by the deployer. A deploy that does not declare it is not checked, so the
     declaration is part of the protocol, not a convenience (CLAUDE.md, "Before any deploy").

## Schedule

Tuesdays 2:00-7:00 AM CST (08:00-13:00Z): after Monday's games have settled and before the day's slates. Every second
Tuesday. The windows below are UTC and machine-read: keep the format, one per line.

## Windows (UTC)

- 2026-11-24T08:00:00Z .. 2026-11-24T13:00:00Z
- 2026-12-08T08:00:00Z .. 2026-12-08T13:00:00Z
- 2026-12-22T08:00:00Z .. 2026-12-22T13:00:00Z
- 2027-01-05T08:00:00Z .. 2027-01-05T13:00:00Z
- 2027-01-19T08:00:00Z .. 2027-01-19T13:00:00Z
- 2027-02-02T08:00:00Z .. 2027-02-02T13:00:00Z
- 2027-02-16T08:00:00Z .. 2027-02-16T13:00:00Z
- 2027-03-02T08:00:00Z .. 2027-03-02T13:00:00Z

Add later windows in the same format before the last one passes. With no future window listed, every betting change
is outside and needs an exception, which fails closed.
