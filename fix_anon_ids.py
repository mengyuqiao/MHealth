"""
Fix anon_id assignment using raw SQL only — bypasses SQLAlchemy model entirely.
Usage: python fix_anon_ids.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'hnc_tracker.db')

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

# Check column exists
cols = [row[1] for row in cur.execute("PRAGMA table_info(patients)")]
if 'anon_id' not in cols:
    cur.execute("ALTER TABLE patients ADD COLUMN anon_id VARCHAR(10)")
    print("✓ Added anon_id column")

# Assign PAT-001, PAT-002 ... to all patients without one
patients = cur.execute("SELECT id FROM patients ORDER BY id").fetchall()
for i, (pid,) in enumerate(patients, start=1):
    cur.execute(f"UPDATE patients SET anon_id='PAT-{i:03d}' WHERE id=? AND (anon_id IS NULL OR anon_id='')", (pid,))

conn.commit()

# Print result
print("\n  Patient roster:")
print(f"  {'ID':<5} {'Anon ID':<12} {'Code':<10}")
print(f"  {'-'*5} {'-'*12} {'-'*10}")
for row in cur.execute("SELECT id, anon_id, code FROM patients ORDER BY id"):
    print(f"  {row[0]:<5} {row[1]:<12} {row[2]:<10}")

conn.close()
print("\n✓ Done! Now run: python anonymization_patch.py")