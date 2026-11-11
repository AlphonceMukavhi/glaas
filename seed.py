"""
GLAAS Seed Data — realistic Grade 7 Science demo dataset
CO5 and CO7 deliberately produce weak Quizizz-Exam correlation
to demonstrate GLAAS diagnostic value.
"""
import random, math

OBJECTIVES = [
    (1,"CO1","Characteristics of Living Organisms","Living things share seven key characteristics: movement, respiration, sensitivity, growth, reproduction, excretion and nutrition."),
    (2,"CO2","Plant Nutrition and Photosynthesis","Green plants manufacture food through photosynthesis using sunlight, carbon dioxide and water."),
    (3,"CO3","Human Body Systems","The human body comprises several interconnected systems including the digestive, circulatory and respiratory systems."),
    (4,"CO4","Ecosystems and Food Chains","Ecosystems comprise producers, consumers and decomposers linked through food chains and food webs."),
    (5,"CO5","Properties of Matter","Matter exists in solid, liquid and gaseous states, each with distinct physical properties."),
    (6,"CO6","The Water Cycle","Water moves continuously through the environment via evaporation, condensation and precipitation."),
    (7,"CO7","Forces and Motion","Forces cause objects to start, stop, speed up, slow down or change direction."),
    (8,"CO8","Human Health and Disease","The body has natural and acquired defences against disease; hygiene and vaccination support health."),
]

LEARNERS = [(f"L{i:02d}", "M" if i%2==0 else "F") for i in range(1,21)]

def run_seed(db):
    random.seed(42)

    # Clear existing seed data
    db.execute("DELETE FROM scores")
    db.execute("DELETE FROM assessment_items")
    db.execute("DELETE FROM curriculum_objectives")
    db.execute("DELETE FROM learners")

    # Insert objectives
    for order, code, title, desc in OBJECTIVES:
        db.execute("INSERT INTO curriculum_objectives (code,title,description,display_order) VALUES (?,?,?,?)",
                   (code, title, desc, order))

    # Insert learners
    for code, gender in LEARNERS:
        db.execute("INSERT INTO learners (code,gender) VALUES (?,?)", (code, gender))
    db.commit()

    # Re-fetch IDs
    obj_rows = list(db.execute("SELECT id,code FROM curriculum_objectives ORDER BY display_order"))
    lrn_rows = list(db.execute("SELECT id,code FROM learners ORDER BY code"))

    # Create 3 items per objective per assessment type
    items = {}  # (atype, obj_id) -> [item_ids]
    for atype in ["prior_exercise","quizizz","formal_exam"]:
        for obj in obj_rows:
            oid = obj[0]
            ids = []
            for n in range(1,4):
                item_no = (list(obj_rows).index(obj))*3 + n
                cur = db.execute(
                    "INSERT INTO assessment_items (item_number,assessment_type,curriculum_objective_id,max_marks,description) VALUES (?,?,?,?,?)",
                    (item_no, atype, oid, 4,
                     f"{atype.replace('_',' ').title()} — {obj[1]} Q{n}"))
                ids.append(cur.lastrowid)
            items[(atype, oid)] = ids

    db.commit()

    # Generate learner ability baseline (0-100)
    ability = {lrn[0]: random.gauss(60, 14) for lrn in lrn_rows}

    # Score generation
    # Strong correlation objectives: CO1,CO2,CO3,CO4,CO6,CO8 (Quizizz-Exam r ≈ 0.70)
    # Weak correlation objectives:   CO5, CO7 (game score inflated, exam deflated)
    weak_objs = {obj[0] for obj in obj_rows if obj[1] in ("CO5","CO7")}

    def clamp(v): return max(0, min(100, v))

    for lrn in lrn_rows:
        lid = lrn[0]
        base = ability[lrn[0]]
        for obj in obj_rows:
            oid = obj[0]
            is_weak = oid in weak_objs

            # Prior exercise: close to baseline
            prior_true = clamp(base + random.gauss(0, 8))

            # Quizizz: improved over prior (gamification effect)
            if is_weak:
                # Large quizizz boost but doesn't transfer to exam
                quiz_true = clamp(prior_true + random.gauss(18, 10))
            else:
                quiz_true = clamp(prior_true + random.gauss(8, 8))

            # Formal exam: correlated with true ability
            if is_weak:
                # Exam score barely related to quizizz
                exam_true = clamp(base + random.gauss(0, 14))
            else:
                exam_true = clamp(quiz_true + random.gauss(-4, 7))

            for atype, true_score in [("prior_exercise", prior_true),
                                       ("quizizz", quiz_true),
                                       ("formal_exam", exam_true)]:
                for item_id in items[(atype, oid)]:
                    # Item-level score (vary within ±15% of objective score)
                    item_pct = clamp(true_score + random.gauss(0, 10))
                    marks = round((item_pct / 100) * 4, 1)
                    marks = max(0, min(4, marks))
                    db.execute("""INSERT OR IGNORE INTO scores
                        (learner_id, assessment_item_id, assessment_type,
                         curriculum_objective_id, marks_obtained, max_marks, entered_by)
                        VALUES (?,?,?,?,?,4,1)""",
                        (lid, item_id, atype, oid, marks))
    db.commit()
    print("Seed data inserted: 20 learners, 8 objectives, 72 items, 1440 score records")
