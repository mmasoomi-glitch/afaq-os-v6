
from flask import Blueprint, render_template, request, jsonify
import uuid

manager_bp = Blueprint('manager_bp', __name__)

# This is a placeholder. In the full refactoring, these will be initialized in a central place.
from core.database import DatabaseManager
from core.security import SecurityManager
from core.time_service import time_service
from services.ai_engine import IntelligenceEngine
from services.shopify_mcp import EcomCommander
from services.whatsapp import WhatsAppHandler

# WARNING: These are temporary singletons. This will be fixed in the app factory.
db_manager = DatabaseManager('afaq_tactical.db')
security_manager = SecurityManager()
ai_engine = IntelligenceEngine()
ecom_commander = EcomCommander(db_manager)
whatsapp_handler = WhatsAppHandler(db_manager, ai_engine)

@manager_bp.route('/')
def manager_index():
    """Manager command center dashboard"""
    shopify_stats = ecom_commander.get_shopify_stats()
    employees = db_manager.get_all_employees()
    active_directives = db_manager.get_directives(status='Pending')
    crawler_logs = db_manager.get_recent_crawler_logs(10)
    
    return render_template(
        'manager.html',
        employees=employees,
        active_directives=active_directives,
        shopify_stats=shopify_stats,
        crawler_logs=crawler_logs,
        now_time=time_service.now_str()
    )

@manager_bp.route('/api/directives/generate', methods=['POST'])
def api_generate_directive():
    """Generate AI-powered directive with SOP"""
    data = request.json
    
    assignee = data.get('assignee', 'Hafiz')
    objective = data.get('objective', '')
    intel_recon = data.get('intel_recon', False)
    
    if not objective:
        return jsonify({'error': 'Objective required'}), 400
    
    sop_data = ai_engine.generate_directive_sop(objective, assignee, intel_recon)
    
    directive_id = f"VJ-OPS-{time_service.now().strftime('%Y')}-{uuid.uuid4().hex[:4].upper()}"
    
    directive = {
        'directive_id': directive_id,
        'classification': 'Internal Operational Mission',
        'assignee': assignee,
        'role': security_manager.get_employee_role(assignee),
        'priority': sop_data.get('priority', 'Silver Line'),
        'mission_window_minutes': sop_data.get('mission_window_minutes', 45),
        'objective': objective,
        'situation': sop_data.get('situation', ''),
        'execution_steps': sop_data.get('execution_steps', []),
        'proof_required': 'Image',
        'escalate_to': 'Abdolmadjid Masoomi',
        'status': 'Pending',
        'created_at': time_service.now_iso()
    }
    
    db_manager.insert_directive(directive)
    
    return jsonify({'success': True, 'directive_id': directive_id})

@manager_bp.route('/whatsapp/webhook', methods=['POST'])
def whatsapp_webhook():
    """WhatsApp webhook endpoint"""
    data = request.json
    result = whatsapp_handler.process_webhook(data)
    return jsonify(result)
