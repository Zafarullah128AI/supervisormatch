# SupervisorMatch — Complete Project (Exhibition-ready)

A complete, designed web application: students submit FYP ideas, get ranked
supervisor matches, and complete the full approval cycle. The website is
served by FastAPI itself — no Streamlit, no second server, no React build.

## Run locally (one terminal, one URL)

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open: **http://127.0.0.1:8000**

API docs (for testing endpoints directly): http://127.0.0.1:8000/docs

## Default accounts

- **Admin:** admin@sbbusba.edu.pk / admin123
- **Teachers (100 seeded):** their email / teacher123
- **Demo student (exhibition):** demo@student.sbbusba.edu.pk / demo123
  (Zafarullah Shah, 24BS(IT)128)

## Exhibition mode — try it in one click

The login page has one-click demo buttons — **Try as Admin**, **Try as
Teacher** (Sir Ghulam Mustafa), **Try as Student** — so a judge can open any
role instantly without registering.

The admin dashboard has **🔄 Reset demo data**: it wipes every idea,
request, match, rating and notification, then re-seeds the admin, the demo
student and the 100 supervisors — so the next judge can try the full approval
cycle again from a clean slate.

Other professional touches: public landing page with live stats and feature
cards, dark / light mode toggle (top-right, saved per browser), modern font,
favicon.

## The complete approval cycle

```
Student submits idea
  → system matches + ranks supervisors          (idea status: matched)
Student sends a request to a supervisor
  → supervisor AND admin are notified           (idea status: requested)
Teacher accepts  → request goes to admin         (status: teacher_accepted)
   or rejects    → student is notified          (status: rejected)
Admin approves   → supervisor is finally assigned, load +1,
                   all other open requests for that idea are closed,
                   student + supervisor are notified
                   (request: approved, idea: assigned)
   or rejects    → student + supervisor notified (status: admin_rejected)
Admin can also approve a still-pending request directly, or assign any
supervisor manually from the Approvals page (override).
Student can cancel an open request, and rate the supervisor after assignment.
```

Every step creates an in-app notification. The 🔔 bell in the top bar shows
the unread count; the Notifications page lists everything.

## Features

- 3 roles with JWT login: Student / Supervisor / Admin
- Ranked matching with score bars, rank medals (#1, #2, #3...), and
  "why matched" explanations (TF-IDF + light stemming + domain boost +
  verified-faculty boost + capacity/load filter)
- **Idea Quality Checker** — score 0–100 with a grade and concrete
  suggestions (add detail, name the domain and technology, state the problem)
- **Gibberish detection** — random-letter input like `sdfgdsjfgfsdhfsdfsdfsdifkj`
  is flagged in the checker, rejected on submit, and caught by the assistant
- **Idea Uniqueness Check** — TF-IDF similarity against a sample archive of
  30 past FYP titles (`past_fyp_titles.csv`); warns when an idea was done before
- **AI assistant chatbot** (💬 button, bottom-right) — **Gemini-powered when
  a key is set**, rule-based fallback otherwise. The local matching engine
  still computes every fact (idea quality, originality, top 3 supervisors)
  and those facts are passed into the Gemini prompt, so the model discusses
  real computed data instead of inventing names or numbers. The chat header
  shows which engine answered: **✨ Gemini AI** or **rule-based (offline)**.
  Gibberish input never reaches the LLM — the local check catches it first.
  See "Gemini AI assistant" below for the key setup.
- **Supervisor Compare** — pick 2–3 supervisors in the directory and compare
  them side by side; **Shortlist** (☆) saves favourites on the device and
  shows them on the student dashboard
- **Admin analytics charts** — requests by status (doughnut) and supervisor
  load vs capacity (bar), drawn with Chart.js bundled locally
  (`frontend/chart.min.js`, so charts work even without internet)
- **Evaluation page with model comparison chart** — TF-IDF-only vs full
  pipeline vs BERT hybrid on 10 labeled test ideas (Hit@3, Hit@5, MRR, NDCG@5)
- Supervisor rankings page: ranked by average student rating, then approved
  assignments, then total matches; ratings shown in the directory
- Admin: pending approvals queue, manual assignment override, teacher
  add/edit/deactivate, student list, stats dashboard, final assignments
  with CSV export, demo-data reset
- Faculty directory with search + department filter
- 8 tables: users, supervisor_profiles, student_profiles, project_ideas,
  matches, requests, feedback, notifications
- Designed UI: custom HTML/CSS (no framework), responsive cards, status
  badges, stat cards, bar charts, dark mode

## Evaluation results (10 labeled test ideas, 100 supervisors)

| Method | Hit@3 | Hit@5 | MRR | NDCG@5 |
|---|---|---|---|---|
| TF-IDF only | 0.4 | 0.6 | 0.317 | 0.386 |
| Full pipeline (TF-IDF + domain boost + capacity) | 0.7 | 0.8 | 0.57 | 0.628 |
| Hybrid (0.4 TF-IDF + 0.6 BERT) | 0.8 | 0.9 | 0.72 | 0.765 |

The BERT row was measured once on a machine with the model installed
(`backend/bert_evaluation.json`) and is shown as a reference when BERT is
not loaded. 3 of the 10 test ideas still miss their expected supervisor:
the IoT-attendance idea expects Mr. Wagan, the exam-dashboard idea and the
campus-network idea expect Mr. Mustafa and Dr. Mairaj — their profiles use
short, generic interest phrases ("Smart systems", "Data science",
"Computer networks") without the idea's keywords, so they rank below
keyword-rich sample profiles. Supplying their real research interests
improves those matches.

## Dataset note (for the report)

100 teachers: 12 Real + 88 Synthetic, clearly badged in the directory.
State in the report that synthetic augmentation was used for testing.

## Deploy to a live link (Render, free)

Netlify cannot host this project — it has a Python (FastAPI) server and a
database, not just static files. Render is the equivalent free host for it:

1. **Put the code on GitHub** (no git commands needed):
   - Create a free account at github.com, then a new repository
     (e.g. `supervisormatch`). Make it Public.
   - On the repo page: Add file → Upload files → drag this whole folder
     in (or the zip, extracted). Commit.
2. **Create the Render service:**
   - Create a free account at render.com (sign in with GitHub is easiest).
   - Dashboard → New + → Web Service → pick your `supervisormatch` repo.
   - Render reads `render.yaml` automatically: Python 3.11.9, installs
     `requirements.txt`, starts `uvicorn backend.main:app`.
   - Click **Create Web Service** and wait ~3–5 minutes for the first build.
3. **Copy the live link** (e.g. `https://supervisormatch.onrender.com`) and
   use it for the exhibition. Open it once before the exhibition so the
   server is warm.

Notes:
- The free plan sleeps after ~15 minutes of no traffic; the first visit
  after that takes ~30–60 seconds to wake up. Open the link once before
  your demo slot.
- The free plan has no permanent disk: the SQLite database resets when the
  service restarts, and the app re-seeds the admin, demo student and 100
  supervisors automatically. That is fine for the exhibition demo (fresh
  data every time); it is not suitable for real production use.

## Project structure

```
supervisormatch_complete/
├── data.csv               # 100 teachers (12 Real + 88 Synthetic)
├── past_fyp_titles.csv    # sample archive of 30 past FYP titles (demo data)
├── evaluation.py          # Phase 10 evaluation (10 labeled ideas)
├── requirements.txt       # pinned versions tested locally
├── render.yaml            # Render deploy config (Blueprint)
├── runtime.txt            # Python 3.11.9
├── README.md
├── frontend/
│   ├── index.html         # All pages (single-page app)
│   ├── styles.css         # Complete design + dark mode
│   ├── app.js             # API client + views + notification bell
│   └── chart.min.js       # Chart.js 4.4.1, bundled locally (offline-safe)
└── backend/
    ├── main.py            # FastAPI app — all endpoints + serves frontend
    ├── database.py        # SQLite schema + seeding (admin + CSV + demo student)
    ├── auth.py            # PBKDF2 hashing + JWT (HS256)
    ├── assistant.py       # Gemini chatbot (grounded) + rule-based fallback
    ├── nlp.py             # Matching engine + quality/gibberish/uniqueness checks
    ├── bert_evaluation.json # cached BERT metrics (measured once, see README)
    └── supervisormatch.db # created automatically on first run
```

## Gemini AI assistant (free key)

Without a key the chatbot answers with built-in rules. With a free Gemini
key it answers like a real AI assistant — still grounded in the locally
computed facts (quality, originality, top supervisors), so it cannot invent
supervisor names or scores.

**1. Get a free key:** open https://aistudio.google.com → sign in with
Google → **Get API key** → **Create API key**. The free tier is enough for
the exhibition demo.

**2. Use it locally:** the project includes a `.env.example` file — rename
it to `.env` and replace the placeholder with your key:

```
GEMINI_API_KEY=your-key-here
```

Then restart the server. The `.env` file is git-ignored, so the key never
goes into the zip or onto GitHub. (You can also set the variable directly:
Windows `setx GEMINI_API_KEY "your-key-here"`, then restart the terminal.)

**3. Use it on Render:** Render dashboard → your service → **Environment**
→ Add `GEMINI_API_KEY` with your key → the service redeploys automatically.

**How to check it works:** open the chat — the header shows **✨ Gemini AI**
when Gemini answered, or **rule-based (offline)** when no key is set or the
API failed. If the key is wrong or the free quota runs out, the chatbot
quietly falls back to rule-based replies.

To use a different model, set `GEMINI_MODEL` (default
`gemini-flash-lite-latest` — the fast lite model; `gemini-3.8-flash` also
works but was overloaded/slow during testing, and `gemini-2.0-flash` /
`gemini-2.5-flash` are retired for new users).

## Optional: BERT hybrid matching

BERT is OFF by default (the model is ~80MB, and the sentence-transformers
package needs a ~200MB CPU torch install). To enable locally:

```bash
pip install sentence-transformers
USE_BERT=1 uvicorn backend.main:app --reload
```

(Windows PowerShell: `$env:USE_BERT=1; uvicorn backend.main:app --reload`)

On this machine BERT measured Hit@5 0.9 / MRR 0.72 / NDCG@5 0.765, and those
numbers are cached in `backend/bert_evaluation.json`, so the Evaluation page
shows the third method even when BERT is not loaded. Not recommended on the
free Render plan — the model download and memory use can exceed the free tier.
