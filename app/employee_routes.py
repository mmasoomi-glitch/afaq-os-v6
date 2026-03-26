
from flask import Blueprint, render_template, request, session, jsonify
from werkzeug.utils import secure_filename
import os

employee_bp = Blueprint('employee_bp', __name__)

# This is a placeholder. In the full refactoring, these will be initialized in a central place.
from core.database import DatabaseManager
from core.security import SecurityManager
from core.time_service import time_service
from services.accountability import AccountabilityEngine

# WARNING: These are temporary singletons. This will be fixed in the app factory.
db_manager = DatabaseManager('afaq_tactical.db')
security_manager = SecurityManager()
accountability_engine = AccountabilityEngine(db_manager)


@employee_bp.route('/guide')
def user_guide():
    """Serves the user guide."""
    return render_template('user_guide.html')

@employee_bp.route('/', methods=['GET', 'POST'])
def employee_index():
    """Employee dashboard with attendance and directive management"""
    message = None
    message_type = 'info'
    current_employee = session.get('username', 'Hafiz')
    
    if request.method == 'POST':
        emp_name = request.form.get('employee')
        label = request.form.get('label')
        scheduled_time = request.form.get('time')
        
        if emp_name and label and scheduled_time:
            actual_time = time_service.now_str()
            date = time_service.get_today_date()
            db_manager.insert_attendance_log(emp_name, label, scheduled_time, actual_time, date)
            message = f"✅ {emp_name} - {label} Logged Successfully!"
            message_type = 'success'
            session['username'] = emp_name
    
    employee_role = security_manager.get_employee_role(current_employee)
    active_directives = db_manager.get_directives(status='Pending', assignee=current_employee)
    active_break = accountability_engine.get_active_break(current_employee)
    
    shifts = [
        {'label': 'Morning In', 'time': '09:00', 'active': True},
        {'label': 'Morning Out', 'time': '14:00', 'active': False},
        {'label': 'Evening In', 'time': '16:30', 'active': False},
        {'label': 'Evening Out', 'time': '21:30', 'active': False}
    ]
    
    kpi_text = "95.2%"
    kpi_color = "var(--brand-green)"
    
    return render_template(
        'employee.html',
        current_employee=current_employee,
        employee_role=employee_role,
        active_directives=active_directives,
        active_break=active_break is not None,
        break_start=active_break['start_time'] if active_break else '',
        break_elapsed=int(active_break['elapsed_minutes']) if active_break else 0,
        break_warning=active_break['warning'] if active_break else False,
        break_violation=active_break['violation'] if active_break else False,
        shifts=shifts,
        kpi_text=kpi_text,
        kpi_color=kpi_color,
        now_time=time_service.now_str()
    )

@employee_bp.route('/api/breaks/toggle', methods=['POST'])
def api_toggle_break():
    """Toggle break status"""
    employee = session.get('username', 'Hafiz')
    active_break = accountability_engine.get_active_break(employee)
    
    if active_break:
        result = accountability_engine.end_break(employee)
    else:
        result = accountability_engine.start_break(employee)
    
    return jsonify(result)

@employee_bp.route('/api/directives/complete', methods=['POST'])
def api_complete_directive():
    """Complete directive with proof upload"""
    directive_id = request.form.get('directive_id')
    
    if 'proof_file' not in request.files:
        return jsonify({'error': 'Proof file required'}), 400
    
    file = request.files['proof_file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    allowed_extensions = {'jpg', 'jpeg', 'png', 'pdf'}
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    if ext not in allowed_extensions:
        return jsonify({'error': 'File type not allowed'}), 400
    
    # This path needs to be configured properly
    PROOF_UPLOADS_DIR = 'static/proof_uploads'
    directive_folder = os.path.join(PROOF_UPLOADS_DIR, directive_id)
    os.makedirs(directive_folder, exist_ok=True)
    
    file_path = os.path.join(directive_folder, filename)
    file.save(file_path)
    
    completed_at = time_service.now_iso()
    db_manager.update_directive_status(directive_id, 'Awaiting Review', completed_at, file_path)
    
    return jsonify({'success': True})
