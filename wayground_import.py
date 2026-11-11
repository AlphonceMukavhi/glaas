"""
GLAAS — Wayground (Quizizz) XLSX Import Handler
Reads the .xlsx file exported directly by Wayground — no CSV conversion needed.
Parses the 'Participant Data' sheet and the 'Overview' sheet (for per-question
accuracy), auto-deduplicates by retaining the best complete attempt per learner,
and writes scores into GLAAS.
"""
import io
import openpyxl
# Column name variants Wayground has used across export versions.
# The parser matches headers case-insensitively and tolerates renames.
COL_ALIASES = {
    'first_name':  ['first name'],
    'last_name':   ['last name'],
    'player_name': ['player name', 'name'],
    'attempted':   ['total questions attempted', 'questions attempted'],
    'accuracy':    ['accuracy'],
    'correct':     ['correct'],
    'incorrect':   ['incorrect'],
    'unattempted': ['unattempted'],
}

# Placeholder names learners type when they don't enter their real name.
JUNK_FIRST_NAMES = {'', 'mmm', 'test', 'xxx', 'abc', 'player'}


def _sheet_to_dicts(ws):
    """Convert an openpyxl worksheet into a list of dict rows using row 1 as headers."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip().lower() if h is not None else '' for h in rows[0]]
    out = []
    for r in rows[1:]:
        if all(v is None for v in r):
            continue
        out.append({headers[i]: r[i] for i in range(len(headers)) if i < len(r)})
    return out


def _get(row: dict, key: str):
    """Fetch a value from a row dict using the known column aliases for `key`."""
    for alias in COL_ALIASES.get(key, [key]):
        if alias in row and row[alias] is not None:
            return row[alias]
    return None


def _to_int(val, default=0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).strip())
    except ValueError:
        return default


def _to_pct(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        # Wayground sometimes stores accuracy as 0.86 and sometimes as 86
        return float(val) * 100 if val <= 1 else float(val)
    s = str(val).replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return default
# Main entry point
def parse_wayground_xlsx(file_bytes: bytes, learners_map: dict, db, user_id: int,
                          n_questions: int = 31):
    """
    Parse a Wayground .xlsx export and insert scores into GLAAS.

    file_bytes:    raw bytes of the uploaded .xlsx file (e.g. request.files['f'].read())
    learners_map:  dict of {learner_code: full_name} already registered in GLAAS
    db:            an open sqlite3 connection (or equivalent .execute/.commit interface)
    user_id:       id of the researcher performing the import
    n_questions:   number of questions in the quiz (default 31, matches GLAAS quiz set)

    Returns: (imported_count, error_list, dedup_log)
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)

    # Wayground exports always include a 'Participant Data' sheet.
    sheet_name = next((n for n in wb.sheetnames if n.strip().lower() == 'participant data'),
                       None)
    if sheet_name is None:
        return 0, ["No 'Participant Data' sheet found in the uploaded file. "
                   "Please upload the original .xlsx export from Wayground."], []

    rows = _sheet_to_dicts(wb[sheet_name])

    # Step 1: Deduplicate — keep the most complete attempt per real learner
    candidates = {}
    for row in rows:
        fname  = str(_get(row, 'first_name') or '').strip()
        player = str(_get(row, 'player_name') or '').strip()

        if not fname or len(fname) < 2 or fname.lower() in JUNK_FIRST_NAMES:
            continue

        clean_name = player.rstrip('*. ').strip()
        attempted  = _to_int(_get(row, 'attempted'))
        correct    = _to_int(_get(row, 'correct'))
        accuracy   = _to_pct(_get(row, 'accuracy'))

        if clean_name not in candidates or attempted > candidates[clean_name]['attempted']:
            candidates[clean_name] = {
                'attempted': attempted, 'correct': correct,
                'accuracy': accuracy, 'player': player,
            }

    # Step 2: Match to learner records, then write scores
    imported, errors, dedup_log = 0, [], []

    for clean_name, data in candidates.items():
        matched_code = _match_learner(clean_name, learners_map)

        if not matched_code:
            errors.append(f"No learner match for '{clean_name}' "
                           f"(attempted: {data['attempted']})")
            continue

        if data['attempted'] < 10:
            errors.append(f"'{clean_name}' only attempted {data['attempted']} "
                           f"questions — skipped (too incomplete)")
            continue

        pct = round((data['correct'] / n_questions) * 100, 1)
        dedup_log.append(f"{clean_name} → {matched_code}: "
                          f"{data['correct']}/{n_questions} = {pct}%")

        try:
            for q_num in range(1, n_questions + 1):
                item = db.execute(
                    "SELECT id, curriculum_objective_id FROM assessment_items "
                    "WHERE item_number=? AND assessment_type='quizizz'",
                    (q_num,)
                ).fetchone()
                if not item:
                    continue

                q_correct = 1 if q_num <= data['correct'] else 0

                db.execute("""
                    INSERT INTO scores
                    (learner_id, assessment_item_id, assessment_type,
                     curriculum_objective_id, marks_obtained, max_marks, entered_by)
                    VALUES (
                        (SELECT id FROM learners WHERE code=?),
                        ?, 'quizizz', ?, ?, 1, ?
                    )
                    ON CONFLICT(learner_id, assessment_item_id)
                    DO UPDATE SET marks_obtained=excluded.marks_obtained,
                                  entered_by=excluded.entered_by,
                                  entered_at=CURRENT_TIMESTAMP
                """, (matched_code, item[0], item[1], q_correct, user_id))

            imported += 1
        except Exception as e:
            errors.append(f"DB error for '{clean_name}': {e}")

    db.commit()
    return imported, errors, dedup_log


def _match_learner(clean_name: str, learners_map: dict):
    """Find the GLAAS learner code whose name best matches the Wayground player name."""
    cl = clean_name.lower()
    for code, lrn_name in learners_map.items():
        ln = lrn_name.lower()
        if cl in ln or ln in cl or _name_match(cl, ln):
            return code
    return None


def _name_match(name_a: str, name_b: str) -> bool:
    """
    Loose name match for messy Wayground display names. Handles:
      - 'Grace M' vs 'Grace Moyo'              (surname initial)
      - 'Tino S' vs 'Tinotenda Sibanda'        (shortened first name + initial)
      - 'J0HN BANDA' vs 'John Banda'           (case / digits used as letters)
    """
    a_parts = name_a.split()
    b_parts = name_b.split()
    if not a_parts or not b_parts:
        return False

    a0, b0 = a_parts[0], b_parts[0]

    def norm(tok):
        # normalise common leetspeak substitutions seen in Wayground display names
        return tok.replace('0', 'o').replace('1', 'i').replace('3', 'e')

    a0n, b0n = norm(a0), norm(b0)

    first_name_match = (
        a0n == b0n
        or a0n.startswith(b0n) or b0n.startswith(a0n)
        or (len(a0n) >= 3 and len(b0n) >= 3 and b0n.startswith(a0n[:4]))
    )
    if not first_name_match:
        return False

    # First name alone is enough if there's nothing else to compare
    if len(a_parts) == 1 or len(b_parts) == 1:
        return first_name_match

    # Surname / surname-initial check
    a1, b1 = a_parts[-1], b_parts[-1]
    if a1 == b1:
        return True
    if len(a1) == 1 and b1.startswith(a1):
        return True
    if len(b1) == 1 and a1.startswith(b1):
        return True
    if a1.startswith(b1[:3]) or b1.startswith(a1[:3]):
        return True

    return first_name_match  # first name matched strongly enough on its own
# Optional: per-question accuracy extraction from the 'Overview' sheet
# Useful for the Question Analysis report — not required for score import.
def parse_overview_accuracy(file_bytes: bytes):
    """
    Returns a dict {question_number: accuracy_pct} read from the 'Overview' sheet,
    which Wayground always includes alongside 'Participant Data'.
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    sheet_name = next((n for n in wb.sheetnames if n.strip().lower() == 'overview'), None)
    if sheet_name is None:
        return {}

    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}

    headers = [str(h).strip().lower() if h is not None else '' for h in rows[0]]
    try:
        q_idx   = headers.index('#')
        acc_idx = headers.index('question accuracy')
    except ValueError:
        return {}

    result = {}
    for r in rows[1:]:
        if r[q_idx] is None:
            continue
        try:
            q_num = int(r[q_idx])
        except (ValueError, TypeError):
            continue
        result[q_num] = _to_pct(r[acc_idx])
    return result


def generate_xlsx_template(assessment_type: str, learner_codes: list, item_numbers: list):
    """
    Generate a GLAAS-compatible .xlsx template workbook (in-memory) for manual
    score import, returned as raw bytes ready to send as a file download.
    """
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Score Import'
    headers = ['learnerCode'] + [f'item{n}' for n in item_numbers]
    ws.append(headers)
    for code in learner_codes:
        ws.append([code] + [''] * len(item_numbers))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
