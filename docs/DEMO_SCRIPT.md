# Round 2 demo video: problem, solution, build, live demo (5 minutes)

Team Xyrus · PS-011 Real-Time CMM Quality Dashboard with Automatic Non-Conformance Alerts.

Ground rules for everything we say: all data is synthetic and labelled "Demo data"; we have no
Sakthi numbers, so we talk about mechanisms and give **formulas, not invented figures**; we say
"near-real-time, file-triggered"; escalation timers are shortened for the video and we say so;
we say "aligned with" ISA-18.2 / ISO 14253-1 / IATF 16949, never "compliant".

---

## Part 0: Setting up on a fresh laptop (for whoever records)

Everything runs in Docker; you do not need to install Python or PostgreSQL. Linux (Ubuntu) is
the reference. On macOS use Docker Desktop; on Windows install WSL2 + Ubuntu and run every
command below inside the Ubuntu terminal (Docker Desktop with WSL integration on).

### 1. Accept the GitHub invite

(email, or github.com/notifications) for
`yaswanthme007/smart-cmm-quality`.

### 2. Install the tools (once)

| Tool | Why | Ubuntu command |
|---|---|---|
| Git | clone the repo | `sudo apt install -y git` |
| Docker Engine + Compose plugin | runs db, api, worker, web, mailpit | follow docs.docker.com/engine/install/ubuntu, then `sudo usermod -aG docker $USER` and **log out and back in** |
| make | runs the project commands | `sudo apt install -y make` |
| uv | runs the demo file generator (`make demo-drop`); downloads Python 3.12 by itself | `curl -LsSf https://astral.sh/uv/install.sh \| sh` then open a new terminal |
| Node 24 LTS (optional) | only for `make test` / `make e2e`; the app itself runs in Docker | nodejs.org or `nvm install 24` |
| OBS Studio | screen recording | `sudo apt install -y obs-studio` |

Check: `docker ps` works without sudo, `make --version`, `uv --version`.

### 3. Get the code

(the work is on the `dev` branch)

```bash
git clone https://github.com/yaswanthme007/smart-cmm-quality.git
cd smart-cmm-quality
git checkout dev
```

### 4. Create your `.env`

(secrets are never in Git; each laptop has its own)

```bash
cp .env.example .env
openssl rand -hex 32        # copy the output into JWT_SECRET
```

Edit `.env`: set `POSTGRES_PASSWORD` to anything and put the **same** password inside
`DATABASE_URL`; paste the random value into `JWT_SECRET`; set `DEMO_USER_PASSWORD` to anything.
Keep `DEMO_MODE=true` (one-click demo login) and `ESCALATION_PROFILE=demo` (60 s / 120 s timers).
Leave `AI_ENABLED=false` unless you also want to show PDF extraction (then add a Groq key in
`AI_API_KEY`).

### 5. Start and seed

```bash
make up            # first time builds images: several minutes
make demo-reset    # ≈20 s: demo masters, 30 days of synthetic history, drift on VMC-02
```

Check http://localhost:8000/api/health shows `"status":"ok"` (worker becomes `ok` within ~10 s)
and http://localhost:5173 shows the login page with the demo-user buttons.

### 6. Dry run once, then reset

Open `http://localhost:5173/login?as=owner.vmc02`, run `make demo-drop`, watch the alert pop up,
then `make demo-reset` so the recording starts clean (the live NC must be NC-2026-00042).

### Troubleshooting

| Symptom | Fix |
|---|---|
| `permission denied ... docker.sock` | you are not in the docker group yet: `sudo usermod -aG docker $USER`, log out and in |
| A port is already in use (5432, 8000, 5173, 1025, 8025) | stop the other program, or for PostgreSQL set `DB_PORT=5433` in `.env` |
| Web page shows a red Vite error after `git pull` | `make up` (rebuilds images with new dependencies) |
| Alerts don't pop up | each role must be in its own browser profile / incognito window; check the green "live" dot next to "Demo data" |
| Anything else odd before a take | `make demo-reset`, reload the windows |
| Stop everything | `make down` |

---

## Part 1: The real problems (say these in plant language)

The CMM is the most accurate instrument in the plant, but its verdict travels slowly and then
disappears. These are the problems we heard in the problem statement and in how machining shops
usually run (Section 2.2 of the spec; to be validated with Sakthi):

| # | Real problem on the shop floor | What it costs | Our answer | Shown at |
|---|---|---|---|---|
| P1 | **The Not OK reaches the machine late.** The inspector reads the result on the CMM screen or printout and tells production by phone, WhatsApp or by walking over. Meanwhile the machine keeps cutting. | Every minute of delay is more suspect parts: *bad parts ≈ machine output rate × detection delay*. Containment gets bigger and costlier. | The result file is read the moment the CMM writes it; the owner gets an in-app alert and an email in seconds, and we **measure that time for every Not OK**. | 1:50 |
| P2 | **Nobody clearly owns it.** "Production" is told, not the person responsible for VMC-02 / OP-30 finish boring. Nobody confirms they saw it. | Alerts get lost between shifts; the same defect runs on. | Ownership rules (machine → process → part → department head) name one owner. If nobody acknowledges, it **escalates** to the supervisor, then the Quality Head. | 2:30 |
| P3 | **The fix is not tracked.** Corrective actions live on paper or in a sheet: no evidence, no verification, closure time unknown. | Same root cause comes back; audits find gaps; nobody can say how long problems stay open. | A light 8D flow: acknowledge → containment → 6M root cause → action + target date → evidence → Quality Head verifies. Closure lead time is computed automatically. | 3:05 |
| P4 | **Reports are built by hand.** At shift end someone copies CMM results into Excel to get OK / Not OK counts and trends. | Hours of clerical work; numbers arrive late and with copy errors; trends by machine stay hidden. | Every number on the dashboard comes from stored events, filterable by date, part, machine, process and shift; Excel export in one click. | 0:50 / 4:05 |
| P5 | **Every CMM speaks a different format.** ZEISS CALYPSO writes table files, PC-DMIS writes CSV/Excel, others write AQDEF; layouts differ even on the same brand. | Each new layout becomes an IT project, so integration never happens. | A canonical format + **mapping profiles**: a new layout is a configuration in the UI, not code. Drawing limits come from master data; if the report prints different limits we flag a **limit mismatch** (drawing revision risk). | 4:20 |
| P6 | **We find failures, not drift.** Tool wear slowly pushes a bore toward its limit; every part passes until one suddenly fails. | Scrap and rework that a trend would have prevented. | SPC on every characteristic per machine: I-MR chart with frozen limits and Nelson rules. N3 (6 points steadily rising) **warns before the part fails**. | 1:15 |
| P7 | **Too many or wrong alarms.** Probe errors, borderline readings and repeated failures flood people, so they stop reading. | Alarm fatigue: the real alarm is ignored. | Marginal results are shown but not pushed; one NC per part; repeats link to the open NC (recurrence) instead of new alarms; suspect values flagged "re-measure"; re-inspection OK lets the Quality Head cancel with a reason. Aligned with ISA-18.2 alarm principles. | 2:10 |

One sentence for the judges: **"We don't replace the CMM software; we close the loop from a Not OK
result to a verified fix, with a named owner and a measured time at every step."**

---

## Part 2: Our solution (the closed loop)

```
CMM writes result file ──► read in seconds ──► every size vs drawing limits ──► OK / Marginal / Not OK
        │                                                                      │
        └──── SPC drift warning (before failure)                               ▼
                                         Not OK ──► NC with named owner ──► app alert + email
                                                                 │ no acknowledgement?
                                                                 ▼
                                               supervisor (L1) ──► Quality Head (L2)
owner acknowledges ──► containment ──► root cause (6M) ──► action + evidence ──► Quality Head verifies ──► closed
                                                                                                │
                                                     dashboard: counts, OK %, alert time, open/closed, lead time, trends
```

---

## Part 3: How we built it (30 seconds in the video, the rest for Q&A)

| Plant need | How it is implemented | Why this way |
|---|---|---|
| No change at the CMM | Worker watches a shared folder per CMM; waits until the file size is stable (CMM writes progressively); also manual upload and manual entry | Zero change to CMM programs; works on a plant LAN |
| Any report layout | Adapters (generic CSV/XLSX, CALYPSO-style `_chr.txt`, AQDEF subset, PDF tables) → one canonical record; mapping profiles edited in the UI with live preview | New format = configuration |
| Correct verdict at the limit | Decimal arithmetic rounded to the drawing's decimals; limits inclusive; 10% guard band → Marginal; golden tests from the spec (e.g. 72.030 on a 72.030 limit is conforming) | Floats give 72.030000001 > 72.030 errors |
| Alert can never be lost | Report, measurements, NC, alert and email row written in **one database transaction** (transactional outbox); worker sends email with retries | Upload never waits for SMTP; nothing half-recorded |
| Seconds, not minutes | PostgreSQL LISTEN/NOTIFY → Server-Sent Events to the owner's browser | No extra message broker to run |
| Escalation | Sweeper every 10 s; timers per characteristic class (critical 10/30 min in plant mode, 60/120 s demo) | Escalate only when unacknowledged |
| Trust in the data | Role-based permissions on the server; **append-only audit log** (database trigger rejects edits) | Quality records must be tamper-evident |
| Warn before failure | I-MR limits frozen from a baseline (Quality Head recalculates, audited), Nelson rules 1/2/3/5, Cp/Cpk shown only with ≥ 30 readings and a stable process | Rolling limits hide drift; capability from unstable data misleads |
| Messy PDFs | Deterministic table reading first; only if that fails and AI is switched on, **Groq** reads the PDF text and proposes rows; every number is checked against the PDF and a person confirms before anything is classified | AI never decides OK / Not OK and never alerts |
| Runs in the plant | Docker Compose on one on-prem server; React dashboard; FastAPI + PostgreSQL | Quality data stays inside; no internet needed |
| Proof | 130+ automated tests incl. golden cases, a browser test of the full loop, measured benchmarks in `docs/BENCHMARKS.md` | Numbers we can defend |

---

## Part 4: Recording setup (do this once)

**Machine:** the laptop that will run the demo. Plug in power, close chat apps, turn on "Do not disturb".

```bash
make up            # db, mailpit, api, worker, web
make demo-reset    # 30 days of synthetic history + drift on VMC-02 + clean NC numbering
```

**Browsers: one profile per role.** Cookies are shared inside one browser profile, so use separate
profiles (or one normal window + incognito windows, or Chrome + Firefox). No passwords needed: in
demo mode each link signs in with one click.

| Window | Open this link | Role on screen |
|---|---|---|
| A | http://localhost:5173/login?as=qhead | Quality Head: dashboard, SPC, verification |
| B | http://localhost:5173/login?as=owner.vmc02 | Process Owner of VMC-02: receives the alert (turn sound on) |
| C | http://localhost:5173/login?as=supervisor | Shift Supervisor: receives the escalation |
| D | http://localhost:8025 | Mailpit: shows the email |
| T | Terminal in the repo folder | `make demo-drop` |

**Screen recorder (OBS Studio, free):** canvas and output 1920×1080, 30 fps, MP4; one "Display
capture" scene plus a small webcam corner if you want; microphone noise suppression on. Browser
zoom 110% so numbers are readable. Hide bookmarks bar. Record **each part as a separate clip**
(easier to retake) and join them in the editor.

**Rehearse twice** with a stopwatch. After each take: `make demo-reset` (≈20 s) and reload the
windows (they stay signed in).

---

## Part 5: Shot list and narration (5:00)

| Time | Screen | Do | Say |
|---|---|---|---|
| 0:00–0:35 | Title slide → P1–P7 table (PPT) | – | "Sakthi's CMMs measure to microns, but the verdict travels on foot. A Not OK is read off a screen and phoned to production; nobody clearly owns it, actions sit on paper, reports are rebuilt in Excel, every CMM brand writes a different file, and tool wear is only noticed once parts fail. Every minute of delay is more bad parts." |
| 0:35–0:50 | Loop diagram (PPT) | – | "We built the action layer on top of the CMM software: read the result file the moment it is written, judge every size, tell the owner in seconds, escalate if nobody responds, track the fix to a verified close, and measure every step. All data you will see is synthetic." |
| 0:50–1:15 | **A** Dashboard | Point at tiles, hover a tooltip, click **Not OK** tile → filtered reports, back | "One screen answers PS-011: parts inspected, OK and Not OK, OK percent, alert time, open, pending and closed actions, closure lead time, trends by day, machine and part. Every number is computed from stored events and clicks through to the records." |
| 1:15–1:40 | **A** SPC → stream "DC-101 C-03 … VMC-02 ⚠ N3" | Point at the last six rising points, the N3 signal, the capability banner | "The bearing bore on VMC-02 is creeping up: six parts in a row rising. Every part is still inside the drawing limit, but Nelson rule N3 has already warned the owner. That is tool wear caught before it fails. Capability is hidden because the process is not stable right now." |
| 1:40–1:50 | **T** terminal | Run `make demo-drop` | "Now the CMM finishes the next part and writes its normal result file into the shared folder. Nothing changes at the CMM." |
| 1:50–2:10 | **B** owner window, then **D** Mailpit | Toast appears with sound; open bell; show email in Mailpit | "Within about a second, the owner of VMC-02 gets it: bearing bore 72.034 against a 72.030 limit, 4 microns over, critical characteristic, NC-2026-00042. The same message is already in his email." |
| 2:10–2:30 | **B** click the toast → NC page, timeline | Point at "… ms after file arrived" | "The timeline records file received, alert created, email sent, each with milliseconds. Alert time is stored for every Not OK, so this KPI is measured, not claimed. The owner was chosen by the rule for machine VMC-02." |
| 2:30–3:05 | **C** supervisor window (≈60 s after the drop; cut the wait in editing) | Show the escalation alert | "Say the owner is busy and doesn't acknowledge. After the timer, the shift supervisor is alerted automatically, then the Quality Head. In the plant these timers are 10 and 30 minutes for a critical characteristic; we shortened them to seconds for this video." |
| 3:05–3:45 | **B** NC page | Acknowledge → type containment "Quarantined last 12 parts from VMC-02", root cause **Machine** "finish-boring insert worn", action "replace insert, reduce tool-life counter from 500 to 400 parts", target date → Save → add evidence file → Submit | "The owner acknowledges, which stops escalation. He records containment, the 6M root cause, the action with a target date and attaches the re-measurement as proof, then submits." |
| 3:45–4:05 | **A** same NC | Verify and close; open Dashboard | "Only the Quality Head can close it. The moment she verifies, closure lead time is calculated and the dashboard updates live: open actions down, closed up, VMC-02 trend updated." |
| 4:05–4:20 | **A** Export Excel; Audit log filtered on the NC | Click export, show the sheet; show audit entries | "The shift report nobody has to build by hand, and an audit trail the database itself refuses to edit." |
| 4:20–4:40 | **A** Mapping page | Upload a sample CSV with a new layout, pick 3 columns, preview turns red/green | "A new CMM layout is a configuration: upload a sample, map the columns, preview the verdicts, save. Messy PDFs can optionally go through Groq, but a person confirms every row and the AI never decides OK or Not OK." |
| 4:40–5:00 | Closing slide with the 7 problems ticked | – | "Read the files CMMs already write, name the owner, measure every minute, close the loop. Software only, on-prem, works without AI. Measured numbers are in our repository. Thank you." |

## Part 6: Backup plan

- Record the live part (1:40–4:05) twice; keep the better take.
- If the toast is missed on camera, the bell and the NC timeline still prove the time.
- If anything breaks: `make demo-reset`, reload windows, restart that clip.
- Never edit numbers in post; if a measured time looks odd, re-record.

## Part 7: Numbers we may quote

Only what `make bench` measured on the recording laptop (`docs/BENCHMARKS.md`) and what the
timeline shows on screen. Targets are targets, not results.
