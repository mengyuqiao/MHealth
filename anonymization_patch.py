"""
Anonymization patch — adds PAT-001 style anonymous IDs to all patients.
Clinician views will show anon_id only; real names stay in DB for patient-facing screens.

Usage:
  conda activate hnc-tracker
  python anonymization_patch.py
"""

import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Step 1: Add anon_id column to DB ──────────────────────────────────────────
from app import app
from database import db, Patient
import sqlalchemy as sa

def migrate_db():
    with app.app_context():
        # Add column if it doesn't exist
        with db.engine.connect() as conn:
            cols = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(patients)"))]
            if 'anon_id' not in cols:
                conn.execute(sa.text("ALTER TABLE patients ADD COLUMN anon_id VARCHAR(10)"))
                conn.commit()
                print("✓ Added anon_id column to patients table")
            else:
                print("  anon_id column already exists, skipping")

        # Assign PAT-001, PAT-002, ... to existing patients that don't have one
        db.session.expire_all()
        patients = Patient.query.order_by(Patient.id).all()
        changed = 0
        for i, p in enumerate(patients, start=1):
            if not p.anon_id:
                p.anon_id = f"PAT-{i:03d}"
                changed += 1
        db.session.commit()
        print(f"✓ Assigned anon IDs to {changed} patients")

        print("\n  Current patient roster (clinician view):")
        print(f"  {'Anon ID':<12} {'Code':<10} {'Cal Goal'}")
        print(f"  {'-'*12} {'-'*10} {'-'*8}")
        for p in Patient.query.order_by(Patient.id).all():
            print(f"  {p.anon_id:<12} {p.code:<10} {p.calorie_goal}")

migrate_db()

# ── Step 2: Patch database.py — add anon_id field ─────────────────────────────
db_path = 'database.py'
with open(db_path) as f:
    db_src = f.read()

if 'anon_id' not in db_src:
    db_src = db_src.replace(
        "    is_active     = db.Column(db.Boolean, default=True)",
        "    anon_id       = db.Column(db.String(10), unique=True)  # e.g. PAT-001\n    is_active     = db.Column(db.Boolean, default=True)"
    )
    with open(db_path, 'w') as f:
        f.write(db_src)
    print("✓ database.py patched")
else:
    print("  database.py already has anon_id, skipping")

# ── Step 3: Patch app.py — auto-assign anon_id on seed + new patient ──────────
app_path = 'app.py'
with open(app_path) as f:
    app_src = f.read()

# Patch seed_db to assign anon_ids
old_seed = "    p1 = Patient(code='472910', name='John Smith',\n                 birthdate='03/14/1958', calorie_goal=2000)\n    p2 = Patient(code='835621', name='Maria Garcia',\n                 birthdate='07/22/1965', calorie_goal=1800)\n    db.session.add_all([p1, p2])\n    db.session.commit()"
new_seed = """    p1 = Patient(code='472910', name='John Smith',
                 birthdate='03/14/1958', calorie_goal=2000, anon_id='PAT-001')
    p2 = Patient(code='835621', name='Maria Garcia',
                 birthdate='07/22/1965', calorie_goal=1800, anon_id='PAT-002')
    db.session.add_all([p1, p2])
    db.session.commit()"""

if old_seed in app_src:
    app_src = app_src.replace(old_seed, new_seed)
    print("✓ app.py seed_db patched")
else:
    print("  app.py seed already patched or changed, skipping seed patch")

with open(app_path, 'w') as f:
    f.write(app_src)

# ── Step 4: Patch clinician/dashboard.html ────────────────────────────────────
dash_path = 'templates/clinician/dashboard.html'
with open(dash_path) as f:
    dash = f.read()

# Replace patient name display with anon_id
dash = dash.replace(
    '<span class="patient-name">{{ p.name }}</span>',
    '<span class="patient-name">{{ p.anon_id or p.code }}</span>'
)

with open(dash_path, 'w') as f:
    f.write(dash)
print("✓ clinician/dashboard.html patched")

# ── Step 5: Patch clinician/patient.html ──────────────────────────────────────
clin_path = 'templates/clinician/patient.html'
with open(clin_path) as f:
    clin = f.read()

# Replace name in title and subtitle
clin = clin.replace(
    '<h1 class="clinician-title">{{ patient.name }}</h1>',
    '<h1 class="clinician-title">{{ patient.anon_id or patient.code }}</h1>'
)
clin = clin.replace(
    '<div class="clinician-sub">DOB: {{ patient.birthdate }} · Goal: {{ patient.calorie_goal }} cal/day</div>',
    '<div class="clinician-sub">Goal: {{ patient.calorie_goal }} cal/day · Enrolled: {{ patient.created_at.strftime(\'%b %Y\') }}</div>'
)
# Replace name in med log table references
clin = clin.replace(
    "{% block title %}{{ patient.name }}{% endblock %}",
    "{% block title %}{{ patient.anon_id or patient.code }}{% endblock %}"
)

with open(clin_path, 'w') as f:
    f.write(clin)
print("✓ clinician/patient.html patched")

# ── Step 6: Patch add_demo_patients.py ────────────────────────────────────────
demo_path = 'add_demo_patients.py'
if os.path.exists(demo_path):
    with open(demo_path) as f:
        demo = f.read()

    old_list = """DEMO_PATIENTS = [
    # (code,    name,              birthdate,    calorie_goal)
    ('111111', 'Demo Patient 1',  '01/01/1960', 2000),
    ('123456', 'Demo Patient 2',  '01/01/1960', 2000),
    ('222222', 'Demo Patient 3',  '01/01/1960', 1800),
    ('333333', 'Demo Patient 4',  '01/01/1960', 1800),
    ('000000', 'Test User',       '01/01/1960', 2000),
]"""
    new_list = """DEMO_PATIENTS = [
    # (code,    name,              birthdate,    calorie_goal)
    ('111111', 'Demo Patient 1',  '01/01/1960', 2000),
    ('123456', 'Demo Patient 2',  '01/01/1960', 2000),
    ('222222', 'Demo Patient 3',  '01/01/1960', 1800),
    ('333333', 'Demo Patient 4',  '01/01/1960', 1800),
    ('000000', 'Test User',       '01/01/1960', 2000),
]

def next_anon_id():
    \"\"\"Generate the next PAT-XXX id based on existing patients.\"\"\"
    from database import Patient
    existing = [p.anon_id for p in Patient.query.all() if p.anon_id]
    nums = []
    for aid in existing:
        try: nums.append(int(aid.split('-')[1]))
        except: pass
    return f"PAT-{(max(nums) + 1):03d}" if nums else "PAT-001\""""

    demo = demo.replace(old_list, new_list)

    # Patch the add logic to include anon_id
    demo = demo.replace(
        "        p = Patient(code=code, name=name, birthdate=dob, calorie_goal=goal)",
        "        p = Patient(code=code, name=name, birthdate=dob, calorie_goal=goal, anon_id=next_anon_id())"
    )

    with open(demo_path, 'w') as f:
        f.write(demo)
    print("✓ add_demo_patients.py patched")

print("\n✅ All done! Restart the app: bash run.sh")
print("\nNote: Clinician dashboard now shows PAT-001 style IDs.")
print("Real patient names are only visible to patients on their own screens.")