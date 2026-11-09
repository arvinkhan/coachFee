# CoachFee — Deployment & Operations Guide

## 1. Quick Overview

CoachFee is an enterprise-grade fee management and dues collection portal built for coaching institutes (Company A, Jaipur: 4 centres, 2,600 students, ₹31.2 Cr billed annually).

- **Technology Stack:** Django 5, HTMX, Tailwind CSS, SQLite (local) / PostgreSQL (production), Gunicorn + WhiteNoise.
- **Repository URL:** `https://github.com/arvinkhan/coachFee`
- **Live Deployment URL:** `https://coachfee-ukbr.onrender.com`

---

## 2. Local Setup (Step-by-Step)

### Prerequisites
- Python 3.10+ (Tested on Python 3.11)
- Git

### Commands

1. **Clone the repository:**
   ```bash
   git clone https://github.com/arvinkhan/coachFee.git
   cd coachFee
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

6. **Seed realistic sample data (includes 50 students across all 4 centres):**
   ```bash
   python manage.py seed_data
   ```

7. **Execute automated test suite (28 test cases):**
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
- *Single-Centre Scoped Executive:* Username `exec_gpl` | Password `staff123` (restricted to Gopalpura)
- *Access:* Consolidated dues dashboard, ageing buckets (0–30d, 31–60d, >60d), multi-centre breakdown across 50 students, student fee ledgers with individual payment links, pro-rata refund calculator, counsellor risk tasks, Tally CSV export, unmatched payments queue, and **Bulk Upload** of batch attendance and test scores via CSV.

### B. Student Portal Login
- **URL:** `http://127.0.0.1:8000/auth/student-login/`
- **Sample Student 1 (Aarav Meena):** Student ID `STU-0412` | Password: `student123`
- **Sample Student 2 (Ishita Sharma):** Student ID `STU-0587` | Password: `student123`
- **Sample Student 3 (Mohit Gurjar):** Student ID `STU-0219` | Password: `student123`
- **All 50 Students:** Any student ID `STU-xxxx` with password `student123`
- *Access:* Individual academic profile, class attendance logs, periodic assessment marks, and fee schedule overview with instant payment links.

### C. Parent Portal OTP Login (5-Second View)
- **URL:** `http://127.0.0.1:8000/auth/parent-login/`
- **Login Mechanism:** Passwordless email OTP. Every student has a unique parent with their own distinct email (`<first><last>@coachfee.com`) and credentials:
  - **Sample Parent 1 (Aarav Meena):** `humeshmeena@coachfee.com` (Father: Humesh Meena, Hindi default)
  - **Sample Parent 2 (Ishita Sharma):** `rameshsharma@coachfee.com` (Father: Dr. Ramesh Sharma, English default)
  - **Sample Parent 3 (Mohit Gurjar):** `surendragurjar@coachfee.com` (Father: Surendra Gurjar, NEET batch)
  - **Sample Parent 4 (Rohit Choudhary):** `vikramchoudhary@coachfee.com` (Father: Vikram Choudhary, High-risk NEET)
  - *All 50 Students:* Each of the 50 students has a completely distinct parent with a unique email formatted as `<father_name>@coachfee.com`.
- **OTP Delivery via Alert Dialog:** In Demo Mode, the 6-digit OTP code pops up automatically in an interactive browser `alert(...)` dialog (e.g. `[CoachFee Email OTP Verification] Your verification code for humeshmeena@coachfee.com is: 123456`). Simply enter the 6 digits and submit.
- **Language Switch:** Click the language button at the top right to instantly toggle between English and Hindi.
- **Payment Link per Instalment:** Each unpaid instalment features a test-mode payment link with copyable link pill and gateway simulation controls.

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
