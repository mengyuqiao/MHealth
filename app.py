import os
import uuid
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from database import db, Patient, FoodLog, MedLog, WeightLog, Clinician
import vlm_service

# ── App setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'welcome'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'heic', 'webp'}

# ── Login manager ──────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith('patient-'):
        return Patient.query.get(int(user_id.split('-')[1]))
    elif user_id.startswith('clinician-'):
        return Clinician.query.get(int(user_id.split('-')[1]))
    return None

# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_upload(file):
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    return path

def clinician_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not isinstance(current_user, Clinician):
            return redirect(url_for('clinician_login'))
        return f(*args, **kwargs)
    return decorated

def patient_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not isinstance(current_user, Patient):
            return redirect(url_for('welcome'))
        return f(*args, **kwargs)
    return decorated

# ── Patient: Onboarding ────────────────────────────────────────────────────────
@app.route('/')
def welcome():
    return render_template('patient/welcome.html',
                           support_phone=app.config['SUPPORT_PHONE'])

@app.route('/enter-code', methods=['GET', 'POST'])
def enter_code():
    error = None
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        patient = Patient.query.filter_by(code=code, is_active=True).first()
        if patient:
            session['pending_patient_id'] = patient.id
            return redirect(url_for('confirm_identity'))
        error = "Code not found. Please check your card or call your care team."
    return render_template('patient/enter_code.html',
                           error=error,
                           support_phone=app.config['SUPPORT_PHONE'])

@app.route('/confirm-identity', methods=['GET', 'POST'])
def confirm_identity():
    patient_id = session.get('pending_patient_id')
    if not patient_id:
        return redirect(url_for('welcome'))
    patient = Patient.query.get_or_404(patient_id)
    if request.method == 'POST':
        if request.form.get('confirm') == 'yes':
            login_user(patient, remember=True)
            session.pop('pending_patient_id', None)
            return redirect(url_for('patient_home'))
        else:
            session.pop('pending_patient_id', None)
            return redirect(url_for('enter_code'))
    return render_template('patient/confirm_identity.html',
                           patient=patient,
                           support_phone=app.config['SUPPORT_PHONE'])

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('welcome'))

# ── Patient: Home ──────────────────────────────────────────────────────────────
@app.route('/home')
@patient_required
def patient_home():
    patient = current_user
    today_cal = patient.today_calories()
    today_meds = patient.today_med_logs()

    # Check if there's a pending follow-up
    pending_followup = MedLog.query.filter(
        MedLog.patient_id == patient.id,
        MedLog.followup_done == False,
        MedLog.followup_due_at <= datetime.utcnow(),
        MedLog.pain_after == None
    ).order_by(MedLog.followup_due_at).first()

    return render_template('patient/home.html',
                           patient=patient,
                           today_cal=today_cal,
                           today_meds=today_meds,
                           pending_followup=pending_followup,
                           support_phone=app.config['SUPPORT_PHONE'])

# ── Patient: Food Logging ──────────────────────────────────────────────────────
@app.route('/log/food', methods=['GET', 'POST'])
@patient_required
def log_food():
    if request.method == 'POST':
        if 'photo' not in request.files or request.files['photo'].filename == '':
            flash('Please take a photo first.')
            return redirect(request.url)

        file = request.files['photo']
        if not allowed_file(file.filename):
            flash('Please use a JPG or PNG photo.')
            return redirect(request.url)

        image_path = save_upload(file)
        result = vlm_service.analyze_food(image_path)

        # Store in session for the confirm screen
        session['food_analysis'] = {
            'calories':    result['calories'],
            'description': result['description'],
            'image_path':  image_path,
        }
        return redirect(url_for('confirm_food'))

    return render_template('patient/food_log.html')

@app.route('/log/food/confirm', methods=['GET', 'POST'])
@patient_required
def confirm_food():
    data = session.get('food_analysis')
    if not data:
        return redirect(url_for('log_food'))

    if request.method == 'POST':
        portion  = request.form.get('portion', 'all')
        calories = data['calories']

        # Adjust calories based on portion answer
        if portion == 'less':
            calories = int(calories * 0.6)
        elif portion == 'more':
            calories = int(calories * 1.4)

        log = FoodLog(
            patient_id  = current_user.id,
            calories    = calories,
            description = data['description'],
            portion     = portion,
            image_path  = data['image_path'],
        )
        db.session.add(log)
        db.session.commit()

        # Clean up temp image
        try:
            os.remove(data['image_path'])
        except Exception:
            pass

        session.pop('food_analysis', None)
        return redirect(url_for('food_saved', log_id=log.id))

    return render_template('patient/food_confirm.html', data=data)

@app.route('/log/food/saved/<int:log_id>')
@patient_required
def food_saved(log_id):
    log = FoodLog.query.get_or_404(log_id)
    today_cal = current_user.today_calories()
    return render_template('patient/food_saved.html',
                           log=log,
                           today_cal=today_cal,
                           goal=current_user.calorie_goal)

# ── Patient: Medication Logging ────────────────────────────────────────────────
@app.route('/log/med', methods=['GET', 'POST'])
@patient_required
def log_med():
    if request.method == 'POST':
        if 'photo' not in request.files or request.files['photo'].filename == '':
            flash('Please take a photo first.')
            return redirect(request.url)

        file = request.files['photo']
        if not allowed_file(file.filename):
            flash('Please use a JPG or PNG photo.')
            return redirect(request.url)

        image_path = save_upload(file)
        result = vlm_service.analyze_medication(image_path)

        session['med_analysis'] = {
            'med_name':     result['med_name'],
            'dosage':       result['dosage'],
            'instructions': result['instructions'],
            'image_path':   image_path,
        }
        return redirect(url_for('confirm_med'))

    return render_template('patient/med_log.html')

@app.route('/log/med/confirm', methods=['GET', 'POST'])
@patient_required
def confirm_med():
    data = session.get('med_analysis')
    if not data:
        return redirect(url_for('log_med'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'retake':
            try:
                os.remove(data['image_path'])
            except Exception:
                pass
            session.pop('med_analysis', None)
            return redirect(url_for('log_med'))
        # confirmed — go to pain rating
        return redirect(url_for('pain_rating'))

    return render_template('patient/med_confirm.html', data=data)

@app.route('/log/med/pain', methods=['GET', 'POST'])
@patient_required
def pain_rating():
    data = session.get('med_analysis')
    if not data:
        return redirect(url_for('log_med'))

    if request.method == 'POST':
        pain_score = int(request.form.get('pain_score', 5))
        followup_at = datetime.utcnow() + timedelta(
            minutes=app.config['FOLLOWUP_DELAY_MINUTES']
        )

        log = MedLog(
            patient_id      = current_user.id,
            med_name        = data['med_name'],
            med_dosage      = data['dosage'],
            med_instructions= data['instructions'],
            pain_before     = pain_score,
            followup_due_at = followup_at,
            image_path      = data['image_path'],
        )
        db.session.add(log)
        db.session.commit()

        try:
            os.remove(data['image_path'])
        except Exception:
            pass

        session.pop('med_analysis', None)
        return redirect(url_for('med_saved', log_id=log.id))

    return render_template('patient/pain_rating.html')

@app.route('/log/med/saved/<int:log_id>')
@patient_required
def med_saved(log_id):
    log = MedLog.query.get_or_404(log_id)
    return render_template('patient/med_saved.html', log=log)

# ── Patient: Follow-up Check-in ────────────────────────────────────────────────
@app.route('/checkin/<int:log_id>', methods=['GET', 'POST'])
@patient_required
def pain_checkin(log_id):
    log = MedLog.query.get_or_404(log_id)
    if log.patient_id != current_user.id:
        return redirect(url_for('patient_home'))

    if request.method == 'POST':
        pain_after = request.form.get('pain_score')
        if pain_after is not None:
            log.pain_after = int(pain_after)
        log.followup_done = True
        db.session.commit()
        return redirect(url_for('checkin_saved', log_id=log.id))

    return render_template('patient/pain_checkin.html', log=log)

@app.route('/checkin/<int:log_id>/saved')
@patient_required
def checkin_saved(log_id):
    log = MedLog.query.get_or_404(log_id)
    return render_template('patient/checkin_saved.html', log=log)

# ── API: check for pending follow-up (polled by frontend) ─────────────────────
@app.route('/api/pending-followup')
@patient_required
def api_pending_followup():
    log = MedLog.query.filter(
        MedLog.patient_id == current_user.id,
        MedLog.followup_done == False,
        MedLog.followup_due_at <= datetime.utcnow(),
        MedLog.pain_after == None
    ).order_by(MedLog.followup_due_at).first()

    if log:
        return jsonify({
            'pending': True,
            'log_id': log.id,
            'med_name': log.med_name,
            'checkin_url': url_for('pain_checkin', log_id=log.id)
        })
    return jsonify({'pending': False})


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

        # Update today's log if it already exists
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

# ── Clinician: Auth ────────────────────────────────────────────────────────────
@app.route('/clinician/login', methods=['GET', 'POST'])
def clinician_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        clinician = Clinician.query.filter_by(username=username).first()
        if clinician and check_password_hash(clinician.password_hash, password):
            login_user(clinician, remember=True)
            return redirect(url_for('clinician_dashboard'))
        error = "Invalid username or password."
    return render_template('clinician/login.html', error=error)

@app.route('/clinician/logout')
def clinician_logout():
    logout_user()
    return redirect(url_for('clinician_login'))

# ── Clinician: Dashboard ───────────────────────────────────────────────────────
@app.route('/clinician/')
@clinician_required
def clinician_dashboard():
    patients = Patient.query.filter_by(is_active=True).order_by(Patient.name).all()
    today = datetime.utcnow().date()

    patient_data = []
    for p in patients:
        today_cal = p.today_calories()
        cal_pct = round((today_cal / p.calorie_goal) * 100) if p.calorie_goal else 0

        last_med = MedLog.query.filter_by(patient_id=p.id)\
                               .order_by(MedLog.logged_at.desc()).first()

        # Flag: <50% calories today
        flag_nutrition = cal_pct < 50
        # Flag: pain >= 7 in last 24h
        flag_pain = db.session.query(MedLog).filter(
            MedLog.patient_id == p.id,
            MedLog.pain_before >= 7,
            MedLog.logged_at >= datetime.utcnow() - timedelta(hours=24)
        ).first() is not None

        patient_data.append({
            'patient':         p,
            'today_cal':       today_cal,
            'cal_pct':         cal_pct,
            'last_med':        last_med,
            'flag_nutrition':  flag_nutrition,
            'flag_pain':       flag_pain,
        })

    return render_template('clinician/dashboard.html',
                           clinician=current_user,
                           patient_data=patient_data,
                           today=today)

@app.route('/clinician/patient/<int:patient_id>')
@clinician_required
def clinician_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)

    # Last 14 days of food logs grouped by date
    two_weeks_ago = datetime.utcnow() - timedelta(days=14)
    food_logs = FoodLog.query.filter(
        FoodLog.patient_id == patient_id,
        FoodLog.logged_at >= two_weeks_ago
    ).order_by(FoodLog.logged_at).all()

    med_logs = MedLog.query.filter(
        MedLog.patient_id == patient_id,
        MedLog.logged_at >= two_weeks_ago
    ).order_by(MedLog.logged_at).all()

    # Build day-by-day calorie totals for chart
    from collections import defaultdict
    daily_calories = defaultdict(int)
    for fl in food_logs:
        day = fl.logged_at.strftime('%Y-%m-%d')
        daily_calories[day] += fl.calories or 0

    # Build pain timeline
    pain_timeline = [
        {
            'date':        ml.logged_at.strftime('%Y-%m-%d %H:%M'),
            'med':         ml.med_name,
            'pain_before': ml.pain_before,
            'pain_after':  ml.pain_after,
        }
        for ml in med_logs
    ]

    weight_logs = WeightLog.query.filter(
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
                           food_logs=food_logs)

# ── Clinician: API for chart data ──────────────────────────────────────────────
@app.route('/clinician/api/patient/<int:patient_id>/data')
@clinician_required
def clinician_patient_data(patient_id):
    days = int(request.args.get('days', 14))
    since = datetime.utcnow() - timedelta(days=days)

    food_logs = FoodLog.query.filter(
        FoodLog.patient_id == patient_id,
        FoodLog.logged_at >= since
    ).all()

    med_logs = MedLog.query.filter(
        MedLog.patient_id == patient_id,
        MedLog.logged_at >= since
    ).all()

    from collections import defaultdict
    daily_cal = defaultdict(int)
    for fl in food_logs:
        daily_cal[fl.logged_at.strftime('%Y-%m-%d')] += fl.calories or 0

    return jsonify({
        'daily_calories': daily_cal,
        'pain_events': [
            {
                'date':        m.logged_at.isoformat(),
                'med':         m.med_name,
                'pain_before': m.pain_before,
                'pain_after':  m.pain_after,
            }
            for m in med_logs
        ]
    })

# ── DB init + seed ─────────────────────────────────────────────────────────────
def seed_db():
    """Create a default clinician and two demo patients if DB is empty."""
    if Clinician.query.first():
        return

    # Default clinician account
    clinician = Clinician(
        username      = 'admin',
        password_hash = generate_password_hash('admin123'),
        name          = 'Dr. Sura'
    )
    db.session.add(clinician)

    # Demo patients
    p1 = Patient(code='472910', name='John Smith',
                 birthdate='03/14/1958', calorie_goal=2000)
    p2 = Patient(code='835621', name='Maria Garcia',
                 birthdate='07/22/1965', calorie_goal=1800)
    db.session.add_all([p1, p2])
    db.session.commit()
    logger.info("Database seeded with demo data.")

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_db()

    # Pre-load the VLM before accepting requests
    import threading
    threading.Thread(target=vlm_service.warmup, daemon=True).start()

    app.run(host='0.0.0.0', port=5000, debug=False)
