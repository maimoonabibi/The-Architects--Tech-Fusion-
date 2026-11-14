"""Lab Report Explainer - main file (Python / Flask).

Run:    pip install -r requirements.txt && python main.py     -> http://127.0.0.1:5000
Check:  python main.py --check     (compares the rules engine with docs/answer_key.csv)

Layout:  main.py   frontend/ (index.html, styles.css, app.js)   docs/ (answer_key.csv, test_questions.md)
"""
import csv
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent

# ---------------------------------------------------------------- reference data
UNKNOWN = "cannot be classified from the files"
ASK = "ASK, cannot pick range"
FLAG = "FLAG: unsure"
AGE_MIN, AGE_MAX = 18, 100

ALIASES = {  # glossary
    "sgpt": "ALT", "sgot": "AST", "fbs": "Fasting Blood Sugar", "hb": "Hemoglobin",
    "plt": "Platelet Count", "rbc": "Red Blood Cell Count", "wbc": "White Blood Cell Count",
}
AMBIGUOUS = {"ph level": "Urine pH", "protein": "Urine Protein"}  # not stated as urine -> FLAG

# name: (standard unit, {"male": (lo, hi), "female": (lo, hi)} or {"all": (lo, hi) | "Negative"})
RANGES = {
    "Hemoglobin": ("g/dL", {"male": (13.8, 17.2), "female": (12.1, 15.1)}),
    "White Blood Cell Count": ("cells/mcL", {"all": (4500, 11000)}),
    "Platelet Count": ("cells/mcL", {"all": (150000, 450000)}),
    "Fasting Blood Sugar": ("mg/dL", {"all": (70, 99)}),
    "ALT": ("U/L", {"male": (7, 55), "female": (7, 45)}),
    "AST": ("U/L", {"male": (8, 48), "female": (8, 43)}),
    "Cholesterol": ("mg/dL", {"all": (125, 200)}),
    "TSH": ("mIU/L", {"all": (0.4, 4.0)}),
    "Urine pH": ("", {"all": (4.5, 8.0)}),
    "Urine Protein": ("", {"all": "Negative"}),
}
URGENT = {  # test: (operator, threshold)
    "Hemoglobin": ("<", 7.0), "Fasting Blood Sugar": (">", 300),
    "Platelet Count": ("<", 50000), "ALT": (">", 1000),
}
CONVERT = {("Fasting Blood Sugar", "mmol/L"): 18.016}  # standard factor, not from the files
EXPLAIN = {
    "Hemoglobin": "is the protein in red blood cells that carries oxygen around your body",
    "White Blood Cell Count": "counts the cells that help your body fight germs",
    "Platelet Count": "counts the small cells that help your blood clot",
    "Fasting Blood Sugar": "is the sugar level in your blood after not eating",
    "ALT": "is an enzyme found mostly in the liver",
    "AST": "is an enzyme found in the liver and other organs",
    "Cholesterol": "is a fatty substance in your blood",
    "TSH": "is a hormone signal that tells the thyroid gland how much to work",
    "Urine pH": "shows how acidic or alkaline your urine is",
    "Urine Protein": "checks whether protein is leaking into your urine",
}

# ---------------------------------------------------------------- patient reports
def P(pid, name, age, sex, tests):
    return {"id": pid, "name": name, "age": age, "sex": sex, "tests": tests}

PATIENTS = [
    P("P001", "Alice Smith", 28, "Female", [("Hemoglobin", 13.5, "g/dL"), ("WBC", 6000, "cells/mcL")]),
    P("P002", "Bob Jones", 35, "Female", [("SGPT", 45, "U/L")]),
    P("P003", "Charlie Brown", None, None, [("Fasting Blood Sugar", 110, "mg/dL")]),
    P("P004", "Diana Prince", 42, "Female", [("Hemoglobin", 6.5, "g/dL"), ("Platelet Count", 120000, "cells/mcL")]),
    P("P005", "Ethan Hunt", 50, "Male", [("Fasting Blood Sugar", 6.0, "mmol/L")]),
    P("P006", "Fiona Gallagher", 22, "Female", [("Serum Ferritin", 25, "ng/mL")]),
    P("P007", "George Costanza", 65, "Male", [("TSH", 2.5, "mIU/L")]),
    P("P008", "Haley Dunphy", 19, "Female", [("pH Level", 5.5, ""), ("Protein", "Negative", "")]),
    P("P009", "Ian Malcolm", 48, "Male", [("ALT", 85, "U/L"), ("AST", 60, "U/L")]),
    P("P010", "Julia Child", 55, "Female", [("Cholesterol", 200, "mg/dL")]),
    P("P011", "Kevin Hart", 40, "Male", [("WBC", 12000, "cells/mcL"), ("PLT", 140000, "cells/mcL")]),
    P("P012", "Laura Croft", 32, None, [("AST", 44, "U/L")]),
]

# ---------------------------------------------------------------- rules engine
def resolve(name):
    k = name.strip().lower()
    if k in AMBIGUOUS:
        return name.strip(), True
    std = ALIASES.get(k, name.strip())
    return next((s for s in RANGES if s.lower() == std.lower()), std), False


def classify(p, reported, value, unit, sex=None):
    """One test result -> dict(test, reported, value, unit, converted, status, urgent, note)."""
    sex = (sex or p["sex"] or "").lower()
    std, ambiguous = resolve(reported)
    row = {"test": std, "reported": reported, "value": value, "unit": unit,
           "converted": "", "status": "", "urgent": False, "note": ""}
    if reported.strip().lower() != std.lower() and not ambiguous:
        row["note"] = f"Reported as '{reported}'. "
    if ambiguous:
        row.update(status=FLAG, note=f"'{reported}' does not say which test it is "
                   f"(probably {AMBIGUOUS[reported.strip().lower()]}). Please confirm.")
        return row
    if std not in RANGES:
        row.update(status=UNKNOWN, note="No range for this test in the provided files.")
        return row

    std_unit, ranges = RANGES[std]
    v = value
    if unit != std_unit:
        factor = CONVERT.get((std, unit))
        if factor is None:
            row.update(status=UNKNOWN, note=f"Unit '{unit}' cannot be converted to {std_unit}.")
            return row
        v = round(value * factor, 1)
        row["converted"] = f"about {round(v)} {std_unit}"
        row["note"] += f"{value} x {factor} = {v} {std_unit}."

    if std in URGENT:  # urgent list is checked first
        op, lim = URGENT[std]
        if (op == "<" and v < lim) or (op == ">" and v > lim):
            row.update(status="Urgent", urgent=True)
            row["note"] += f" Beyond the urgent limit ({op} {lim} {std_unit}). See a doctor today."
            return row

    age = p["age"]
    if not isinstance(age, int) or sex not in ("male", "female"):
        row.update(status=ASK)
        row["note"] += " Age or sex is missing. Please provide it."
        return row
    if not AGE_MIN <= age <= AGE_MAX:
        row.update(status=UNKNOWN, note=f"Age {age} is outside the range sheets (18-100).")
        return row

    ref = ranges.get("all") or ranges[sex]
    if isinstance(ref, str):  # text result such as Negative
        row["status"] = "Normal" if str(v).lower() == ref.lower() else "High"
    else:
        lo, hi = ref
        row["status"] = "Low" if v < lo else "High" if v > hi else "Normal"  # on the limit = Normal
    row["note"] = row["note"].strip()
    return row


def evaluate(p, sex=None):
    return [classify(p, *t, sex=sex) for t in p["tests"]]


def doctor_questions(results):
    qs = []
    for r in results:
        s = r["status"]
        if s == "Urgent":
            qs.insert(0, f"My {r['test']} is at a dangerous level. What is causing this, and do I need treatment today?")
        elif s in ("Low", "High"):
            qs.append(f"My {r['test']} is {s.lower()}. What could be causing this, and do I need more tests?")
        elif s == ASK:
            qs.append("Can you confirm my age and sex so the correct range can be used?")
        elif s in (UNKNOWN, FLAG):
            qs.append(f"What is a healthy range for my {r['reported']}, and what does my result mean?")
    return list(dict.fromkeys(qs))

# ---------------------------------------------------------------- question answering (rule based)
DOCTOR = "Only a licensed doctor can diagnose."
MEANING = {"Normal": "within the reference range", "Low": "low compared with the reference range",
           "High": "high compared with the reference range",
           "Urgent": "at a dangerous level - please see a doctor today",
           ASK: "not checked yet because age or sex is missing", UNKNOWN: "cannot be classified from the files",
           FLAG: "unclear because the test name is not specific - please confirm"}


def describe(r):
    return f"{r['test']}: {r['value']} {r['unit']}".strip() + f" - {MEANING[r['status']]}."


def answer(p, question):
    t = question.lower()
    for o in PATIENTS:  # never discuss another patient
        if o["id"] != p["id"] and re.search(r"\b" + re.escape(o["name"].split()[0].lower()) + r"\b", t):
            return "I can only talk about the report that is open. I can't share another patient's results."
    if re.search(r"ignore (your|the|all)|do i have|what disease|diagnos|cancer|anemi|diabet", t):
        return f"I can't diagnose any condition. {DOCTOR} I can explain what your numbers mean in simple words."

    sex = None  # sex given by the user in chat (age is never guessed)
    if not p["sex"]:
        sex = "female" if re.search(r"\b(female|woman|girl)\b", t) else "male" if re.search(r"\b(male|man|boy)\b", t) else None
    results = evaluate(p, sex)
    if any(r["status"] == ASK for r in results):
        return "Your age or sex is missing, so I can't choose the right range. Please tell me the missing detail."

    urgent = [r for r in results if r["urgent"]]
    if urgent and re.search(r"urgent|serious|danger|wait|worr|week", t):
        return ("Please don't wait. " + ", ".join(r["test"] for r in urgent) + " is at a dangerous level. "
                "See a doctor today. " + DOCTOR)
    named = [r for r in results if r["test"].lower() in t or r["reported"].lower() in t]
    for r in named or []:
        if r["status"] == UNKNOWN:
            return f"Your {r['reported']} {UNKNOWN}. Please ask your doctor what it means."
    shown = named or results
    lines = [describe(r) for r in shown]
    if len(shown) == 1 and shown[0]["test"] in EXPLAIN:
        lines.insert(0, f"{shown[0]['test']} {EXPLAIN[shown[0]['test']]}.")
    if sex:
        lines.append(f"(I used the {sex} range because you told me your sex.)")
    return "\n".join(lines) + f"\n\nThis only compares your numbers with the reference range. {DOCTOR}"

# ---------------------------------------------------------------- web app
def create_app():
    from flask import Flask, jsonify, request, send_from_directory

    app = Flask(__name__, static_folder=str(BASE / "frontend"), static_url_path="")
    find = lambda pid: next((p for p in PATIENTS if p["id"] == pid), None)

    @app.get("/")
    def index():
        page = Path(app.static_folder) / "index.html"
        if not page.exists():
            return f"index.html not found. Expected it at: {page}", 404
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/patients")
    def patients():
        return jsonify([{"id": p["id"], "name": p["name"]} for p in PATIENTS])

    @app.get("/api/patients/<pid>")
    def patient(pid):
        p = find(pid)
        if not p:
            return jsonify(error="Patient not found."), 404
        res = evaluate(p)
        return jsonify(id=p["id"], name=p["name"], age=p["age"], sex=p["sex"], results=res,
                       doctor_questions=doctor_questions(res))

    @app.post("/api/ask")
    def ask():
        data = request.get_json(silent=True) or {}
        p, q = find(data.get("patient_id")), str(data.get("question", "")).strip()
        if not p:
            return jsonify(error="Patient not found."), 404
        if not q or len(q) > 300:
            return jsonify(error="Question must be 1-300 characters."), 400
        return jsonify(answer=answer(p, q))

    @app.errorhandler(Exception)
    def fail(e):
        code = getattr(e, "code", 500)
        return jsonify(error="Something went wrong." if code == 500 else str(e)), code

    return app

# ---------------------------------------------------------------- answer-key check
def check():
    key = list(csv.DictReader(open(BASE / "docs" / "answer_key.csv", encoding="utf-8")))
    got = {(p["name"], r["test"]): r for p in PATIENTS for r in evaluate(p)}
    bad = 0
    for k in key:
        r = got.get((k["patient"], k["test"]))
        want_urgent = k["urgent warning (yes/no)"] == "yes"
        if not r or r["status"] != k["correct status"] or r["urgent"] != want_urgent:
            bad += 1
            print(f"FAIL {k['patient']} / {k['test']}: expected {k['correct status']!r}, got {r and r['status']!r}")
    print(f"{len(key) - bad}/{len(key)} rows match the answer key.")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    create_app().run(debug=True)
