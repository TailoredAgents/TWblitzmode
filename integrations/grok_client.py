"""
Grok API Client for multi-model reasoning and development assistance
"""

import os
import asyncio
import json
from typing import Dict, Any, Optional, List
import httpx
from datetime import datetime

try:
    from api.mt_db import get_db
    from api.security import dec
except ImportError:
    from .api.mt_db import get_db
    from .api.security import dec

import logging
logger = logging.getLogger(__name__)

class GrokClient:
    """Client for xAI Grok API integration"""
    
    def __init__(self, api_key: str, tenant_id: Optional[int] = None):
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.base_url = "https://api.x.ai/v1"
        self.model = "grok-beta"  # xAI's Grok model
        
        # Session configuration
        self.timeout = httpx.Timeout(60.0)
        self.session = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.aclose()
            
    async def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Send chat completion request to Grok"""
        if not self.session:
            raise RuntimeError("GrokClient must be used as async context manager")
            
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        try:
            response = await self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload
            )
            response.raise_for_status()
            return response.json()
            
        except httpx.RequestError as e:
            logger.error(f"Grok API request failed: {e}")
            raise Exception(f"Grok API request failed: {str(e)}")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Grok API HTTP error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Grok API error: {e.response.status_code}")
    
    async def get_development_advice(
        self, 
        context: str, 
        question: str,
        code_snippet: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get development advice from Grok for specific coding questions"""
        
        system_prompt = """You are Grok, an advanced AI assistant specialized in software development and architecture. 
        Provide detailed, practical advice for development questions. Focus on:
        1. Best practices and industry standards
        2. Specific implementation guidance
        3. Potential pitfalls and how to avoid them
        4. Alternative approaches when appropriate
        5. Code examples when helpful
        
        Be direct, actionable, and technically precise."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"}
        ]
        
        if code_snippet:
            messages.append({
                "role": "user", 
                "content": f"Relevant code:\n```\n{code_snippet}\n```"
            })
        
        try:
            response = await self.chat_completion(
                messages=messages,
                temperature=0.3,  # Lower temperature for technical accuracy
                max_tokens=1500
            )
            
            if response and "choices" in response and response["choices"]:
                advice = response["choices"][0]["message"]["content"]
                
                return {
                    "advice": advice,
                    "model": self.model,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "context": context,
                    "question": question,
                    "usage": response.get("usage", {})
                }
            else:
                raise Exception("Invalid response from Grok API")
                
        except Exception as e:
            logger.error(f"Grok development advice failed: {e}")
            raise
    
    async def analyze_architecture(
        self,
        description: str,
        current_stack: List[str],
        requirements: List[str]
    ) -> Dict[str, Any]:
        """Get architectural analysis and recommendations from Grok"""
        
        system_prompt = """You are Grok, an expert software architect. Analyze the provided architecture description and provide:
        1. Architectural strengths and weaknesses
        2. Scalability considerations  
        3. Security implications
        4. Performance bottlenecks
        5. Recommended improvements
        6. Alternative architectural patterns to consider
        
        Provide specific, actionable recommendations with reasoning."""
        
        context = f"""
        Architecture Description: {description}
        
        Current Technology Stack:
        {chr(10).join(f"- {tech}" for tech in current_stack)}
        
        Requirements:
        {chr(10).join(f"- {req}" for req in requirements)}
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context}
        ]
        
        try:
            response = await self.chat_completion(
                messages=messages,
                temperature=0.2,
                max_tokens=2000
            )
            
            if response and "choices" in response and response["choices"]:
                analysis = response["choices"][0]["message"]["content"]
                
                return {
                    "analysis": analysis,
                    "model": self.model,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "architecture_description": description,
                    "stack": current_stack,
                    "requirements": requirements,
                    "usage": response.get("usage", {})
                }
            else:
                raise Exception("Invalid response from Grok API")
                
        except Exception as e:
            logger.error(f"Grok architecture analysis failed: {e}")
            raise
    
    async def debug_assistance(
        self,
        error_message: str,
        stack_trace: Optional[str] = None,
        code_context: Optional[str] = None,
        environment: str = "python"
    ) -> Dict[str, Any]:
        """Get debugging assistance from Grok for specific errors"""
        
        system_prompt = f"""You are Grok, an expert debugger and troubleshooter for {environment} applications.
        Analyze the provided error and help debug it by:
        1. Explaining what the error means in plain language
        2. Identifying the most likely root causes
        3. Providing step-by-step debugging approach
        4. Suggesting specific fixes with code examples
        5. Recommending preventive measures
        
        Be thorough but practical in your debugging advice."""
        
        context_parts = [f"Error: {error_message}"]
        
        if stack_trace:
            context_parts.append(f"Stack Trace:\n{stack_trace}")
            
        if code_context:
            context_parts.append(f"Code Context:\n```{environment}\n{code_context}\n```")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(context_parts)}
        ]
        
        try:
            response = await self.chat_completion(
                messages=messages,
                temperature=0.1,  # Very low temperature for debugging accuracy
                max_tokens=1800
            )
            
            if response and "choices" in response and response["choices"]:
                debugging_help = response["choices"][0]["message"]["content"]
                
                return {
                    "debugging_help": debugging_help,
                    "model": self.model,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "error_message": error_message,
                    "environment": environment,
                    "usage": response.get("usage", {})
                }
            else:
                raise Exception("Invalid response from Grok API")
                
        except Exception as e:
            logger.error(f"Grok debugging assistance failed: {e}")
            raise

def get_tenant_grok_settings(tenant_id: int) -> Dict[str, Any]:
    """Get Grok integration settings for a tenant"""
    conn = get_db()
    try:
        cursor = conn.execute("""
            SELECT setting_key, setting_value, encrypted
            FROM tenant_settings
            WHERE tenant_id = ? AND setting_key LIKE 'grok_%'
        """, (tenant_id,))
        
        settings = {}
        for row in cursor.fetchall():
            key = row["setting_key"]
            value = row["setting_value"]
            if row["encrypted"] and value:
                try:
                    value = dec(value)
                except Exception as e:
                    logger.warning(f"Failed to decrypt Grok setting {key}: {e}")
                    value = ""
            settings[key] = value
            
        return settings
        
    except Exception as e:
        logger.error(f"Error fetching Grok settings for tenant {tenant_id}: {e}")
        return {}
    finally:
        conn.close()

async def get_grok_client(tenant_id: int) -> Optional[GrokClient]:
    """Get configured Grok client for tenant"""
    settings = get_tenant_grok_settings(tenant_id)
    
    api_key = settings.get("grok_api_key")
    if not api_key:
        logger.warning(f"No Grok API key configured for tenant {tenant_id}")
        return None
    
    return GrokClient(api_key=api_key, tenant_id=tenant_id)