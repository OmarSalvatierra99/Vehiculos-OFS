from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash
from datetime import datetime
from sqlalchemy.orm import joinedload

from config import Config
from models import db, User, Vehicle, Trip, Request, VehicleLog, IncidentReport

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Rutas de autenticación
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrectos.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Rutas de la aplicación
@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        pending_requests = Request.query.filter_by(status='pending').all()
        active_trips = Trip.query.filter(Trip.end_time.is_(None)).all()
        all_vehicles = Vehicle.query.all()
        pending_incidents = IncidentReport.query.filter_by(status='pending').all()
        return render_template('dashboard.html', user=current_user, requests=pending_requests, active_trips=active_trips, all_vehicles=all_vehicles, pending_incidents=pending_incidents)
    else:  # Trabajador
        available_vehicles = Vehicle.query.filter_by(status='available').all()
        my_requests = Request.query.filter_by(user_id=current_user.id).order_by(Request.date_requested.desc()).all()
        return render_template('dashboard.html', user=current_user, vehicles=available_vehicles, my_requests=my_requests)

@app.route('/add_vehicle', methods=['POST'])
@login_required
def add_vehicle():
    if current_user.role != 'admin':
        flash('Solo los administradores pueden añadir vehículos.', 'danger')
        return redirect(url_for('dashboard'))
    try:
        license_plate = request.form['license_plate'].upper()
        make = request.form['make']
        model = request.form['model']
        current_odometer = request.form.get('current_odometer')

        if Vehicle.query.filter_by(license_plate=license_plate).first():
            flash('Ya existe un vehículo con esta placa.', 'warning')
        else:
            new_vehicle = Vehicle(
                license_plate=license_plate,
                make=make,
                model=model,
                current_odometer=current_odometer
            )
            db.session.add(new_vehicle)
            db.session.commit()
            flash('Vehículo añadido exitosamente.', 'success')
            log_event(new_vehicle.id, 'Creado', 'Vehículo añadido al sistema.')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al añadir vehículo: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/request_vehicle', methods=['POST'])
@login_required
def request_vehicle():
    if current_user.role != 'worker':
        flash('No tienes permiso para realizar esta acción.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        vehicle_id = request.form['vehicle_id']
        destination = request.form['destination']
        responsible_name = request.form['responsible_name']
        num_auditors = request.form['num_auditors']
        auditors_names = request.form['auditors_names']
        reason = request.form['reason']

        vehicle = Vehicle.query.get(vehicle_id)
        if vehicle.status != 'available':
            flash('Este vehículo no está disponible para ser solicitado.', 'warning')
            return redirect(url_for('dashboard'))

        new_request = Request(
            user_id=current_user.id,
            vehicle_id=vehicle_id,
            destination=destination,
            reason=reason,
            responsible_name=responsible_name,
            num_auditors=num_auditors,
            auditors_names=auditors_names
        )
        db.session.add(new_request)
        db.session.commit()
        flash('Solicitud enviada exitosamente. Esperando aprobación del administrador.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al enviar solicitud: {e}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/approve_request/<int:request_id>')
@login_required
def approve_request(request_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para aprobar solicitudes.', 'danger')
        return redirect(url_for('dashboard'))

    req = db.session.get(Request, request_id)
    if req and req.status == 'pending':
        try:
            req.status = 'approved'

            new_trip = Trip(
                user_id=req.user_id,
                vehicle_id=req.vehicle_id,
                destination=req.destination,
                reason=req.reason,
                start_time=datetime.now(),
                start_odometer=req.vehicle.current_odometer
            )

            vehicle = req.vehicle
            vehicle.status = 'in_use'

            db.session.add(new_trip)
            db.session.commit()
            flash('Solicitud aprobada y viaje registrado. El vehículo está en uso.', 'success')
            log_event(vehicle.id, 'En uso', f'Asignado a {req.user.username} para viaje a {req.destination}')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al aprobar la solicitud: {e}', 'danger')
    else:
        flash('La solicitud no existe o ya ha sido procesada.', 'warning')
    return redirect(url_for('dashboard'))

@app.route('/reject_request/<int:request_id>')
@login_required
def reject_request(request_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para rechazar solicitudes.', 'danger')
        return redirect(url_for('dashboard'))

    req = db.session.get(Request, request_id)
    if req and req.status == 'pending':
        try:
            req.status = 'rejected'
            db.session.commit()
            flash('Solicitud rechazada.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al rechazar la solicitud: {e}', 'danger')
    else:
        flash('La solicitud no existe o ya ha sido procesada.', 'warning')
    return redirect(url_for('dashboard'))

@app.route('/complete_trip/<int:trip_id>', methods=['GET', 'POST'])
@login_required
def complete_trip(trip_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para completar viajes.', 'danger')
        return redirect(url_for('dashboard'))

    trip = db.session.get(Trip, trip_id)
    if not trip or trip.end_time is not None:
        flash('El viaje no existe o ya ha sido completado.', 'warning')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            end_odometer = int(request.form['end_odometer'])
            if end_odometer < trip.start_odometer:
                flash('El odómetro final no puede ser menor que el inicial.', 'danger')
                return redirect(url_for('complete_trip', trip_id=trip.id))

            trip.end_time = datetime.now()
            trip.end_odometer = end_odometer
            trip.km_traveled = end_odometer - trip.start_odometer

            vehicle = trip.vehicle
            vehicle.status = 'available'
            vehicle.current_odometer = end_odometer

            db.session.commit()
            flash('Viaje completado y vehículo marcado como disponible.', 'success')
            log_event(vehicle.id, 'Disponible', f'Viaje completado por {trip.user.username}. Kilómetros recorridos: {trip.km_traveled}')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al completar el viaje: {e}', 'danger')
            return redirect(url_for('complete_trip', trip_id=trip.id))

    return render_template('complete_trip.html', trip=trip)

@app.route('/report')
@login_required
def report():
    if current_user.role != 'admin':
        flash('No tienes permiso para ver los reportes.', 'danger')
        return redirect(url_for('dashboard'))

    trips = Trip.query.filter(Trip.end_time.isnot(None)).options(db.joinedload(Trip.user), db.joinedload(Trip.vehicle)).all()
    requests_map = { (req.user_id, req.vehicle_id, req.destination): req for req in Request.query.all() }

    report_data = []
    for trip in trips:
        # Usar un enfoque más robusto para encontrar la solicitud
        request_for_trip = requests_map.get((trip.user_id, trip.vehicle_id, trip.destination))
        
        data = {
            'fecha_salida': trip.start_time.strftime('%d/%m/%Y %H:%M:%S'),
            'fecha_regreso': trip.end_time.strftime('%d/%m/%Y %H:%M:%S') if trip.end_time else 'N/A',
            'resguardante': trip.user.username,
            'placa': trip.vehicle.license_plate,
            'marca': trip.vehicle.make,
            'modelo': trip.vehicle.model,
            'odometro_inicio': trip.start_odometer,
            'odometro_fin': trip.end_odometer,
            'km_recorridos': trip.km_traveled,
            'responsable': request_for_trip.responsible_name if request_for_trip else 'N/A',
            'no_auditores': request_for_trip.num_auditors if request_for_trip else 'N/A',
            'nombre_auditores': request_for_trip.auditors_names if request_for_trip else 'N/A',
            'ruta_destino': trip.destination,
            'motivo_salida': trip.reason
        }
        report_data.append(data)

    return render_template('report.html', report_data=report_data)

@app.route('/vehicle_details/<int:vehicle_id>')
@login_required
def vehicle_details(vehicle_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para ver los detalles de los vehículos.', 'danger')
        return redirect(url_for('dashboard'))

    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash('Vehículo no encontrado.', 'warning')
        return redirect(url_for('dashboard'))

    trips = Trip.query.filter_by(vehicle_id=vehicle_id).order_by(Trip.start_time.desc()).all()
    logs = VehicleLog.query.filter_by(vehicle_id=vehicle_id).order_by(VehicleLog.timestamp.desc()).all()

    return render_template('vehicle_details.html', vehicle=vehicle, trips=trips, logs=logs)

@app.route('/set_maintenance/<int:vehicle_id>', methods=['POST'])
@login_required
def set_maintenance(vehicle_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para realizar esta acción.', 'danger')
        return redirect(url_for('dashboard'))

    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash('Vehículo no encontrado.', 'warning')
        return redirect(url_for('dashboard'))

    try:
        if vehicle.status != 'maintenance':
            vehicle.status = 'maintenance'
            db.session.commit()
            log_event(vehicle.id, 'En mantenimiento', 'Marcado por el administrador.')
            flash('El vehículo ha sido marcado para mantenimiento.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al marcar para mantenimiento: {e}', 'danger')

    return redirect(url_for('vehicle_details', vehicle_id=vehicle.id))

@app.route('/release_maintenance/<int:vehicle_id>', methods=['POST'])
@login_required
def release_maintenance(vehicle_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para realizar esta acción.', 'danger')
        return redirect(url_for('dashboard'))

    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash('Vehículo no encontrado.', 'warning')
        return redirect(url_for('dashboard'))

    try:
        if vehicle.status == 'maintenance':
            vehicle.status = 'available'
            db.session.commit()
            log_event(vehicle.id, 'Disponible', 'Mantenimiento completado.')
            flash('El vehículo ha sido marcado como disponible.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al liberar el vehículo: {e}', 'danger')

    return redirect(url_for('vehicle_details', vehicle_id=vehicle.id))

@app.route('/report_incident/<int:vehicle_id>', methods=['GET', 'POST'])
@login_required
def report_incident(vehicle_id):
    if current_user.role != 'worker' and current_user.role != 'admin':
        flash('No tienes permiso para reportar incidentes.', 'danger')
        return redirect(url_for('dashboard'))

    vehicle = db.session.get(Vehicle, vehicle_id)
    if not vehicle:
        flash('Vehículo no encontrado.', 'warning')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            incident_type = request.form['incident_type']
            description = request.form['description']
            location = request.form['location']

            new_incident = IncidentReport(
                vehicle_id=vehicle.id,
                user_id=current_user.id,
                incident_type=incident_type,
                description=description,
                location=location
            )
            db.session.add(new_incident)

            # Cambiar estado del vehículo a "incident" si no está ya
            if vehicle.status != 'incident':
                vehicle.status = 'incident'
                log_event(vehicle.id, 'Incidente reportado', f'Reporte de {incident_type} por {current_user.username}.')

            db.session.commit()
            flash('Reporte de incidente enviado exitosamente.', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al enviar el reporte: {e}', 'danger')

    return render_template('report_incident.html', vehicle=vehicle)

@app.route('/incident_reports')
@login_required
def incident_reports():
    if current_user.role != 'admin':
        flash('No tienes permiso para ver los reportes de incidentes.', 'danger')
        return redirect(url_for('dashboard'))

    incidents = IncidentReport.query.options(db.joinedload(IncidentReport.user), db.joinedload(IncidentReport.vehicle)).order_by(IncidentReport.report_date.desc()).all()
    return render_template('incident_reports.html', incidents=incidents)

@app.route('/view_incident/<int:incident_id>')
@login_required
def view_incident(incident_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para ver este reporte.', 'danger')
        return redirect(url_for('dashboard'))

    incident = db.session.get(IncidentReport, incident_id)
    if not incident:
        flash('Reporte de incidente no encontrado.', 'warning')
        return redirect(url_for('incident_reports'))

    return render_template('view_incident.html', incident=incident)


@app.route('/resolve_incident/<int:incident_id>', methods=['POST'])
@login_required
def resolve_incident(incident_id):
    if current_user.role != 'admin':
        flash('No tienes permiso para resolver incidentes.', 'danger')
        return redirect(url_for('dashboard'))

    incident = db.session.get(IncidentReport, incident_id)
    if not incident:
        flash('Reporte de incidente no encontrado.', 'warning')
        return redirect(url_for('incident_reports'))

    try:
        incident.status = 'resolved'
        vehicle = incident.vehicle
        if vehicle.status == 'incident':
            vehicle.status = 'available'  # Asumimos que al resolver el incidente, el vehículo vuelve a estar disponible
            log_event(vehicle.id, 'Incidente Resuelto', f'Incidente #{incident.id} resuelto. Vehículo ahora disponible.')

        db.session.commit()
        flash('Incidente marcado como resuelto.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al resolver el incidente: {e}', 'danger')

    return redirect(url_for('incident_reports'))


def log_event(vehicle_id, event, notes=None):
    log = VehicleLog(vehicle_id=vehicle_id, event=event, notes=notes)
    db.session.add(log)
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        # ¡IMPORTANTE! Si acabas de cambiar models.py, DEBES ejecutar:
        # rm inventario.db
        db.create_all()

        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', role='admin')
            admin_user.set_password('admin123')
            db.session.add(admin_user)

        if not User.query.filter_by(username='auditor1').first():
            auditor1 = User(username='auditor1', role='worker')
            auditor1.set_password('auditor123')
            db.session.add(auditor1)

        db.session.commit()

    app.run(host='0.0.0.0', port=5015, debug=True)
