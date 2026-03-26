
import os
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class WhatsAppHandler:
    """
    Headless WhatsApp webhook for customer service automation.
    Integrates with self-hosted Node.js bridge.
    """
    
    def __init__(self, db_manager, ai_engine):
        self.bridge_url = os.environ.get('WHATSAPP_BRIDGE_URL', 'http://127.0.0.1:3457')
        self.db_manager = db_manager
        self.ai_engine = ai_engine
    
    def process_webhook(self, data: Dict) -> Dict[str, Any]:
        """
        Process incoming WhatsApp webhook from the bridge.
        """
        sender = data.get('from', 'unknown')
        message_body = data.get('body', '')
        
        self.db_manager.insert_whatsapp_log(sender, message_body, 'inbound')
        
        response_text = self._generate_response(message_body)
        
        self.send_message(sender, response_text)
        
        return {
            'success': True,
            'response': response_text
        }
    
    def _generate_response(self, message: str) -> str:
        """Generate AI-powered response to customer message"""
        product_context = {
            'store': 'Afaq Al Naseem Trading LLC',
            'categories': ['Hair Tools', 'Salon Equipment', 'Professional Products'],
            'shipping': 'UAE-wide delivery available',
            'payment': 'Cash on Delivery, Card, Bank Transfer'
        }
        
        system_prompt = """
You are Veridian Junior, Customer Service AI for Afaq Alnaseem Trading LLC.
Respond to customer WhatsApp inquiries professionally and helpfully.
Use provided product context to give accurate information.
Keep responses concise (under 200 characters for WhatsApp).
Include emojis for friendliness.
Language: English (can switch to Arabic if customer uses Arabic)
"""
        user_message = f"""
Product Context: {json.dumps(product_context)}
Customer Message: {message}

Generate appropriate customer service response.
"""
        
        response = self.ai_engine.call_deepseek(system_prompt, user_message, max_tokens=300)
        return response
    
    def send_message(self, recipient: str, message: str):
        """Send WhatsApp message via the Node.js bridge"""
        if not self.bridge_url:
            logger.warning("WhatsApp bridge URL not configured")
            return
        
        try:
            payload = {
                'to': recipient,
                'text': message
            }
            requests.post(f"{self.bridge_url}/api/send", json=payload, timeout=10)
            logger.info(f"WhatsApp message sent to {recipient}")
            self.db_manager.insert_whatsapp_log(recipient, message, 'outbound')
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")
