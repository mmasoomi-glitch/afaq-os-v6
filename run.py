
import os
import threading
import webbrowser
import logging
import socket
import time
from app import create_app
from core.database import DatabaseManager
from core.security import SecurityManager
from services.recon_crawler import TacticalRecon
from services.shopify_mcp import EcomCommander

# =============================================================================
# CONFIGURATION & ENVIRONMENT LOADING
# =============================================================================
def load_env_file(env_path: str):
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"\'')
                    if key not in os.environ:
                        os.environ[key] = value

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_env_file(os.path.join(BASE_DIR, '.env'))

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_FILE = os.path.join(BASE_DIR, 'afaq_tactical.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('AfaqTactical')

# =============================================================================
# INITIALIZE SERVICES
# =============================================================================
db_manager = DatabaseManager(os.path.join(BASE_DIR, 'afaq_tactical.db'))
security_manager = SecurityManager()
ecom_commander = EcomCommander(db_manager)
tactical_recon = TacticalRecon(db_manager)

# =============================================================================
# BACKGROUND THREADS
# =============================================================================
def shopify_sync_thread():
    while True:
        try:
            ecom_commander.get_shopify_stats()
            time.sleep(60)
        except Exception as e:
            logger.error(f"Shopify sync error: {e}")
            time.sleep(60)

def recon_crawler_thread():
    keywords = ['professional hair straightener', 'salon equipment UAE', 'hair tools Dubai']
    tactical_recon.start_background_crawler(keywords)

# =============================================================================
# APPLICATION STARTUP
# =============================================================================
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def run_app(app, port):
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    logger.info("Initializing Afaq Tactical Command System V5.3-OMEGA-REF")

    # Seed employees if db is empty
    if not db_manager.get_all_employees():
        for name, role in security_manager.EMPLOYEE_ROLES.items():
            db_manager.insert_employee(name, role)
            logger.info(f"Seeded employee: {name}")

    # Start background threads
    threading.Thread(target=shopify_sync_thread, daemon=True).start()
    threading.Thread(target=recon_crawler_thread, daemon=True).start()

    # Create and run apps
    employee_app = create_app('employee')
    manager_app = create_app('manager')
    
    employee_app.secret_key = security_manager.secret_key
    manager_app.secret_key = security_manager.secret_key

    threading.Thread(target=run_app, args=(employee_app, 3456), daemon=True).start()
    threading.Thread(target=run_app, args=(manager_app, 6789), daemon=True).start()

    local_ip = get_local_ip()
    print("\n" + "="*70)
    print("🚀 AFAQ AL NASEEM TACTICAL COMMAND V5.3-OMEGA-REF - ONLINE")
    print("="*70)
    print(f"📊 Manager Command Center: http://{local_ip}:6789/admin")
    print(f"👥 Employee Terminal: http://{local_ip}:3456/")
    print("="*70)
    
    # webbrowser.open(f'http://127.0.0.1:6789/admin')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⚠️  System shutdown initiated...")
        logger.info("System shutdown")
