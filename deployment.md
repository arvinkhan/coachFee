# CoachFee — Deployment & Operations Guide

## 1. Quick Overview

CoachFee is an enterprise-grade fee management and dues collection portal built for coaching institutes (Company A, Jaipur: 4 centres, 2,600 students, ₹31.2 Cr billed annually).

- **Technology Stack:** Django 5, HTMX, Tailwind CSS, SQLite (local) / PostgreSQL (production), Gunicorn + WhiteNoise.
- **Repository URL:** `[GITHUB_REPOSITORY_URL_PLACEHOLDER]` *(To be linked upon repo publishing)*
- **Live Deployment URL:** `[RENDER_DEPLOYMENT_URL_PLACEHOLDER]` *(Auto-deployed via Render blueprint)*

---

## 2. Local Setup (Step-by-Step)

### Prerequisites
- Python 3.10+ (Tested on Python 3.11)
- Git

### Commands

1. **Clone the repository:**
   ```bash
   git clone [GITHUB_REPOSITORY_URL_PLACEHOLDER]
   cd assn
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # On macOS/Linux:
   python3 -m venv .venv
   source .venv/bin/activate

   # On Windows (PowerShell):
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables (optional for local SQLite):**
   ```bash
   cp .env.example .env
   ```

5. **Apply database migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Seed realistic sample data (includes 4 centres & required sample students):**
   ```bash
   python manage.py seed_data
   ```

7. **Execute automated test suite:**
   ```bash
   python manage.py test
   ```

8. **Start development server:**
   ```bash
   python manage.py runserver
   ```
   Open `http://127.0.0.1:8000/` in your browser.

---

## 3. Reviewer Demo Credentials

### A. Staff / Accounts Executive Login
- **URL:** `http://127.0.0.1:8000/auth/staff-login/`
- **Username:** `staff`
- **Password:** `staff123`
- *Access:* Consolidated dues dashboard, ageing buckets (0–30d, 31–60d, >60d), multi-centre breakdown, student fee ledgers, pro-rata refund calculator, counsellor risk tasks, Tally CSV export, unmatched payments queue.

### B. Parent Portal OTP Login (5-Second View)
- **URL:** `http://127.0.0.1:8000/auth/parent-login/`
- **Sample Parent 1 (Aarav Meena):** `9829012345` (Hindi default)
- **Sample Parent 2 (Ishita Sharma):** `9829023456` (English default)
- **Sample Parent 3 (Mohit Gurjar):** `9829034567` (NEET batch)
- **OTP Verification:** In Demo Mode, the 6-digit OTP code is generated and displayed on-screen in a banner upon requesting. Simply type the code and submit.
- **Language Switch:** Click the language button at the top right to instantly toggle between English and Hindi.

---

## 4. Production Deployment on Render

The repository includes a ready `render.yaml` infrastructure-as-code blueprint.

### Automatic Render Blueprint Setup
1. Fork or push the repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com), click **New** → **Blueprint**.
3. Select your repository. Render automatically reads `render.yaml` and provisions:
   - A managed PostgreSQL database (`coachfee-db`).
   - A Python Web Service running Gunicorn and WhiteNoise.
4. Render automatically runs `migrate`, `collectstatic`, and `seed_data`.

### Environment Variables Required in Production

| Variable Name | Description | Example / Note |
|---|---|---|
| `DJANGO_SECRET_KEY` | High-entropy production cryptographic secret key | Generated automatically on Render |
| `DJANGO_DEBUG` | Disables debug mode for security | `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of allowed host domains | `.onrender.com,localhost` |
| `DATABASE_URL` | PostgreSQL connection string | Injected automatically from Render DB |
| `GATEWAY_HMAC_SECRET` | Secret key used to sign & verify payment gateway webhooks | Auto-generated or configured |

---

## 5. Scheduled Automation Tasks (Cron)

### Daily Reminder Dispatch Engine
To dispatch reminders at -3, 0, +1, +7, and +15 day intervals with real-time **stop-on-pay** balance verification:
```bash
python manage.py send_reminders
```
*(On Render, configure a Background Cron Job scheduled at 09:00 IST daily: `python manage.py send_reminders`)*
