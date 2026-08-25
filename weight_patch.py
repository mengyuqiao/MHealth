"""
Run this once to patch app.py and templates/patient/home.html with weight logging.
Usage: python weight_patch.py
"""
import re, os

BASE = os.path.dirname(os.path.abspath(__file__))

# ── 1. Patch app.py ────────────────────────────────────────────────────────────
app_path = os.path.join(BASE, 'app.py')
with open(app_path) as f:
    app = f.read()

# 1a. Add WeightLog to database import
app = app.replace(
    'from database import db, Patient, FoodLog, MedLog, Clinician',
    'from database import db, Patient, FoodLog, MedLog, WeightLog, Clinician'
)

# 1b. Add weight routes before the clinician section
weight_routes = '''
# ── Patient: Weight Logging ────────────────────────────────────────────────────
@app.route('/log/weight', methods=['GET', 'POST'])
@patient_required
def log_weight():
    today_weight = current_user.today_weight()

    if request.method == 'POST':
        try:
            weight_lbs = float(request.form.get('weight_lbs', 0))
        except ValueError:
            flash('Please enter a valid weight.')
            return redirect(request.url)

        if weight_lbs < 50 or weight_lbs > 500:
            flash('Please enter a weight between 50 and 500 lbs.')
            return redirect(request.url)

        method = request.form.get('method', 'manual')

        # Update today\'s log if it already exists
        if today_weight:
            today_weight.weight_lbs = weight_lbs
            today_weight.method = method
            log = today_weight
        else:
            log = WeightLog(
                patient_id = current_user.id,
                weight_lbs = weight_lbs,
                method     = method,
            )
            db.session.add(log)
        db.session.commit()

        return redirect(url_for('weight_saved', log_id=log.id))

    return render_template('patient/weight_log.html', today_weight=today_weight)

@app.route('/log/weight/saved/<int:log_id>')
@patient_required
def weight_saved(log_id):
    log = WeightLog.query.get_or_404(log_id)
    # Get previous log for delta display
    prev_log = WeightLog.query.filter(
        WeightLog.patient_id == current_user.id,
        WeightLog.id != log_id
    ).order_by(WeightLog.logged_at.desc()).first()
    return render_template('patient/weight_saved.html', log=log, prev_log=prev_log)

'''

# Insert before clinician auth section
app = app.replace(
    '# ── Clinician: Auth ──',
    weight_routes + '# ── Clinician: Auth ──'
)

# 1c. Add weight data to clinician patient view
app = app.replace(
    "    return render_template('clinician/patient.html',\n                           patient=patient,\n                           daily_calories=dict(daily_calories),\n                           pain_timeline=pain_timeline,\n                           med_logs=med_logs,\n                           food_logs=food_logs)",
    """    weight_logs = WeightLog.query.filter(
        WeightLog.patient_id == patient_id,
        WeightLog.logged_at >= two_weeks_ago
    ).order_by(WeightLog.logged_at).all()

    weight_timeline = [
        {'date': w.logged_at.strftime('%Y-%m-%d'), 'weight': w.weight_lbs}
        for w in weight_logs
    ]

    return render_template('clinician/patient.html',
                           patient=patient,
                           daily_calories=dict(daily_calories),
                           pain_timeline=pain_timeline,
                           weight_timeline=weight_timeline,
                           med_logs=med_logs,
                           food_logs=food_logs)"""
)

with open(app_path, 'w') as f:
    f.write(app)
print("✓ app.py patched")

# ── 2. Patch home.html ─────────────────────────────────────────────────────────
home_path = os.path.join(BASE, 'templates/patient/home.html')
with open(home_path) as f:
    home = f.read()

weight_card = """
  <!-- Weight card -->
  {% set today_wt = patient.today_weight() %}
  <div class="stat-card weight-card">
    <div class="stat-card-label">Today's weight</div>
    {% if today_wt %}
      <div class="weight-logged-row">
        <span class="weight-logged-val">{{ today_wt.weight_lbs }} lbs</span>
        {% set latest = patient.latest_weight() %}
        {% set prev = namespace(val=None) %}
        {% for w in patient.weight_logs %}
          {% if w.id != today_wt.id and prev.val is none %}
            {% set prev.val = w.weight_lbs %}
          {% endif %}
        {% endfor %}
        <a href="{{ url_for('log_weight') }}" class="weight-edit-link">Edit</a>
      </div>
      <div class="weight-logged-sub">Logged today ✓</div>
    {% else %}
      <a href="{{ url_for('log_weight') }}" class="weight-prompt">
        <span class="weight-prompt-icon">⚖️</span>
        <div>
          <div class="weight-prompt-title">Log your weight</div>
          <div class="weight-prompt-sub">Once a day, in the morning</div>
        </div>
        <span class="weight-prompt-arrow">›</span>
      </a>
    {% endif %}
  </div>

"""

# Insert weight card before action buttons
home = home.replace('  <!-- Action buttons -->', weight_card + '  <!-- Action buttons -->')

with open(home_path, 'w') as f:
    f.write(home)
print("✓ home.html patched")

# ── 3. Patch clinician/patient.html ───────────────────────────────────────────
clin_path = os.path.join(BASE, 'templates/clinician/patient.html')
with open(clin_path) as f:
    clin = f.read()

# Add weight chip to summary
clin = clin.replace(
    "    {% if last_med %}\n    <div class=\"chip\">\n      <span class=\"chip-label\">Last pain score</span>",
    """    {% set latest_wt = patient.latest_weight() %}
    {% if latest_wt %}
    <div class="chip">
      <span class="chip-label">Latest weight</span>
      <span class="chip-val">{{ latest_wt.weight_lbs }} lbs</span>
    </div>
    {% endif %}
    {% if last_med %}
    <div class="chip">
      <span class="chip-label">Last pain score</span>"""
)

# Add weight chart before med log table
weight_chart = """
  <!-- Weight chart -->
  <div class="chart-card">
    <div class="chart-title">Weight Trend (last 14 days)</div>
    <div class="chart-wrap">
      <canvas id="weightChart"></canvas>
    </div>
  </div>

"""
clin = clin.replace('  <!-- Med log table -->', weight_chart + '  <!-- Med log table -->')

# Add weight chart JS and data
clin = clin.replace(
    'const calData   = {{ daily_calories | tojson }};',
    'const calData   = {{ daily_calories | tojson }};\nconst weightData = {{ weight_timeline | tojson }};'
)

weight_js = """
// ── Weight chart ───────────────────────────────────────────────────────
new Chart(document.getElementById('weightChart'), {
  type: 'line',
  data: {
    labels: weightData.map(w => {
      const dt = new Date(w.date + 'T12:00:00');
      return dt.toLocaleDateString('en-US', {month:'short', day:'numeric'});
    }),
    datasets: [{
      label: 'Weight (lbs)',
      data: weightData.map(w => w.weight),
      borderColor: '#1a4a6b',
      backgroundColor: 'rgba(26,74,107,0.08)',
      tension: 0.3,
      pointRadius: 5,
      fill: true,
    }]
  },
  options: {
    responsive: true,
    scales: {
      y: { grid: { color: '#e8e8e8' } }
    }
  }
});
"""
clin = clin.replace('</script>', weight_js + '\n</script>')

with open(clin_path, 'w') as f:
    f.write(clin)
print("✓ clinician/patient.html patched")

print("\nAll done! Restart the app: bash run.sh")
