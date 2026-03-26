
import os
import requests
import json
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class IntelligenceEngine:
    """
    Core AI engine using DeepSeek and Gemini with search grounding.
    Named "Veridian Junior" for internal operations.
    """
    
    def __init__(self):
        self.deepseek_api_key = os.environ.get('DEEPSEEK_API_KEY')
        self.gemini_api_key = os.environ.get('GEMINI_API_KEY')
        self.deepseek_model = os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
        self.gemini_model = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash')
        self.deepseek_api_url = 'https://api.deepseek.com/v1/chat/completions'
        self.gemini_api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"

    def call_deepseek(self, system_prompt: str, user_message: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """
        Call DeepSeek API.
        """
        if not self.deepseek_api_key:
            logger.error("DeepSeek API key missing")
            return "Error: DeepSeek API key not configured"
        
        headers = {
            'Authorization': f'Bearer {self.deepseek_api_key}',
            'Content-Type': 'application/json'
        }
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        payload = {
            'model': self.deepseek_model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens
        }
        
        try:
            response = requests.post(self.deepseek_api_url, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            result = response.json()
            
            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                logger.info(f"DeepSeek Response generated ({len(content)} chars)")
                return content
            
            return "Error: No response from DeepSeek"
            
        except requests.exceptions.Timeout:
            logger.error("DeepSeek API timeout")
            return "Error: AI service timeout - please retry"
        except Exception as e:
            logger.error(f"DeepSeek API error: {str(e)}")
            return f"Error: {str(e)}"

    def call_gemini_vision(self, prompt: str, image_base64: str) -> str:
        """
        Call Gemini Vision API for OCR.
        """
        if not self.gemini_api_key:
            logger.error("Gemini API key missing")
            return "Error: Gemini API key not configured"

        url = f"{self.gemini_api_url}?key={self.gemini_api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64
                            }
                        }
                    ]
                }
            ]
        }
        
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            
            if 'candidates' in result and len(result['candidates']) > 0:
                content = result['candidates'][0]['content']['parts'][0]['text']
                logger.info(f"Gemini Vision Response generated ({len(content)} chars)")
                return content

            return "Error: No response from Gemini Vision"
        except Exception as e:
            logger.error(f"Gemini Vision API error: {str(e)}")
            return f"Error: {str(e)}"
    
    def generate_directive_sop(self, objective: str, assignee: str, 
                                intel_recon: bool = False) -> Dict[str, Any]:
        """
        Generate military-style SOP with optional market intelligence.
        """
        system_prompt = """
You are Veridian Junior, Tactical Operations AI for Afaq Al Naseem Trading LLC.
Your role is to convert raw objectives into military-grade Standard Operating Procedures.

OUTPUT FORMAT (STRICT JSON ONLY - NO MARKDOWN):
{
    "execution_steps": ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"],
    "mission_window_minutes": 45,
    "priority": "Gold Line|Silver Line|Overflow",
    "intel_recon": "Market intelligence summary if search was performed",
    "required_tools": ["Tool 1", "Tool 2"],
    "success_criteria": "How to measure mission completion",
    "situation": "Why this matters / business context"
}

TONE: Professional, direct, actionable
CONTEXT: Dubai/UAE e-commerce environment
BRAND: Afaq Alnaseem Trading LLC
PRIORITY GUIDELINES:
- Gold Line: Revenue-critical, time-sensitive
- Silver Line: Important but flexible timing
- Overflow: Low priority, fill-time tasks
"""
        
        user_message = f"""
Assignee: {assignee}
Objective: {objective}

Generate a complete tactical directive with all required fields.
Focus on sales improvement and productivity enhancement.
"""
        
        response = self.call_deepseek(system_prompt, user_message)
        
        try:
            clean_response = re.sub(r'```json|```', '', response).strip()
            parsed = json.loads(clean_response)
            
            required = ['execution_steps', 'mission_window_minutes']
            for field in required:
                if field not in parsed:
                    parsed[field] = [] if field == 'execution_steps' else 45
            
            return parsed
            
        except Exception as e:
            logger.error(f"SOP parsing error: {e}")
            return {
                'execution_steps': ['Review objective requirements', 'Execute primary action', 
                                   'Document results', 'Submit proof of completion', 
                                   'Report to commander'],
                'mission_window_minutes': 45,
                'priority': 'Silver Line',
                'intel_recon': 'Standard procedure - no recon performed',
                'required_tools': ['Computer', 'Internet', 'Phone'],
                'success_criteria': 'Objective completed per instructions with proof',
                'situation': 'Critical for operational efficiency and sales targets'
            }
