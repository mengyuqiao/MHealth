from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class Patient(UserMixin, db.Model):
    __tablename__ = 'patients'
    id            = db.Column(db.Integer, primary_key=True)
    code          = db.Column(db.String(6), unique=True, nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    birthdate     = db.Column(db.String(20), nullable=False)
    calorie_goal  = db.Column(db.Integer, default=2000)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    is_active     = db.Column(db.Boolean, default=True)

    food_logs   = db.relationship('FoodLog',   backref='patient', lazy=True, cascade='all, delete-orphan')
    med_logs    = db.relationship('MedLog',    backref='patient', lazy=True, cascade='all, delete-orphan')
    weight_logs = db.relationship('WeightLog', backref='patient', lazy=True, cascade='all, delete-orphan')

    def get_id(self):
        return f"patient-{self.id}"

    def today_calories(self):
        today = datetime.utcnow().date()
        logs = FoodLog.query.filter(
            FoodLog.patient_id == self.id,
            db.func.date(FoodLog.logged_at) == today
        ).all()
        return sum(l.calories for l in logs if l.calories)

    def today_med_logs(self):
        today = datetime.utcnow().date()
        return MedLog.query.filter(
            MedLog.patient_id == self.id,
            db.func.date(MedLog.logged_at) == today
        ).order_by(MedLog.logged_at.desc()).all()

    def today_weight(self):
        today = datetime.utcnow().date()
        log = WeightLog.query.filter(
            WeightLog.patient_id == self.id,
            db.func.date(WeightLog.logged_at) == today
        ).first()
        return log

    def latest_weight(self):
        return WeightLog.query.filter_by(patient_id=self.id)\
                              .order_by(WeightLog.logged_at.desc()).first()


class FoodLog(db.Model):
    __tablename__ = 'food_logs'
    id          = db.Column(db.Integer, primary_key=True)
    patient_id  = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    calories    = db.Column(db.Integer)
    description = db.Column(db.Text)
    portion     = db.Column(db.String(20))
    image_path  = db.Column(db.String(255))
    logged_at   = db.Column(db.DateTime, default=datetime.utcnow)


class MedLog(db.Model):
    __tablename__ = 'med_logs'
    id               = db.Column(db.Integer, primary_key=True)
    patient_id       = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    med_name         = db.Column(db.String(200))
    med_dosage       = db.Column(db.String(100))
    med_instructions = db.Column(db.String(255))
    pain_before      = db.Column(db.Integer)
    pain_after       = db.Column(db.Integer)
    followup_due_at  = db.Column(db.DateTime)
    followup_done    = db.Column(db.Boolean, default=False)
    image_path       = db.Column(db.String(255))
    logged_at        = db.Column(db.DateTime, default=datetime.utcnow)

    def pain_label(self, score):
        if score is None: return ''
        if score <= 1:    return 'none'
        if score <= 3:    return 'mild'
        if score <= 6:    return 'moderate'
        return 'severe'

    @property
    def pain_before_label(self): return self.pain_label(self.pain_before)

    @property
    def pain_after_label(self): return self.pain_label(self.pain_after)


class WeightLog(db.Model):
    __tablename__ = 'weight_logs'
    id          = db.Column(db.Integer, primary_key=True)
    patient_id  = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    weight_lbs  = db.Column(db.Float, nullable=False)
    method      = db.Column(db.String(20), default='manual')  # 'manual' or 'scale'
    logged_at   = db.Column(db.DateTime, default=datetime.utcnow)


class Clinician(UserMixin, db.Model):
    __tablename__ = 'clinicians'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    name          = db.Column(db.String(100))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def get_id(self):
        return f"clinician-{self.id}"
