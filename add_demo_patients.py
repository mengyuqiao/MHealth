"""
Add demo patients with easy-to-remember codes for collaborators.
Usage: python add_demo_patients.py

Run from ~/hnc-tracker with the conda env active:
  conda activate hnc-tracker
  python add_demo_patients.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, seed_db
from database import db, Patient
from werkzeug.security import generate_password_hash

DEMO_PATIENTS = [
    # (code,    name,              birthdate,    calorie_goal)
    ('111111', 'Demo Patient 1',  '01/01/1960', 2000),
    ('123456', 'Demo Patient 2',  '01/01/1960', 2000),
    ('222222', 'Demo Patient 3',  '01/01/1960', 1800),
    ('333333', 'Demo Patient 4',  '01/01/1960', 1800),
    ('000000', 'Test User',       '01/01/1960', 2000),
]

with app.app_context():
    db.create_all()
    added = []
    skipped = []

    for code, name, dob, goal in DEMO_PATIENTS:
        existing = Patient.query.filter_by(code=code).first()
        if existing:
            skipped.append(code)
            continue
        p = Patient(code=code, name=name, birthdate=dob, calorie_goal=goal)
        db.session.add(p)
        added.append(code)

    db.session.commit()

    print("\n============================================")
    print("  Demo Patients")
    print("============================================")
    print(f"  Added  : {', '.join(added) if added else 'none (all already exist)'}")
    print(f"  Skipped: {', '.join(skipped) if skipped else 'none'}")
    print()
    print("  All active patients:")
    print(f"  {'Code':<10} {'Name':<20} {'Cal Goal'}")
    print(f"  {'-'*10} {'-'*20} {'-'*8}")
    for p in Patient.query.filter_by(is_active=True).order_by(Patient.code).all():
        print(f"  {p.code:<10} {p.name:<20} {p.calorie_goal}")
    print("============================================\n")