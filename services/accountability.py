
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AccountabilityEngine:
    """
    Employee break tracking and discipline management.
    Enforces UAE labor law compliance while maintaining productivity.
    """
    
    MAX_BREAK_MINUTES = 15
    WARNING_THRESHOLD = 10
    
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def start_break(self, employee: str) -> Dict[str, Any]:
        """
        Record break start time.
        """
        from core.time_service import time_service
        start_time = time_service.now_iso()
        break_id = self.db_manager.insert_break_record(employee, start_time)
        
        logger.info(f"Break started: {employee} at {start_time}")
        return {
            'id': break_id,
            'employee': employee,
            'start_time': start_time,
            'status': 'active'
        }
    
    def end_break(self, employee: str) -> Dict[str, Any]:
        """
        Record break end time and calculate duration.
        """
        from core.time_service import time_service
        end_time = time_service.now_iso()
        
        active_break = self.db_manager.get_active_break(employee)
        if not active_break:
            return {'error': 'No active break found'}
        
        start_dt = time_service.parse_iso(active_break['start_time'])
        end_dt = time_service.parse_iso(end_time)
        duration_minutes = (end_dt - start_dt).total_seconds() / 60.0
        
        violation = duration_minutes > self.MAX_BREAK_MINUTES
        
        self.db_manager.end_break_record(employee, end_time, duration_minutes, violation)
        
        logger.info(f"Break ended: {employee} ({duration_minutes:.1f} min) - {'VIOLATION' if violation else 'OK'}")
        
        return {
            'employee': employee,
            'start_time': active_break['start_time'],
            'end_time': end_time,
            'duration_minutes': round(duration_minutes, 1),
            'violation': violation
        }
    
    def get_active_break(self, employee: str) -> Optional[Dict]:
        """Get current active break for employee"""
        from core.time_service import time_service
        active = self.db_manager.get_active_break(employee)
        if active:
            start_dt = time_service.parse_iso(active['start_time'])
            elapsed = (time_service.now() - start_dt).total_seconds() / 60.0
            active = dict(active)  # Convert from sqlite3.Row to dict
            active['elapsed_minutes'] = round(elapsed, 1)
            active['warning'] = elapsed > self.WARNING_THRESHOLD
            active['violation'] = elapsed > self.MAX_BREAK_MINUTES
        return active
