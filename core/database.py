
import sqlite3
import json
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Centralized SQLite database management with WAL journaling.
    Handles all data persistence with thread-safe operations.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with WAL mode enabled"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        return conn
    
    def _init_database(self):
        """Initialize database schema with all required tables"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Employees table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Directives table (replaces tasks)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS directives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                directive_id TEXT UNIQUE NOT NULL,
                classification TEXT DEFAULT 'Internal Operational Mission',
                assignee TEXT NOT NULL,
                role TEXT NOT NULL,
                priority TEXT DEFAULT 'Silver Line',
                mission_window_minutes INTEGER DEFAULT 45,
                objective TEXT NOT NULL,
                situation TEXT,
                execution_steps TEXT,
                proof_required TEXT DEFAULT 'Image',
                escalate_to TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                proof_path TEXT,
                review_comment TEXT
            )
        ''')
        
        # Attendance logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee TEXT NOT NULL,
                label TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                actual_time TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT DEFAULT 'OK',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Chat history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                is_user INTEGER DEFAULT 1,
                attachment_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Proof uploads table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS proof_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                directive_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                verified INTEGER DEFAULT 0
            )
        ''')
        
        # Shopify cache table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shopify_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT NOT NULL
            )
        ''')
        
        # WhatsApp logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS whatsapp_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                message_body TEXT NOT NULL,
                direction TEXT DEFAULT 'inbound',
                processed INTEGER DEFAULT 0,
                response_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Break tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS break_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_minutes REAL,
                violation INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Sales data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                online_sales REAL DEFAULT 0,
                pos_sales REAL DEFAULT 0,
                orders_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Crawler logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawler_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                data_found TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized with WAL mode")
    
    def execute_query(self, query: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Execute SELECT query safely"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        return results
    
    def execute_write(self, query: str, params: Tuple = ()) -> int:
        """Execute INSERT/UPDATE/DELETE safely"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        return last_id
    
    def insert_employee(self, name: str, role: str) -> int:
        """Insert new employee"""
        return self.execute_write(
            'INSERT INTO employees (name, role) VALUES (?, ?)',
            (name, role)
        )
    
    def get_all_employees(self) -> List[Dict]:
        """Get all employees"""
        rows = self.execute_query('SELECT * FROM employees WHERE status = ?', ('active',))
        return [dict(row) for row in rows]
    
    def insert_directive(self, directive: Dict) -> int:
        """Insert new directive"""
        return self.execute_write('''
            INSERT INTO directives 
            (directive_id, classification, assignee, role, priority, mission_window_minutes,
             objective, situation, execution_steps, proof_required, escalate_to, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            directive['directive_id'],
            directive['classification'],
            directive['assignee'],
            directive['role'],
            directive['priority'],
            directive['mission_window_minutes'],
            directive['objective'],
            directive.get('situation', ''),
            json.dumps(directive.get('execution_steps', [])),
            directive.get('proof_required', 'Image'),
            directive.get('escalate_to', ''),
            directive.get('status', 'Pending'),
            directive['created_at']
        ))
    
    def get_directives(self, status: str = None, assignee: str = None) -> List[Dict]:
        """Get directives with optional filters"""
        query = 'SELECT * FROM directives WHERE 1=1'
        params = []
        
        if status:
            query += ' AND status = ?'
            params.append(status)
        
        if assignee:
            query += ' AND assignee = ?'
            params.append(assignee)
        
        query += ' ORDER BY created_at DESC'
        
        rows = self.execute_query(query, tuple(params))
        directives = []
        for row in rows:
            d = dict(row)
            d['execution_steps'] = json.loads(d['execution_steps'] or '[]')
            directives.append(d)
        return directives
    
    def update_directive_status(self, directive_id: str, status: str, 
                                 completed_at: str = None, proof_path: str = None) -> bool:
        """Update directive status"""
        if completed_at and proof_path:
            return self.execute_write('''
                UPDATE directives SET status = ?, completed_at = ?, proof_path = ?
                WHERE directive_id = ?
            ''', (status, completed_at, proof_path, directive_id)) > 0
        elif completed_at:
            return self.execute_write('''
                UPDATE directives SET status = ?, completed_at = ?
                WHERE directive_id = ?
            ''', (status, completed_at, directive_id)) > 0
        else:
            return self.execute_write('''
                UPDATE directives SET status = ?
                WHERE directive_id = ?
            ''', (status, directive_id)) > 0
    
    def insert_attendance_log(self, employee: str, label: str, 
                               scheduled_time: str, actual_time: str, 
                               date: str, status: str = 'OK') -> int:
        """Insert attendance log"""
        return self.execute_write('''
            INSERT INTO attendance_logs 
            (employee, label, scheduled_time, actual_time, date, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (employee, label, scheduled_time, actual_time, date, status))
    
    def get_today_attendance(self, date: str = None) -> List[Dict]:
        """Get today's attendance logs"""
        if not date:
            date = time_service.get_today_date()
        rows = self.execute_query(
            'SELECT * FROM attendance_logs WHERE date = ? ORDER BY actual_time DESC',
            (date,)
        )
        return [dict(row) for row in rows]
    
    def insert_chat_message(self, username: str, role: str, message: str, 
                            is_user: bool = True, attachment_path: str = None) -> int:
        """Insert chat message"""
        return self.execute_write('''
            INSERT INTO chat_history 
            (username, role, message, is_user, attachment_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (username, role, message, 1 if is_user else 0, attachment_path))
    
    def get_chat_history(self, username: str, limit: int = 50) -> List[Dict]:
        """Get chat history for user"""
        rows = self.execute_query('''
            SELECT * FROM chat_history 
            WHERE username = ? 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (username, limit))
        return [dict(row) for row in rows]
    
    def insert_break_record(self, employee: str, start_time: str) -> int:
        """Insert break start record"""
        return self.execute_write('''
            INSERT INTO break_tracking (employee, start_time)
            VALUES (?, ?)
        ''', (employee, start_time))
    
    def end_break_record(self, employee: str, end_time: str, duration_minutes: float, violation: bool) -> bool:
        """End active break record"""
        return self.execute_write('''
            UPDATE break_tracking 
            SET end_time = ?, duration_minutes = ?, violation = ?
            WHERE employee = ? AND end_time IS NULL
        ''', (end_time, duration_minutes, 1 if violation else 0, employee)) > 0
    
    def get_active_break(self, employee: str) -> Optional[Dict]:
        """Get active break for employee"""
        rows = self.execute_query('''
            SELECT * FROM break_tracking 
            WHERE employee = ? AND end_time IS NULL
            ORDER BY created_at DESC LIMIT 1
        ''', (employee,))
        if rows:
            return dict(rows[0])
        return None
    
    def insert_whatsapp_log(self, sender: str, message_body: str, 
                            direction: str = 'inbound') -> int:
        """Insert WhatsApp message log"""
        return self.execute_write('''
            INSERT INTO whatsapp_logs (sender, message_body, direction)
            VALUES (?, ?, ?)
        ''', (sender, message_body, direction))
    
    def insert_sales_data(self, date: str, online_sales: float, 
                          pos_sales: float, orders_count: int) -> int:
        """Insert daily sales data"""
        return self.execute_write('''
            INSERT INTO sales_data (date, online_sales, pos_sales, orders_count)
            VALUES (?, ?, ?, ?)
        ''', (date, online_sales, pos_sales, orders_count))
    
    def get_sales_data(self, days: int = 7) -> List[Dict]:
        """Get recent sales data"""
        rows = self.execute_query('''
            SELECT * FROM sales_data 
            ORDER BY date DESC 
            LIMIT ?
        ''', (days,))
        return [dict(row) for row in rows]
    
    def insert_crawler_log(self, keyword: str, marketplace: str, data_found: str) -> int:
        """Insert crawler result"""
        return self.execute_write('''
            INSERT INTO crawler_logs (keyword, marketplace, data_found)
            VALUES (?, ?, ?)
        ''', (keyword, marketplace, data_found))
    
    def get_recent_crawler_logs(self, limit: int = 20) -> List[Dict]:
        """Get recent crawler logs"""
        rows = self.execute_query('''
            SELECT * FROM crawler_logs 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in rows]
