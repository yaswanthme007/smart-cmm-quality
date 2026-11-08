# Round 2 demo script (5 minutes)

All data is synthetic and labelled "Demo data" on screen. Escalation timers are shortened to
60 s / 120 s for the video; say so. "Real-time" = seconds after the CMM software writes its file.

## Before recording

```bash
make up            # db, mailpit, api, worker, web
make demo-reset    # masters + 30 days synthetic history + N3 drift on VMC-02 C-03
```

Open four browser windows (1280×800 or larger), all on http://localhost:5173:

| Window | Login | Start on |
|---|---|---|
| A | `qhead@demo.local` | Dashboard |
| B | `owner.vmc02@demo.local` | Dashboard |
| C | `supervisor@demo.local` | Alerts |
| D | Mailpit http://localhost:8025 | Inbox (empty) |

Password: `DEMO_USER_PASSWORD` from `.env`. Have a terminal ready in the repo root.

## Script

| Time | Show | Say (short) | PS-011 item |
|---|---|---|---|
| 0:00 | Window A, dashboard | "One screen: inspected, OK and Not OK, OK %, alert time, open / pending / closed actions, closure lead time, trends by date, part and machine. Every number is computed from stored events; click any tile to see the records." Click **Not OK** tile → filtered reports | Real-time totals, OK % / Not OK %, trends |
| 0:40 | SPC → DC-101 C-03 on VMC-02 | "Bearing bore on VMC-02: the last six parts rise steadily. Nelson rule N3 is active and the owner already has an SPC warning, while every part is still in tolerance. We warned before it failed. Capability is hidden because the process is not stable." | Classification, trends |
| 1:20 | Terminal: `make demo-drop` | "The CMM writes its normal result file into the shared folder. Nothing changes at the CMM." | Import CMM data |
| 1:30 | Window B | Toast + bell within about a second: "[NOT OK] DC-101 … C-03 Bearing bore Ø72.000 +0.030/-0.000 → measured 72.034 (+0.004 over USL)". Window D: email arrived | Immediate alert to the process owner |
| 1:50 | Open NC-2026-00042, timeline | "Detected, alerted in about a second after the file arrived — the number is stored for every Not OK. The owner is named by the ownership rules: machine VMC-02." | Alert generation time |
| 2:10 | Wait ~60 s (or cut) → Window C | "Nobody acknowledged, so after the demo timer the shift supervisor is alerted. In the plant this is 10 minutes for a critical characteristic, configurable." | Escalation |
| 2:40 | Window B: Acknowledge; containment "Quarantined last 12 parts from VMC-02"; root cause MACHINE "finish-boring insert worn"; action "replace insert, reduce tool-life counter from 500 to 400 parts"; target date; upload evidence; Submit | "Light 8D: containment, 6M root cause, action, target date, proof." | Action owner and closure status |
| 3:30 | Window A: open NC → Verify and close | "Only the Quality Head can close. Closing time is measured automatically." Dashboard updates live: Not OK count, closure lead time, VMC-02 trend | Closure lead time, open/pending/closed |
| 4:00 | Export Excel; Audit log filtered on the NC | "The report nobody builds by hand, and an append-only audit trail: the database rejects edits." | Report export |
| 4:20 | Mapping → upload a new CSV layout, pick columns, preview | "A new CMM layout is a configuration, not code." | Integrate CMM data |
| 4:45 | Close on the dashboard | "Software only, on-prem, works without AI. Synthetic data; measured numbers in docs/BENCHMARKS.md." | – |

## Numbers to quote

Only quote what `make bench` measured on the recording laptop (`docs/BENCHMARKS.md`); never quote
targets as results.

## Reset between takes

`make demo-reset` (≈20 s) restores the exact starting state, including NC numbering (the live NC
is NC-2026-00042).
