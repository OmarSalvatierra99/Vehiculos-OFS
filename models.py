from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='worker')  # 'admin' o 'worker'

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20), unique=True, nullable=False)
    make = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='available') # 'available', 'in_use', 'maintenance', 'incident'
    current_odometer = db.Column(db.Integer, default=0)

class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    destination = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.String(255), nullable=True)

    start_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    end_time = db.Column(db.DateTime, nullable=True)

    start_odometer = db.Column(db.Integer)
    end_odometer = db.Column(db.Integer)
    km_traveled = db.Column(db.Integer)

    user = db.relationship('User', backref='trips')
    vehicle = db.relationship('Vehicle', backref='trips')

class Request(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    destination = db.Column(db.String(120), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected'
    date_requested = db.Column(db.DateTime, default=datetime.now)

    responsible_name = db.Column(db.String(120))
    num_auditors = db.Column(db.Integer)
    auditors_names = db.Column(db.Text)

    user = db.relationship('User', backref='requests')
    vehicle = db.relationship('Vehicle', backref='requests')

class VehicleLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    timestamp = db.Column(db.DateTime, default=datetime.now)
    event = db.Column(db.String(100), nullable=False)
    notes = db.Column(db.String(255))

    vehicle = db.relationship('Vehicle', backref=db.backref('logs', lazy='dynamic'))

class IncidentReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    report_date = db.Column(db.DateTime, default=datetime.now)
    incident_type = db.Column(db.String(50), nullable=False) # 'Choque', 'Falla Mecánica', 'Daño', etc.
    description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(255))
    status = db.Column(db.String(50), default='pending') # 'pending', 'resolved', 'in_progress'

    vehicle = db.relationship('Vehicle', backref='incidents')
    user = db.relationship('User', backref='incidents')
