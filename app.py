"""
GLAAS — Gamified Learning Assessment Alignment System
Flask application (Python, SQLite, Bootstrap 5) for Grade 7 Science.
Author: Alphonce Mukavhi
"""
import os, io, csv, json, sqlite3, math, statistics, secrets
import openpyxl
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, make_response, g)
from analytics import (pearson_r, spearman_rho, shapiro_wilk_approx,
                       descriptive_stats, class_alignment_report,
                       progression, trend_label, alignment_status,
                       alignment_recommendation, interpret_r)
from wayground_import import parse_wayground_xlsx, parse_overview_accuracy

# App setup
app = Flask(__name__)
# Set SECRET_KEY in production. Without it a random key is used and
# everyone is logged out when the server restarts.
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
DB_PATH = os.path.join(os.path.dirname(__file__), "database", "glaas.db")


# Database helpers
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    with open(os.path.join(os.path.dirname(__file__), "database", "schema.sql")) as f:
        db.executescript(f.read())
    db.commit()
    # First run: create the researcher account. Credentials come from the
    # environment; if no password is given, a random one is printed once.
    cur = db.execute("SELECT id FROM users WHERE role='researcher' LIMIT 1")
    if not cur.fetchone():
        email = os.environ.get("GLAAS_ADMIN_EMAIL", "researcher@example.com").strip().lower()
        password = os.environ.get("GLAAS_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        db.execute(
            "INSERT INTO users (email, password_hash, display_name, role) VALUES (?,?,?,?)",
            (email, generate_password_hash(password), "Researcher", "researcher")
        )
        db.commit()
        if "GLAAS_ADMIN_PASSWORD" not in os.environ:
            print(f"Created researcher account {email} with password: {password}")
            print("Change it under Settings after signing in.")
    db.close()


# Auth helpers
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def researcher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "researcher":
            flash("Researcher access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def current_user():
    if "user_id" not in session:
        return None
    return query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)

@app.context_processor
def inject_globals():
    settings = {r["key"]: r["value"] for r in query("SELECT key, value FROM system_settings")}
    return {"current_user": current_user(), "settings": settings,
            "now": datetime.now()}


# Utility
def get_scores_by_objective(learner_id=None):
    """Return dict: obj_id -> {type -> [pct,...]}. Optionally filter by learner."""
    if learner_id:
        rows = query("""
            SELECT s.curriculum_objective_id, s.assessment_type, s.percentage
            FROM scores s WHERE s.learner_id=?""", (learner_id,))
    else:
        rows = query("""
            SELECT s.curriculum_objective_id, s.assessment_type, s.percentage
            FROM scores s""")
    result = {}
    for r in rows:
        oid = r["curriculum_objective_id"]
        atype = r["assessment_type"]
        if oid not in result:
            result[oid] = {"prior_exercise": [], "quizizz": [], "formal_exam": []}
        result[oid][atype].append(r["percentage"])
    return result

def get_learner_scores_summary():
    """Per-learner: {prior_pct, quiz_pct, exam_pct, completeness}"""
    learners = query("SELECT * FROM learners WHERE active=1 ORDER BY code")
    result = []
    for lrn in learners:
        prior = query("""SELECT AVG(percentage) as avg FROM scores
                         WHERE learner_id=? AND assessment_type='prior_exercise'""",
                      (lrn["id"],), one=True)
        quiz  = query("""SELECT AVG(percentage) as avg FROM scores
                         WHERE learner_id=? AND assessment_type='quizizz'""",
                      (lrn["id"],), one=True)
        exam  = query("""SELECT AVG(percentage) as avg FROM scores
                         WHERE learner_id=? AND assessment_type='formal_exam'""",
                      (lrn["id"],), one=True)
        p = prior["avg"] if prior["avg"] is not None else None
        q = quiz["avg"]  if quiz["avg"]  is not None else None
        e = exam["avg"]  if exam["avg"]  is not None else None
        count = sum(1 for v in [p, q, e] if v is not None)
        result.append({
            "id": lrn["id"], "code": lrn["code"], "gender": lrn["gender"],
            "prior_pct": round(p, 1) if p is not None else None,
            "quiz_pct":  round(q, 1) if q is not None else None,
            "exam_pct":  round(e, 1) if e is not None else None,
            "completeness": count,
            "complete": count == 3,
            "trend": trend_label(p, q, e),
            "growth": round(e - p, 1) if p is not None and e is not None else None,
        })
    return result
# ROUTES
# Auth
@app.route("/", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        pw    = request.form.get("password","")
        user  = query("SELECT * FROM users WHERE email=?", (email,), one=True)
        if user and check_password_hash(user["password_hash"], pw):
            session["user_id"]      = user["id"]
            session["role"]         = user["role"]
            session["display_name"] = user["display_name"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    learner_summaries = get_learner_scores_summary()
    n_learners   = len(learner_summaries)
    n_objectives = query("SELECT COUNT(*) as c FROM curriculum_objectives", one=True)["c"]
    complete     = sum(1 for l in learner_summaries if l["complete"])
    completeness_pct = round((complete / n_learners * 100), 1) if n_learners else 0

    # Overall Quizizz-Exam Pearson r
    quiz_vals = [l["quiz_pct"] for l in learner_summaries if l["quiz_pct"] is not None and l["exam_pct"] is not None]
    exam_vals = [l["exam_pct"] for l in learner_summaries if l["quiz_pct"] is not None and l["exam_pct"] is not None]
    overall_r = pearson_r(quiz_vals, exam_vals)

    # Class means per assessment type
    prior_all = [l["prior_pct"] for l in learner_summaries if l["prior_pct"] is not None]
    quiz_all  = [l["quiz_pct"]  for l in learner_summaries if l["quiz_pct"]  is not None]
    exam_all  = [l["exam_pct"]  for l in learner_summaries if l["exam_pct"]  is not None]
    class_means = {
        "prior":  round(statistics.mean(prior_all), 1) if prior_all else None,
        "quizizz": round(statistics.mean(quiz_all),  1) if quiz_all  else None,
        "exam":   round(statistics.mean(exam_all),  1) if exam_all  else None,
    }

    # Objective-level summary for dashboard table
    objectives = query("SELECT * FROM curriculum_objectives ORDER BY display_order, code")
    sbo = get_scores_by_objective()
    obj_report = class_alignment_report(sbo, [dict(o) for o in objectives])

    return render_template("dashboard.html",
        n_learners=n_learners, n_objectives=n_objectives,
        completeness_pct=completeness_pct,
        overall_r=overall_r, class_means=class_means,
        obj_report=obj_report, learner_summaries=learner_summaries[:5])


# Learners
@app.route("/learners")
@login_required
def learners():
    summaries = get_learner_scores_summary()
    return render_template("learners.html", learners=summaries)

@app.route("/learners/add", methods=["POST"])
@login_required
@researcher_required
def add_learner():
    code      = request.form.get("code","").strip().upper()
    full_name = request.form.get("full_name","").strip()
    gender    = request.form.get("gender","Unspecified")
    if not code:
        flash("Learner code is required.", "danger")
        return redirect(url_for("learners"))
    existing = query("SELECT id FROM learners WHERE code=?", (code,), one=True)
    if existing:
        flash(f"Code {code} already exists.", "danger")
        return redirect(url_for("learners"))
    execute("INSERT INTO learners (code, full_name, gender) VALUES (?,?,?)",
            (code, full_name, gender))
    flash(f"Learner {code} added.", "success")
    return redirect(url_for("learners"))

@app.route("/learners/delete/<int:lid>", methods=["POST"])
@login_required
@researcher_required
def delete_learner(lid):
    execute("DELETE FROM learners WHERE id=?", (lid,))
    flash("Learner removed.", "success")
    return redirect(url_for("learners"))

@app.route("/learners/import", methods=["POST"])
@login_required
@researcher_required
def import_learners():
    f = request.files.get("csv_file")
    if not f:
        flash("No file selected.", "danger")
        return redirect(url_for("learners"))

    filename = (f.filename or "").lower()
    imported, errors = 0, []

    if filename.endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            flash("The uploaded spreadsheet is empty.", "danger")
            return redirect(url_for("learners"))
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        for i, r in enumerate(rows[1:], 1):
            row = dict(zip(headers, r))
            code = str(row.get("learnerCode") or row.get("code") or "").strip().upper()
            full_name = str(row.get("fullName") or row.get("full_name") or "").strip()
            gender = str(row.get("gender") or "Unspecified").strip()
            if not code:
                errors.append(f"Row {i}: missing code")
                continue
            try:
                execute("INSERT OR IGNORE INTO learners (code, full_name, gender) VALUES (?,?,?)",
                        (code, full_name, gender))
                imported += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")
    else:
        stream = io.StringIO(f.stream.read().decode("utf-8"))
        reader = csv.DictReader(stream)
        for i, row in enumerate(reader, 1):
            code = (row.get("learnerCode") or row.get("code","")).strip().upper()
            full_name = (row.get("fullName") or row.get("full_name") or "").strip()
            gender = (row.get("gender","Unspecified")).strip()
            if not code:
                errors.append(f"Row {i}: missing code")
                continue
            try:
                execute("INSERT OR IGNORE INTO learners (code, full_name, gender) VALUES (?,?,?)",
                        (code, full_name, gender))
                imported += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")

    execute("INSERT INTO csv_imports (filename, assessment_type, rows_imported, imported_by, errors, status) VALUES (?,?,?,?,?,?)",
            (f.filename, "learners", imported, session["user_id"],
             json.dumps(errors), "success" if not errors else "partial"))
    flash(f"Imported {imported} learners. {len(errors)} errors.", "success" if not errors else "warning")
    return redirect(url_for("learners"))


# Curriculum Objectives
@app.route("/objectives")
@login_required
def objectives():
    objs = query("SELECT co.*, COUNT(ai.id) as item_count FROM curriculum_objectives co LEFT JOIN assessment_items ai ON ai.curriculum_objective_id=co.id GROUP BY co.id ORDER BY co.display_order, co.code")
    return render_template("objectives.html", objectives=objs)

@app.route("/objectives/add", methods=["POST"])
@login_required
@researcher_required
def add_objective():
    code  = request.form.get("code","").strip().upper()
    title = request.form.get("title","").strip()
    desc  = request.form.get("description","").strip()
    order = request.form.get("order", 0)
    if not code or not title:
        flash("Code and title are required.", "danger")
        return redirect(url_for("objectives"))
    execute("INSERT INTO curriculum_objectives (code, title, description, display_order) VALUES (?,?,?,?)",
            (code, title, desc, order))
    flash(f"Objective {code} added.", "success")
    return redirect(url_for("objectives"))

@app.route("/objectives/delete/<int:oid>", methods=["POST"])
@login_required
@researcher_required
def delete_objective(oid):
    # Check no scores reference this
    items = query("SELECT id FROM assessment_items WHERE curriculum_objective_id=?", (oid,))
    if items:
        flash("Cannot delete: assessment items reference this objective.", "danger")
        return redirect(url_for("objectives"))
    execute("DELETE FROM curriculum_objectives WHERE id=?", (oid,))
    flash("Objective deleted.", "success")
    return redirect(url_for("objectives"))


# Data Entry
@app.route("/data-entry")
@login_required
@researcher_required
def data_entry():
    atype = request.args.get("type", "prior_exercise")
    learners_list = query("SELECT * FROM learners WHERE active=1 ORDER BY code")
    items    = query("SELECT ai.*, co.code as obj_code, co.title as obj_title FROM assessment_items ai JOIN curriculum_objectives co ON co.id=ai.curriculum_objective_id WHERE ai.assessment_type=? ORDER BY ai.item_number", (atype,))
    objs     = query("SELECT * FROM curriculum_objectives ORDER BY display_order, code")
    # Existing scores matrix
    existing = {}
    for s in query("SELECT * FROM scores WHERE assessment_type=?", (atype,)):
        existing[(s["learner_id"], s["assessment_item_id"])] = s["marks_obtained"]
    return render_template("data_entry.html",
        atype=atype, learners=learners_list,
        items=items, objectives=objs, existing=existing)

@app.route("/data-entry/save", methods=["POST"])
@login_required
@researcher_required
def save_scores():
    atype = request.form.get("atype")
    items = query("SELECT * FROM assessment_items WHERE assessment_type=?", (atype,))
    learners_list = query("SELECT * FROM learners WHERE active=1")
    saved = 0
    for lrn in learners_list:
        for item in items:
            key = f"score_{lrn['id']}_{item['id']}"
            val = request.form.get(key,"").strip()
            if val == "":
                continue
            try:
                marks = float(val)
                marks = max(0, min(marks, item["max_marks"]))
                execute("""INSERT INTO scores
                    (learner_id, assessment_item_id, assessment_type,
                     curriculum_objective_id, marks_obtained, max_marks, entered_by)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(learner_id, assessment_item_id)
                    DO UPDATE SET marks_obtained=excluded.marks_obtained,
                                  entered_by=excluded.entered_by,
                                  entered_at=CURRENT_TIMESTAMP""",
                    (lrn["id"], item["id"], atype,
                     item["curriculum_objective_id"], marks,
                     item["max_marks"], session["user_id"]))
                saved += 1
            except ValueError:
                pass
    flash(f"Saved {saved} scores.", "success")
    return redirect(url_for("data_entry", type=atype))

@app.route("/data-entry/add-item", methods=["POST"])
@login_required
@researcher_required
def add_item():
    atype   = request.form.get("atype")
    num     = request.form.get("item_number")
    obj_id  = request.form.get("curriculum_objective_id")
    max_m   = request.form.get("max_marks", 1)
    desc    = request.form.get("description","").strip()
    try:
        execute("INSERT INTO assessment_items (item_number, assessment_type, curriculum_objective_id, max_marks, description) VALUES (?,?,?,?,?)",
                (num, atype, obj_id, max_m, desc))
        flash("Assessment item added.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("data_entry", type=atype))

@app.route("/data-entry/delete-item/<int:iid>", methods=["POST"])
@login_required
@researcher_required
def delete_item(iid):
    atype = request.form.get("atype","prior_exercise")
    execute("DELETE FROM assessment_items WHERE id=?", (iid,))
    flash("Item deleted.", "success")
    return redirect(url_for("data_entry", type=atype))

@app.route("/data-entry/import-csv", methods=["POST"])
@login_required
@researcher_required
def import_scores_csv():
    """
    Generic score importer for manually-prepared spreadsheets
    (prior exercise scores, formal exam scores). Accepts .csv or .xlsx
    in the GLAAS import format: learnerCode, item1, item2, ...
    """
    atype = request.form.get("atype","prior_exercise")
    f     = request.files.get("csv_file")
    if not f:
        flash("No file selected.", "danger")
        return redirect(url_for("data_entry", type=atype))

    filename = (f.filename or "").lower()
    items   = {str(i["item_number"]): i for i in query(
        "SELECT * FROM assessment_items WHERE assessment_type=?", (atype,))}
    learners_map = {l["code"]: l for l in query("SELECT * FROM learners WHERE active=1")}
    imported, errors = 0, []

    if filename.endswith(".xlsx"):
        # Read GLAAS-format xlsx: header row + learnerCode/item columns
        wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            flash("The uploaded spreadsheet is empty.", "danger")
            return redirect(url_for("data_entry", type=atype))
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        for i, r in enumerate(rows[1:], 1):
            row = dict(zip(headers, r))
            code = str(row.get("learnerCode") or row.get("code") or "").strip().upper()
            lrn  = learners_map.get(code)
            if not lrn:
                errors.append(f"Row {i}: unknown learner code '{code}'")
                continue
            for item_no, item in items.items():
                val = row.get(f"item{item_no}") or row.get(item_no)
                if val is None or val == "":
                    continue
                try:
                    marks = max(0, min(float(val), item["max_marks"]))
                    execute("""INSERT INTO scores
                        (learner_id, assessment_item_id, assessment_type,
                         curriculum_objective_id, marks_obtained, max_marks, entered_by)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(learner_id, assessment_item_id)
                        DO UPDATE SET marks_obtained=excluded.marks_obtained""",
                        (lrn["id"], item["id"], atype,
                         item["curriculum_objective_id"], marks,
                         item["max_marks"], session["user_id"]))
                    imported += 1
                except ValueError:
                    errors.append(f"Row {i}, item {item_no}: invalid value '{val}'")
    else:
        # Plain CSV path (still supported)
        stream  = io.StringIO(f.stream.read().decode("utf-8"))
        reader  = csv.DictReader(stream)
        for i, row in enumerate(reader, 1):
            code = (row.get("learnerCode") or row.get("code","")).strip().upper()
            lrn  = learners_map.get(code)
            if not lrn:
                errors.append(f"Row {i}: unknown learner code '{code}'")
                continue
            for item_no, item in items.items():
                val = row.get(f"item{item_no}") or row.get(item_no)
                if val is None:
                    continue
                try:
                    marks = max(0, min(float(val), item["max_marks"]))
                    execute("""INSERT INTO scores
                        (learner_id, assessment_item_id, assessment_type,
                         curriculum_objective_id, marks_obtained, max_marks, entered_by)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(learner_id, assessment_item_id)
                        DO UPDATE SET marks_obtained=excluded.marks_obtained""",
                        (lrn["id"], item["id"], atype,
                         item["curriculum_objective_id"], marks,
                         item["max_marks"], session["user_id"]))
                    imported += 1
                except ValueError:
                    errors.append(f"Row {i}, item {item_no}: invalid value '{val}'")

    execute("INSERT INTO csv_imports (filename, assessment_type, rows_imported, imported_by, errors, status) VALUES (?,?,?,?,?,?)",
            (f.filename, atype, imported, session["user_id"],
             json.dumps(errors), "success" if not errors else "partial"))
    flash(f"Imported {imported} scores. {len(errors)} errors.", "success" if not errors else "warning")
    return redirect(url_for("data_entry", type=atype))


@app.route("/data-entry/import-wayground", methods=["POST"])
@login_required
@researcher_required
def import_wayground():
    """
    Dedicated importer for the raw .xlsx file exported directly by Wayground
    (the 'Participant Data' workbook) — no CSV conversion required.
    Automatically deduplicates multiple attempts per learner and matches
    messy display names (nicknames, leetspeak, surname initials) to the
    registered learner list.
    """
    f = request.files.get("wayground_file")
    if not f or not (f.filename or "").lower().endswith(".xlsx"):
        flash("Please upload the original .xlsx file exported by Wayground.", "danger")
        return redirect(url_for("data_entry", type="quizizz"))

    file_bytes = f.read()
    learners_full = {
        l["code"]: (l["full_name"] or l["code"])
        for l in query("SELECT * FROM learners WHERE active=1")
    }

    db = get_db()
    imported, errors, dedup_log = parse_wayground_xlsx(
        file_bytes, learners_full, db, session["user_id"]
    )

    execute("INSERT INTO csv_imports (filename, assessment_type, rows_imported, imported_by, errors, status) VALUES (?,?,?,?,?,?)",
            (f.filename, "quizizz", imported, session["user_id"],
             json.dumps({"errors": errors, "matched": dedup_log}),
             "success" if not errors else "partial"))

    flash(f"Wayground import complete: {imported} learners matched and scored. "
          f"{len(errors)} unmatched or incomplete entries skipped.",
          "success" if not errors else "warning")
    return redirect(url_for("data_entry", type="quizizz"))


# Class Reports
@app.route("/reports")
@login_required
def reports():
    learner_summaries = get_learner_scores_summary()
    objectives = query("SELECT * FROM curriculum_objectives ORDER BY display_order, code")
    sbo = get_scores_by_objective()
    obj_report = class_alignment_report(sbo, [dict(o) for o in objectives])

    # All percentage arrays
    prior_all = [l["prior_pct"] for l in learner_summaries if l["prior_pct"] is not None]
    quiz_all  = [l["quiz_pct"]  for l in learner_summaries if l["quiz_pct"]  is not None]
    exam_all  = [l["exam_pct"]  for l in learner_summaries if l["exam_pct"]  is not None]

    desc_stats = {
        "prior":   descriptive_stats(prior_all),
        "quizizz": descriptive_stats(quiz_all),
        "exam":    descriptive_stats(exam_all),
    }
    normality = {
        "prior":   shapiro_wilk_approx(prior_all),
        "quizizz": shapiro_wilk_approx(quiz_all),
        "exam":    shapiro_wilk_approx(exam_all),
    }
    # Decide Pearson vs Spearman based on normality
    use_pearson = all(
        normality[k] and normality[k]["normal"]
        for k in ["prior","quizizz","exam"]
        if normality[k]
    )
    corr_fn = pearson_r if use_pearson else spearman_rho
    corr_label = "Pearson r" if use_pearson else "Spearman ρ"

    corr_matrix = {
        "prior_quiz": corr_fn(prior_all, quiz_all[:len(prior_all)]),
        "prior_exam": corr_fn(prior_all, exam_all[:len(prior_all)]),
        "quiz_exam":  corr_fn(quiz_all,  exam_all[:len(quiz_all)]),
    }
    # Scatter data for chart
    scatter = [{"code": l["code"], "x": l["quiz_pct"], "y": l["exam_pct"]}
               for l in learner_summaries
               if l["quiz_pct"] is not None and l["exam_pct"] is not None]

    return render_template("reports.html",
        obj_report=obj_report, desc_stats=desc_stats,
        normality=normality, corr_matrix=corr_matrix,
        corr_label=corr_label, scatter=json.dumps(scatter),
        learner_summaries=learner_summaries,
        settings={r["key"]: r["value"] for r in query("SELECT key, value FROM system_settings")})


# Individual Reports
@app.route("/reports/individual")
@login_required
def individual_report():
    learner_id = request.args.get("learner_id", type=int)
    learners_list = query("SELECT * FROM learners WHERE active=1 ORDER BY code")
    selected = None
    learner_data = None

    if learner_id:
        selected = query("SELECT * FROM learners WHERE id=?", (learner_id,), one=True)
        objectives = query("SELECT * FROM curriculum_objectives ORDER BY display_order, code")
        sbo_all = get_scores_by_objective()
        sbo_lrn = get_scores_by_objective(learner_id=learner_id)

        # Per-objective learner vs class
        obj_breakdown = []
        for obj in objectives:
            oid = obj["id"]
            ldata = sbo_lrn.get(oid, {})
            cdata = sbo_all.get(oid, {})
            import statistics as st
            lp = round(st.mean(ldata.get("prior_exercise",[])), 1) if ldata.get("prior_exercise") else None
            lq = round(st.mean(ldata.get("quizizz",[])),        1) if ldata.get("quizizz")        else None
            le = round(st.mean(ldata.get("formal_exam",[])),    1) if ldata.get("formal_exam")    else None
            cp = round(st.mean(cdata.get("prior_exercise",[])), 1) if cdata.get("prior_exercise") else None
            cq = round(st.mean(cdata.get("quizizz",[])),        1) if cdata.get("quizizz")        else None
            ce = round(st.mean(cdata.get("formal_exam",[])),    1) if cdata.get("formal_exam")    else None
            obj_breakdown.append({
                "code": obj["code"], "title": obj["title"],
                "learner_prior": lp, "learner_quiz": lq, "learner_exam": le,
                "class_prior": cp,   "class_quiz": cq,   "class_exam": ce,
                "trend": trend_label(lp, lq, le),
                "growth": round(le - lp, 1) if lp is not None and le is not None else None,
            })

        # Overall averages for this learner
        def lmean(atype):
            r = query("SELECT AVG(percentage) as a FROM scores WHERE learner_id=? AND assessment_type=?",
                      (learner_id, atype), one=True)
            return round(r["a"], 1) if r["a"] is not None else None

        learner_data = {
            "prior": lmean("prior_exercise"),
            "quiz":  lmean("quizizz"),
            "exam":  lmean("formal_exam"),
            "obj_breakdown": obj_breakdown,
        }

        # Class rank
        all_summaries = get_learner_scores_summary()
        for atype_key in ["prior_pct","quiz_pct","exam_pct"]:
            sorted_vals = sorted([l[atype_key] for l in all_summaries if l[atype_key] is not None], reverse=True)
            my_val = next((l[atype_key] for l in all_summaries if l["id"]==learner_id), None)
            learner_data[f"rank_{atype_key}"] = (sorted_vals.index(my_val)+1 if my_val in sorted_vals else None)
        learner_data["n_learners"] = len(all_summaries)

    return render_template("individual_report.html",
        learners=learners_list, selected=selected,
        learner_data=learner_data, learner_id=learner_id)


# TAM Questionnaire
@app.route("/questionnaire", methods=["GET","POST"])
@login_required
def questionnaire():
    if request.method == "POST":
        role = request.form.get("respondent_role","teacher")
        vals = {f"q{i}": request.form.get(f"q{i}", type=int) for i in range(1,11)}
        opens = {f"q{i}_open": request.form.get(f"q{i}") for i in [11,12,13,14]}
        execute("""INSERT INTO questionnaire_responses
            (respondent_role, q1_useful, q2_curriculum, q3_mastery,
             q4_clearer, q5_recommend, q6_easy_nav, q7_easy_read,
             q8_independent, q9_quiz_aligned, q10_quiz_effective,
             q11_open, q12_open, q13_open, q14_open)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (role, vals["q1"], vals["q2"], vals["q3"], vals["q4"], vals["q5"],
             vals["q6"], vals["q7"], vals["q8"], vals["q9"], vals["q10"],
             opens["q11_open"], opens["q12_open"],
             opens["q13_open"], opens["q14_open"]))
        flash("Thank you. Your response has been recorded.", "success")
        return redirect(url_for("questionnaire_results"))
    return render_template("questionnaire.html")

@app.route("/questionnaire/results")
@login_required
def questionnaire_results():
    responses = query("SELECT * FROM questionnaire_responses ORDER BY submitted_at DESC")
    if not responses:
        return render_template("questionnaire_results.html", responses=[], summary=None)
    # Compute means per TAM dimension
    fields = ["q1_useful","q2_curriculum","q3_mastery","q4_clearer","q5_recommend",
              "q6_easy_nav","q7_easy_read","q8_independent","q9_quiz_aligned","q10_quiz_effective"]
    summary = {}
    for f in fields:
        vals = [r[f] for r in responses if r[f] is not None]
        summary[f] = round(statistics.mean(vals), 2) if vals else None
    return render_template("questionnaire_results.html",
        responses=responses, summary=summary)


# Settings
@app.route("/settings", methods=["GET","POST"])
@login_required
@researcher_required
def settings():
    if request.method == "POST":
        for key in ["school_name","researcher_name","academic_year","study_title","grade","subject"]:
            val = request.form.get(key,"").strip()
            if val:
                execute("INSERT INTO system_settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, val))
        # Password change
        new_pw = request.form.get("new_password","").strip()
        if new_pw:
            execute("UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(new_pw), session["user_id"]))
            flash("Password updated.", "success")
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    settings_data = {r["key"]: r["value"] for r in query("SELECT key, value FROM system_settings")}
    imports = query("SELECT * FROM csv_imports ORDER BY imported_at DESC LIMIT 10")
    return render_template("settings.html", settings=settings_data, imports=imports)

@app.route("/settings/clear-scores", methods=["POST"])
@login_required
@researcher_required
def clear_scores():
    confirm = request.form.get("confirm","")
    if confirm == "DELETE":
        execute("DELETE FROM scores")
        flash("All scores cleared.", "warning")
    else:
        flash("Type DELETE to confirm.", "danger")
    return redirect(url_for("settings"))

@app.route("/settings/seed", methods=["POST"])
@login_required
@researcher_required
def seed_data():
    from seed import run_seed
    run_seed(get_db())
    get_db().commit()
    flash("Demo data loaded successfully.", "success")
    return redirect(url_for("dashboard"))


# Export
@app.route("/export/csv")
@login_required
def export_csv():
    summaries = get_learner_scores_summary()
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["LearnerCode","Gender","PriorExercise_%","Quizizz_%","FormalExam_%","Growth_%","Trend"])
    for l in summaries:
        w.writerow([l["code"], l["gender"],
                    l["prior_pct"] or "", l["quiz_pct"] or "",
                    l["exam_pct"]  or "", l["growth"]   or "", l["trend"]])
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=GLAAS_scores.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

@app.route("/export/report-csv")
@login_required
def export_report_csv():
    objectives = query("SELECT * FROM curriculum_objectives ORDER BY display_order, code")
    sbo = get_scores_by_objective()
    obj_report = class_alignment_report(sbo, [dict(o) for o in objectives])
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["ObjCode","ObjTitle","PriorMean%","QuizMean%","ExamMean%","QuizExam_r","AlignmentStatus","Recommendation"])
    for row in obj_report:
        w.writerow([row["code"], row["title"],
                    row["prior_mean"] or "", row["quiz_mean"] or "", row["exam_mean"] or "",
                    row["r"] or "", row["status"], row["recommendation"]])
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=GLAAS_alignment_report.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp


# API endpoints for charts
@app.route("/api/chart/class-means")
@login_required
def api_class_means():
    objectives = query("SELECT * FROM curriculum_objectives ORDER BY display_order, code")
    sbo = get_scores_by_objective()
    import statistics as st
    data = []
    for obj in objectives:
        oid = obj["id"]
        d   = sbo.get(oid, {})
        data.append({
            "code":  obj["code"],
            "title": obj["title"],
            "prior": round(st.mean(d.get("prior_exercise",[])),1) if d.get("prior_exercise") else 0,
            "quiz":  round(st.mean(d.get("quizizz",[])),1) if d.get("quizizz") else 0,
            "exam":  round(st.mean(d.get("formal_exam",[])),1) if d.get("formal_exam") else 0,
        })
    return jsonify(data)


# Run
if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
