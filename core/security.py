
import os
import hashlib
import time
from functools import wraps
from flask import session, jsonify, request
import logging
from typing import List

logger = logging.getLogger(__name__)

class SecurityManager:
    """
    Handles authentication, session management, and role-based access control.
    Implements strict role separation for all 5 employee tiers.
    """
    
    ROLE_OWNER = 'owner'
    ROLE_COMMANDER = 'commander'
    ROLE_DIGITAL_MANAGER = 'digital_manager'
    ROLE_CASH_CONTROL = 'cash_control'
    ROLE_FIELD_LOGISTICS = 'field_logistics'
    
    ROLE_PERMISSIONS = {
        ROLE_OWNER: ['admin', 'finance', 'strategy', 'override', 'view_all', 'approve_all'],
        ROLE_COMMANDER: ['command', 'approve', 'reject', 'audit', 'view_all'],
        ROLE_DIGITAL_MANAGER: ['shopify', 'marketplace', 'seo', 'inventory'],
        ROLE_CASH_CONTROL: ['pos', 'reconciliation', 'receipts', 'finance'],
        ROLE_FIELD_LOGISTICS: ['missions', 'transit', 'cargo', 'field_ops']
    }
    
    EMPLOYEE_ROLES = {
        'Mrs. Sara Zeinali': ROLE_OWNER,
        'Abdolmadjid Masoomi': ROLE_COMMANDER,
        'Hafiz': ROLE_DIGITAL_MANAGER,
        'Mehriban': ROLE_CASH_CONTROL,
        'Nader': ROLE_FIELD_LOGISTICS
    }
    
    def __init__(self):
        self.secret_key = os.environ.get('FLASK_SECRET')
        if not self.secret_key:
            raise ValueError("FLASK_SECRET environment variable not set.")
        self.session_timeout = int(os.environ.get('SESSION_DAYS', 90)) * 24 * 60 * 60
        self.login_attempts = {}
    
    def generate_session_token(self, user_id: str) -> str:
        """Generate secure session token with timestamp"""
        token_data = f"{user_id}:{time.time()}:{self.secret_key}"
        return hashlib.sha256(token_data.encode()).hexdigest()
    
    def get_employee_role(self, username: str) -> str:
        """Get role for employee username"""
        return self.EMPLOYEE_ROLES.get(username, self.ROLE_FIELD_LOGISTICS)
    
    def has_permission(self, username: str, permission: str) -> bool:
        """Check if employee has specific permission"""
        role = self.get_employee_role(username)
        return permission in self.ROLE_PERMISSIONS.get(role, [])
    
    def require_role(self, required_roles: List[str]):
        """Decorator for role-based route protection"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                username = session.get('username')
                if not username:
                    return jsonify({"error": "Authentication required"}), 401
                
                user_role = self.get_employee_role(username)
                if user_role not in required_roles:
                    logger.warning(f"Unauthorized access attempt by {username} to {request.path}")
                    return jsonify({"error": "Insufficient permissions"}), 403
                
                return f(*args, **kwargs)
            return decorated_function
        return decorator
    
    def log_login_attempt(self, username: str, success: bool, ip: str):
        """Log login attempt for security audit"""
        from .time_service import time_service
        timestamp = time_service.now_iso()
        status = 'SUCCESS' if success else 'FAILED'
        logger.info(f"LOGIN ATTEMPT: {username} from {ip} - {status} at {timestamp}")
        
        if not success:
            if username not in self.login_attempts:
                self.login_attempts[username] = []
            self.login_attempts[username].append({
                'timestamp': timestamp,
                'ip': ip
            })
