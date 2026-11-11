# GLAAS: Gamified Learning Assessment Alignment System

GLAAS is a web application I built for my honours research project. It checks whether learners' scores in gamified quizzes line up with their formal Grade 7 Science examination results, objective by objective, so teachers can see where game-based practice is working and where it is not.

## What it does

- **Learners and objectives:** register learners under anonymous codes and set up curriculum objectives and assessment items.
- **Data entry:** enter scores by hand, import CSV/Excel files, or upload a Wayground (Quizizz) export directly. The importer removes duplicate attempts and matches messy player names to real learners.
- **Analytics:** descriptive statistics, Pearson and Spearman correlation between quiz and exam scores, a normality check, and alignment status per objective with recommendations.
- **Reports:** a class dashboard with charts, individual learner reports, a questionnaire module and CSV export.
- **Access control:** login with hashed passwords. Every page that changes data needs the researcher role.

## Tech

Python, Flask, SQLite, openpyxl, Jinja templates and Bootstrap 5. The statistics in `analytics.py` are written by hand with the standard library.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export GLAAS_ADMIN_EMAIL=you@example.com
export GLAAS_ADMIN_PASSWORD=choose-a-strong-password
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
python run.py                      # http://localhost:5000
```

To explore with sample data, sign in and use **Settings → Load demo data**. It creates 20 anonymous learners (L01–L20) with generated scores.

## Project structure

```
app.py               routes, authentication, data entry, reports
analytics.py         statistics and alignment logic
wayground_import.py  Wayground .xlsx import and name matching
seed.py              demo data
database/schema.sql  SQLite schema
templates/, static/  user interface
```

## Privacy

No learner data is included in this repository. Real data stays in `database/glaas.db`, which is git-ignored. Learners are identified by codes, and full names are used only to match imported quiz results.
