"""
OpenAI GPT-4o Email Generation Client
Production-ready AI-powered message generation with A/B testing
"""

import openai
import json
import logging
import hashlib
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import asyncio

from core.settings import settings
from services.error_classifier import error_classifier
from api.mt_db import get_db

logger = logging.getLogger(__name__)

class MessageType(Enum):
    WARM_INTRO = "warm_intro"
    FOLLOW_UP = "follow_up"
    DIRECT_OUTREACH = "direct_outreach"
    REFERRAL_REQUEST = "referral_request"
    THANK_YOU = "thank_you"
    RE_ENGAGEMENT = "re_engagement"
    CUSTOM = "custom"

@dataclass
class GeneratedMessage:
    subject: str
    body: str
    preview_text: Optional[str] = None
    tone: str = "professional"
    word_count: int = 0
    personalization_score: float = 0.0
    variant_id: Optional[str] = None
    generation_time_ms: int = 0
    tokens_used: int = 0
    cost: float = 0.0
    
    @property
    def message(self) -> str:
        """Alias for body for backward compatibility with routes_email.py"""
        return self.body

class OpenAIEmailClient:
    """
    OpenAI client for email generation
    Uses supported GPT-4.1/4o models optimized for professional B2B communication
    """
    
    # Pricing per 1K tokens (approximate; update as needed)
    MODEL_PRICING = {
        "gpt-4.1": {"input": 0.005, "output": 0.015},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.001, "output": 0.003},
    }
    INPUT_COST_PER_1K = 0.005
    OUTPUT_COST_PER_1K = 0.015
    
    def __init__(self, api_key: Optional[str] = None, tenant_id: Optional[int] = None):
        logger.info(f"🔍 [OPENAI DEBUG] Initializing OpenAI client for tenant_id: {tenant_id}")
        logger.info(f"🔍 [OPENAI DEBUG] Provided api_key length: {len(api_key) if api_key else 0}")
        
        self.tenant_id = tenant_id
        self.api_key = api_key or self._get_api_key_for_tenant(tenant_id)
        
        logger.info(f"🔍 [OPENAI DEBUG] Final API key: {self.api_key[:20]}...{self.api_key[-10:] if len(self.api_key) > 30 else self.api_key}")
        logger.info(f"🔍 [OPENAI DEBUG] API key length: {len(self.api_key)}")
        logger.info(f"🔍 [OPENAI DEBUG] API key starts with 'sk-': {self.api_key.startswith('sk-')}")
        
        if not self.api_key or len(self.api_key) < 20:
            logger.error(f"❌ [OPENAI DEBUG] Invalid or missing API key: '{self.api_key}'")
            raise ValueError("OpenAI API key is missing or invalid")
        
        try:
            self.client = openai.OpenAI(api_key=self.api_key)
            logger.info(f"✅ [OPENAI DEBUG] OpenAI client created successfully")
        except Exception as e:
            logger.error(f"❌ [OPENAI DEBUG] Failed to create OpenAI client: {e}")
            raise
        
        # Model configuration
        # Use supported models per repo guidelines: default to gpt-4.1
        self.model = "gpt-4.1"
        self.max_retries = 3
        
        # Cost tracking
        self.total_tokens_used = 0
        self.total_cost = 0.0
        
        # Cache for similar requests
        self.cache = {}
        self.cache_ttl = 3600  # 1 hour
    
    def _get_api_key_for_tenant(self, tenant_id: Optional[int]) -> str:
        """Get tenant-specific OpenAI API key"""
        logger.info(f"🔍 [OPENAI DEBUG] Getting API key for tenant_id: {tenant_id}")
        
        if not tenant_id:
            import os
            env_key = os.getenv('OPENAI_API_KEY', '')
            logger.info(f"🔍 [OPENAI DEBUG] No tenant_id, using environment OPENAI_API_KEY: {env_key[:20] if env_key else 'NOT SET'}...")
            return env_key
        
        try:
            from integrations.apify_client import get_tenant_integration_settings
            logger.info(f"🔍 [OPENAI DEBUG] Fetching tenant integration settings for tenant {tenant_id}")
            settings = get_tenant_integration_settings(tenant_id)
            logger.info(f"🔍 [OPENAI DEBUG] Retrieved {len(settings)} tenant settings: {list(settings.keys())}")
            
            tenant_key = settings.get('openai_api_key', '')
            logger.info(f"🔍 [OPENAI DEBUG] Tenant OpenAI key: {tenant_key[:20] if tenant_key else 'NOT SET'}...")
            
            if not tenant_key:
                import os
                fallback_key = os.getenv('OPENAI_API_KEY', '')
                logger.info(f"🔍 [OPENAI DEBUG] No tenant key, falling back to environment: {fallback_key[:20] if fallback_key else 'NOT SET'}...")
                return fallback_key
            
            return tenant_key
        except Exception as e:
            logger.error(f"❌ [OPENAI DEBUG] Error getting tenant settings: {e}")
            import os
            fallback_key = os.getenv('OPENAI_API_KEY', '')
            logger.info(f"🔍 [OPENAI DEBUG] Exception fallback to environment: {fallback_key[:20] if fallback_key else 'NOT SET'}...")
            return fallback_key
    
    @classmethod
    async def create(cls, api_key: Optional[str] = None, tenant_id: Optional[int] = None):
        """Create OpenAI client instance (async factory method for compatibility)"""
        return cls(api_key=api_key, tenant_id=tenant_id)
    
    def generate_introduction_email(
        self,
        introducer: Dict,
        prospect: Dict,
        message_type: str = "warm_intro",
        context: Optional[Dict] = None
    ) -> GeneratedMessage:
        """
        Synchronous wrapper for generate_email for backward compatibility
        """
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.generate_email(
                introducer=introducer,
                prospect=prospect,
                message_type=message_type,
                context=context
            ))
        finally:
            loop.close()
    
    def _get_cache_key(self, introducer: Dict, prospect: Dict, message_type: str) -> str:
        """Generate cache key for deduplication"""
        key_data = f"{introducer.get('id')}_{prospect.get('id')}_{message_type}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _check_cache(self, cache_key: str) -> Optional[GeneratedMessage]:
        """Check if we have a cached response"""
        if cache_key in self.cache:
            cached_item = self.cache[cache_key]
            if datetime.now() - cached_item['timestamp'] < timedelta(seconds=self.cache_ttl):
                return cached_item['message']
        return None
    
    def _update_cache(self, cache_key: str, message: GeneratedMessage):
        """Update cache with new message"""
        self.cache[cache_key] = {
            'message': message,
            'timestamp': datetime.now()
        }
    
    def _track_usage(self, tokens: int, cost: float):
        """Track token usage and costs"""
        self.total_tokens_used += tokens
        self.total_cost += cost
        
        if self.tenant_id:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO email_costs (tenant_id, date, service, operation, count, unit_cost, total_cost)
                VALUES (%s, %s, 'openai', 'generation', %s, %s, %s)
                ON CONFLICT (tenant_id, date, service, operation)
                DO UPDATE SET 
                    count = email_costs.count + EXCLUDED.count,
                    total_cost = email_costs.total_cost + EXCLUDED.total_cost
            """, (
                self.tenant_id,
                datetime.now().date(),
                tokens,
                cost / tokens if tokens > 0 else 0,
                cost
            ))
            
            conn.commit()
            conn.close()
    
    def _get_system_prompt(self, message_type: MessageType) -> str:
        """Get optimized system prompt for message type"""
        base_prompt = """You are an expert B2B communication specialist creating personalized introduction requests.
Your messages should be:
- Concise (under 150 words)
- Professional yet friendly
- Focused on mutual value
- Action-oriented with clear next steps

IMPORTANT: Return your response as valid JSON format with 'subject', 'body', and 'preview_text' keys."""
        
        type_specific = {
            MessageType.WARM_INTRO: """
Focus on the mutual connection and shared interests.
Emphasize the value of the introduction for both parties.
Keep the ask light and easy to say yes to.""",
            
            MessageType.FOLLOW_UP: """
Reference the previous message politely.
Add new value or information.
Maintain persistence without being pushy.""",
            
            MessageType.DIRECT_OUTREACH: """
Lead with value and relevance.
Establish credibility quickly.
Make the ask specific and actionable.""",
            
            MessageType.REFERRAL_REQUEST: """
Highlight the existing relationship.
Explain why this specific person can help.
Offer to reciprocate or provide value.""",
            
            MessageType.THANK_YOU: """
Be specific about what you're thanking them for.
Share the positive outcome if applicable.
Keep the door open for future interaction.""",
            
            MessageType.RE_ENGAGEMENT: """
Reference the previous interaction naturally.
Provide a compelling reason to reconnect.
Make it easy to respond."""
        }
        
        return base_prompt + "\n\n" + type_specific.get(message_type, "")
    
    def _build_user_prompt(
        self,
        introducer: Dict,
        prospect: Dict,
        context: Dict,
        message_type: MessageType
    ) -> str:
        """Build detailed user prompt with context"""
        
        # Extract key information
        introducer_name = introducer.get('full_name', 'there')
        introducer_first = introducer_name.split()[0] if introducer_name != 'there' else 'there'
        prospect_name = prospect.get('full_name', 'your connection')
        prospect_company = prospect.get('company', 'their company')
        prospect_title = prospect.get('title', prospect.get('headline', ''))
        
        # Get sender info
        sender_name = context.get('sender_name', 'I')
        sender_company = context.get('sender_company', 'our company')
        value_prop = context.get('value_proposition', 'exploring potential synergies')
        
        # Build the prompt
        prompt = f"""Generate a {message_type.value.replace('_', ' ')} email.

Sender: {sender_name} from {sender_company}
Recipient: {introducer_name} ({introducer.get('title', '')} at {introducer.get('company', '')})
Requesting introduction to: {prospect_name} ({prospect_title} at {prospect_company})

Context:
- Mutual connection strength: {context.get('connection_strength', 'professional')}
- Relationship: {context.get('relationship_context', 'connected on LinkedIn')}
- Value proposition: {value_prop}
- Industry: {context.get('industry', 'technology')}

Additional notes:
{context.get('additional_notes', 'Focus on mutual benefit and keep it concise.')}

Generate a personalized email that feels natural and compelling."""
        
        return prompt
    
    def _build_custom_user_prompt(self, introducer: Dict, prospect: Dict, context: Dict, custom_prompt: str) -> str:
        """Build user prompt using custom user-provided prompt"""
        logger.info(f"🎨 [CUSTOM PROMPT BUILD DEBUG] Building custom user prompt")
        
        # Prepare context variables that users can reference in their custom prompts
        prospect_name = prospect.get('full_name', 'the prospect')
        prospect_company = prospect.get('company', '')
        connector_name = introducer.get('full_name', 'your connection')
        connector_title = introducer.get('title', '')
        connector_company = introducer.get('company', '')
        
        logger.info(f"🎨 [CUSTOM PROMPT BUILD DEBUG] Context variables extracted:")
        logger.info(f"   - prospect_name: '{prospect_name}'")
        logger.info(f"   - prospect_company: '{prospect_company}'")
        logger.info(f"   - connector_name: '{connector_name}'")
        logger.info(f"   - connector_title: '{connector_title}'")
        logger.info(f"   - connector_company: '{connector_company}'")
        
        # Analyze if we have sufficient context
        context_completeness = {
            'has_prospect_name': bool(prospect_name and prospect_name != 'the prospect'),
            'has_prospect_company': bool(prospect_company),
            'has_connector_name': bool(connector_name and connector_name != 'your connection'),
            'has_connector_title': bool(connector_title),
            'has_connector_company': bool(connector_company),
        }
        
        logger.info(f"🎨 [CUSTOM PROMPT BUILD DEBUG] Context completeness analysis:")
        for key, value in context_completeness.items():
            logger.info(f"   - {key}: {value}")
        
        context_score = sum(context_completeness.values()) / len(context_completeness)
        logger.info(f"🎨 [CUSTOM PROMPT BUILD DEBUG] Context completeness score: {context_score:.2f} ({context_score*100:.0f}%)")
        
        if context_score < 0.6:
            logger.warning(f"⚠️ [CUSTOM PROMPT BUILD DEBUG] Low context completeness - may affect message quality")
        
        # Build context information
        context_info = f"""
PROSPECT DETAILS:
- Name: {prospect_name}
- Company: {prospect_company if prospect_company else 'Not specified'}

CONNECTOR/INTRODUCER DETAILS:  
- Name: {connector_name}
- Title: {connector_title if connector_title else 'Not specified'}
- Company: {connector_company if connector_company else 'Not specified'}

CUSTOM INSTRUCTIONS:
{custom_prompt}

Please generate a professional, personalized message based on the above information and custom instructions. Make it sound natural, engaging, and appropriate for business communication. Format your response as JSON with 'subject', 'body', and 'preview_text' keys."""
        
        logger.info(f"🎨 [CUSTOM PROMPT BUILD DEBUG] Final prompt constructed:")
        logger.info(f"   - Total length: {len(context_info)} characters")
        logger.info(f"   - Lines: {context_info.count(chr(10)) + 1}")
        logger.info(f"   - Custom instruction placement: Lines {context_info.find('CUSTOM INSTRUCTIONS:')//50 + 1}")
        
        return context_info
    
    async def generate_email(
        self,
        introducer: Dict,
        prospect: Dict,
        message_type: str = "warm_intro",
        context: Optional[Dict] = None,
        temperature: float = 1.0,
        max_completion_tokens: int = 500,
        custom_prompt: Optional[str] = None
    ) -> GeneratedMessage:
        """
        Generate personalized email using GPT-4o
        """
        start_time = datetime.now()
        
        # Check cache first
        cache_key = self._get_cache_key(introducer, prospect, message_type)
        cached = self._check_cache(cache_key)
        if cached:
            logger.info(f"Returning cached message for {cache_key}")
            return cached
        
        # Parse message type (only if not using custom prompt)
        if custom_prompt:
            # For custom prompts, we'll bypass MessageType validation
            msg_type = None
        else:
            msg_type = MessageType(message_type) if isinstance(message_type, str) else message_type
        
        # Prepare context
        if context is None:
            context = {}
        
        # Optional: reject clearly unsafe custom prompts (actual harmful content only)
        def _is_prompt_safe(text: str) -> bool:
            # Only block explicitly harmful content, not metaphorical expressions or business language
            unsafe_terms = [
                "commit suicide", "kill myself", "kill someone", "how to make bombs",
                "how to die", "end my life", "build explosives", "make explosives",
                "harm children", "hurt children", "illegal drug manufacturing",
                "how to commit crimes", "murder someone", "assassinate"
            ]
            tl = text.lower()
            
            # Allow common business/metaphorical expressions
            business_expressions = [
                "jump off a cliff", "kill it", "blow up", "crushing it", 
                "hit the target", "shoot for", "take a shot", "bomb"
            ]
            
            # Check if it's a business expression context
            for expr in business_expressions:
                if expr in tl:
                    # Allow if it's clearly business/metaphorical context
                    business_context = any(word in tl for word in [
                        "business", "market", "sales", "goal", "target", "success",
                        "growth", "strategy", "performance", "opportunity", "deal"
                    ])
                    if business_context or len(text) < 100:  # Short prompts are usually safe
                        return True
            
            # Block only explicitly harmful content
            return not any(term in tl for term in unsafe_terms)

        if custom_prompt and not _is_prompt_safe(custom_prompt):
            logger.warning("⚠️ [CUSTOM PROMPT SAFETY] Unsafe custom_prompt detected; ignoring and using standard prompt")
            custom_prompt = None
            message_type = message_type if message_type != "custom" else "warm_intro"

        # Get prompts with surgical debugging
        if custom_prompt:
            logger.info(f"🎨 [CUSTOM PROMPT OPENAI DEBUG] ===== CUSTOM PROMPT MODE ACTIVATED =====")
            logger.info(f"🎨 [CUSTOM PROMPT OPENAI DEBUG] Processing custom prompt request:")
            logger.info(f"   - Tenant ID: {self.tenant_id}")
            logger.info(f"   - Original message_type: {message_type}")
            logger.info(f"   - Custom prompt length: {len(custom_prompt)} chars")
            logger.info(f"   - Custom prompt preview: {custom_prompt[:200]}{'...' if len(custom_prompt) > 200 else ''}")
            
            # Analyze custom prompt content
            prompt_words = custom_prompt.lower().split()
            analysis = {
                'contains_write_instruction': any(word in prompt_words for word in ['write', 'generate', 'create', 'compose']),
                'contains_tone_instruction': any(word in prompt_words for word in ['friendly', 'professional', 'casual', 'formal', 'warm']),
                'contains_mention_instruction': any(word in prompt_words for word in ['mention', 'include', 'reference', 'talk about']),
                'contains_personal_details': any(word in prompt_words for word in ['university', 'college', 'company', 'mutual', 'connection']),
                'question_count': custom_prompt.count('?'),
                'exclamation_count': custom_prompt.count('!'),
                'sentence_count': len([s for s in custom_prompt.split('.') if s.strip()])
            }
            
            logger.info(f"🎨 [CUSTOM PROMPT OPENAI DEBUG] Content analysis:")
            for key, value in analysis.items():
                logger.info(f"   - {key}: {value}")
            
            # Use custom prompt provided by user - MUST include "json" for response_format
            system_prompt = "You are a professional business communication assistant. Generate personalized, engaging messages that sound natural and authentic. Return your response as valid JSON with 'subject', 'body', and 'preview_text' keys."
            user_prompt = self._build_custom_user_prompt(introducer, prospect, context, custom_prompt)
            
            logger.info(f"🎨 [CUSTOM PROMPT OPENAI DEBUG] Custom system prompt length: {len(system_prompt)} chars")
            logger.info(f"🎨 [CUSTOM PROMPT OPENAI DEBUG] Custom user prompt length: {len(user_prompt)} chars")
            logger.info(f"🎨 [CUSTOM PROMPT OPENAI DEBUG] User prompt preview: {user_prompt[:300]}{'...' if len(user_prompt) > 300 else ''}")
        else:
            logger.info(f"📝 [CUSTOM PROMPT OPENAI DEBUG] Using standard predefined prompts")
            logger.info(f"📝 [CUSTOM PROMPT OPENAI DEBUG] Message type: {message_type}")
            # Use standard predefined prompts
            system_prompt = self._get_system_prompt(msg_type)
            user_prompt = self._build_user_prompt(introducer, prospect, context, msg_type)
        
        try:
            # Log API call details
            logger.info(f"🔍 [OPENAI DEBUG] Making API call to OpenAI")
            logger.info(f"🔍 [OPENAI DEBUG] Model: {self.model}")
            logger.info(f"🔍 [OPENAI DEBUG] API key being used: {self.api_key[:20]}...{self.api_key[-10:] if len(self.api_key) > 30 else self.api_key}")
            logger.info(f"🔍 [OPENAI DEBUG] System prompt length: {len(system_prompt)} chars")
            logger.info(f"🔍 [OPENAI DEBUG] User prompt length: {len(user_prompt)} chars")
            logger.info(f"🔍 [OPENAI DEBUG] Temperature: {temperature}, Max completion tokens: {max_completion_tokens}")
            
            # Helper to invoke chat completion with a specific model
            async def _invoke(model_name: str):
                return await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                    response_format={"type": "json_object"}
                )

            # Try with primary + fallbacks
            models_to_try = []
            if self.model:
                models_to_try.append(self.model)
            for m in ["gpt-4.1", "gpt-4o-mini", "gpt-4o"]:
                if m not in models_to_try:
                    models_to_try.append(m)

            response = None
            used_model = None
            last_error: Optional[Exception] = None
            for m in models_to_try:
                try:
                    logger.info(f"🔍 [OPENAI DEBUG] Trying model: {m}")
                    response = await _invoke(m)
                    used_model = m
                    break
                except Exception as e:
                    logger.warning(f"⚠️ [OPENAI DEBUG] Model {m} failed: {e}")
                    last_error = e
                    continue
            if response is None:
                raise last_error or RuntimeError("All OpenAI model attempts failed")
            
            logger.info(f"✅ [OPENAI DEBUG] API call successful, processing response")
            
            # Additional debugging for custom prompt responses
            if custom_prompt:
                logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] ===== PROCESSING CUSTOM PROMPT RESPONSE =====")
                logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Response received for custom prompt")
                logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Response metadata:")
                logger.info(f"   - Model used: {response.model}")
                logger.info(f"   - Usage: {response.usage}")
                logger.info(f"   - Choices count: {len(response.choices)}")
                if response.choices:
                    choice = response.choices[0]
                    logger.info(f"   - Finish reason: {choice.finish_reason}")
                    logger.info(f"   - Expected: 'stop' for normal completion")
                    if choice.finish_reason != 'stop':
                        logger.warning(f"⚠️ [CUSTOM PROMPT RESPONSE DEBUG] Unusual finish reason - may indicate issue")
            
            # Parse response with robust error handling
            content = response.choices[0].message.content
            
            if not content or content.strip() == "":
                logger.error(f"❌ [OPENAI DEBUG] Empty response content from model {used_model}")
                logger.error(f"❌ [OPENAI DEBUG] Response object: {response}")
                logger.error(f"❌ [OPENAI DEBUG] Response choices: {response.choices}")
                if custom_prompt:
                    logger.error(f"❌ [CUSTOM PROMPT RESPONSE DEBUG] CRITICAL: Custom prompt resulted in empty response!")
                    logger.error(f"❌ [CUSTOM PROMPT RESPONSE DEBUG] Original custom prompt: {custom_prompt[:200]}...")
                    logger.error(f"❌ [CUSTOM PROMPT RESPONSE DEBUG] This may indicate a prompt formatting or content policy issue")
                # Try next fallback model if available
                raise ValueError(f"{used_model} returned empty content - possibly unsupported parameters or API issue")
            
            logger.info(f"🔍 [OPENAI DEBUG] Response content preview: {content[:200]}...")
            
            if custom_prompt:
                # Analyze the custom prompt response quality  
                content_lower = content.lower()
                custom_prompt_lower = custom_prompt.lower()
                
                logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Response quality analysis:")
                logger.info(f"   - Response length: {len(content)} characters")
                logger.info(f"   - Word count: {len(content.split())}")
                logger.info(f"   - Sentence count: {content.count('.') + content.count('!') + content.count('?')}")
                
                # Check if response addresses custom prompt requirements
                quality_indicators = {
                    'mentions_prospect': bool(prospect.get('full_name', '').lower() in content_lower) if prospect.get('full_name') else False,
                    'mentions_connector': bool(introducer.get('full_name', '').lower() in content_lower) if introducer.get('full_name') else False,
                    'references_company': bool(prospect.get('company', '').lower() in content_lower or introducer.get('company', '').lower() in content_lower),
                    'appropriate_json_format': content.strip().startswith('{') and content.strip().endswith('}'),
                    'contains_subject_and_body': '"subject"' in content_lower and '"body"' in content_lower,
                    'reasonable_length': 100 <= len(content) <= 2000
                }
                
                for key, value in quality_indicators.items():
                    status = "✅" if value else "❌"
                    logger.info(f"   {status} {key}: {value}")
                
                quality_score = sum(quality_indicators.values()) / len(quality_indicators)
                logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Overall quality score: {quality_score:.2f} ({quality_score*100:.0f}%)")
                
                if quality_score < 0.6:
                    logger.warning(f"⚠️ [CUSTOM PROMPT RESPONSE DEBUG] Low quality custom prompt response - may not meet user expectations")
            
            try:
                message_data = json.loads(content)
                if custom_prompt:
                    logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] JSON parsing successful for custom prompt")
                    logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Parsed data keys: {list(message_data.keys())}")
                    if 'subject' in message_data:
                        logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Subject: {message_data['subject'][:100]}...")
                    if 'body' in message_data:
                        logger.info(f"🎨 [CUSTOM PROMPT RESPONSE DEBUG] Body preview: {message_data['body'][:200]}...")
            except json.JSONDecodeError as e:
                logger.error(f"❌ [OPENAI DEBUG] JSON parse failed - Raw content: '{content}'")
                logger.error(f"❌ [OPENAI DEBUG] JSON error: {e}")
                if custom_prompt:
                    logger.error(f"❌ [CUSTOM PROMPT RESPONSE DEBUG] CRITICAL: JSON parsing failed for custom prompt response!")
                    logger.error(f"❌ [CUSTOM PROMPT RESPONSE DEBUG] This may indicate the custom prompt did not generate proper JSON format")
                    logger.error(f"❌ [CUSTOM PROMPT RESPONSE DEBUG] Raw response: {content[:500]}...")
                raise ValueError(f"Invalid JSON from {used_model}: {content[:100]}...")
            
            # Calculate costs
            tokens_used = response.usage.total_tokens
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            
            # Use per-model pricing if available
            pricing = self.MODEL_PRICING.get(used_model or self.model, {"input": self.INPUT_COST_PER_1K, "output": self.OUTPUT_COST_PER_1K})
            cost = (input_tokens * pricing["input"] / 1000) + (output_tokens * pricing["output"] / 1000)
            
            # Track usage
            self._track_usage(tokens_used, cost)
            
            # Calculate metrics
            generation_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            word_count = len(message_data.get('body', '').split())
            
            # Calculate personalization score (0-1)
            personalization_score = self._calculate_personalization_score(
                message_data.get('body', ''),
                introducer,
                prospect
            )
            
            # Create result
            result = GeneratedMessage(
                subject=message_data.get('subject', 'Introduction Request'),
                body=message_data.get('body', ''),
                preview_text=message_data.get('preview_text', ''),
                tone="professional",
                word_count=word_count,
                personalization_score=personalization_score,
                generation_time_ms=generation_time_ms,
                tokens_used=tokens_used,
                cost=cost
            )
            
            if custom_prompt:
                logger.info(f"🎨 [CUSTOM PROMPT FINAL DEBUG] ===== CUSTOM PROMPT GENERATION COMPLETE =====")
                logger.info(f"🎨 [CUSTOM PROMPT FINAL DEBUG] Final result summary:")
                logger.info(f"   - Subject length: {len(result.subject)} chars")
                logger.info(f"   - Body length: {len(result.body)} chars")
                logger.info(f"   - Word count: {result.word_count}")
                logger.info(f"   - Personalization score: {result.personalization_score:.2f}")
                logger.info(f"   - Generation time: {result.generation_time_ms}ms")
                logger.info(f"   - Tokens used: {result.tokens_used}")
                logger.info(f"   - Cost: ${result.cost:.4f}")
                logger.info(f"🎨 [CUSTOM PROMPT FINAL DEBUG] Subject: {result.subject}")
                logger.info(f"🎨 [CUSTOM PROMPT FINAL DEBUG] Body preview: {result.body[:300]}{'...' if len(result.body) > 300 else ''}")
                
                # Final quality check for custom prompt
                final_quality_check = {
                    'has_subject': bool(result.subject and result.subject.strip()),
                    'has_body': bool(result.body and result.body.strip()),
                    'reasonable_word_count': 20 <= result.word_count <= 300,
                    'good_personalization': result.personalization_score >= 0.3,
                    'completed_in_reasonable_time': result.generation_time_ms <= 30000,  # 30 seconds
                    'cost_reasonable': result.cost <= 0.50  # $0.50 limit
                }
                
                logger.info(f"🎨 [CUSTOM PROMPT FINAL DEBUG] Final quality assessment:")
                for key, value in final_quality_check.items():
                    status = "✅" if value else "❌"
                    logger.info(f"   {status} {key}: {value}")
                
                final_score = sum(final_quality_check.values()) / len(final_quality_check)
                logger.info(f"🎨 [CUSTOM PROMPT FINAL DEBUG] Final quality score: {final_score:.2f} ({final_score*100:.0f}%)")
                
                if final_score >= 0.8:
                    logger.info(f"🎉 [CUSTOM PROMPT FINAL DEBUG] Excellent custom prompt result!")
                elif final_score >= 0.6:
                    logger.info(f"✅ [CUSTOM PROMPT FINAL DEBUG] Good custom prompt result")
                else:
                    logger.warning(f"⚠️ [CUSTOM PROMPT FINAL DEBUG] Custom prompt result may not meet user expectations")
            
            # Cache the result
            self._update_cache(cache_key, result)
            
            # Record success
            if self.tenant_id:
                error_classifier.record_provider_success('openai', self.tenant_id)
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response: {e}")
            # Fallback to template
            return self._get_fallback_message(introducer, prospect, msg_type)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ [OPENAI DEBUG] OpenAI generation failed: {error_msg}")
            logger.error(f"❌ [OPENAI DEBUG] Exception type: {type(e).__name__}")
            
            # Check for specific error types
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                logger.error(f"❌ [OPENAI DEBUG] 401 UNAUTHORIZED ERROR DETECTED!")
                logger.error(f"❌ [OPENAI DEBUG] API key that failed: {self.api_key[:20]}...{self.api_key[-10:] if len(self.api_key) > 30 else self.api_key}")
                logger.error(f"❌ [OPENAI DEBUG] Tenant ID: {self.tenant_id}")
                logger.error(f"❌ [OPENAI DEBUG] API key format check:")
                logger.error(f"❌ [OPENAI DEBUG] - Starts with 'sk-': {self.api_key.startswith('sk-')}")
                logger.error(f"❌ [OPENAI DEBUG] - Length: {len(self.api_key)}")
                logger.error(f"❌ [OPENAI DEBUG] - Contains 'proj': {'proj' in self.api_key}")
            elif "429" in error_msg or "rate_limit" in error_msg.lower():
                logger.error(f"❌ [OPENAI DEBUG] RATE LIMIT ERROR DETECTED!")
            elif "404" in error_msg:
                logger.error(f"❌ [OPENAI DEBUG] MODEL NOT FOUND ERROR - attempted models: {models_to_try}")
            
            # Import here to avoid circular imports
            import traceback
            logger.error(f"❌ [OPENAI DEBUG] Full traceback: {traceback.format_exc()}")
            
            if self.tenant_id:
                error_classifier.record_provider_error(
                    'openai', 'generation_failed', str(e), self.tenant_id
                )
            
            # Return fallback template
            return self._get_fallback_message(introducer, prospect, msg_type)
    
    def _calculate_personalization_score(
        self,
        body: str,
        introducer: Dict,
        prospect: Dict
    ) -> float:
        """Calculate how personalized the message is (0-1)"""
        score = 0.0
        body_lower = body.lower()
        
        # Check for name mentions
        if introducer.get('full_name', '').lower() in body_lower:
            score += 0.2
        if prospect.get('full_name', '').lower() in body_lower:
            score += 0.2
        
        # Check for company mentions
        if introducer.get('company', '').lower() in body_lower:
            score += 0.15
        if prospect.get('company', '').lower() in body_lower:
            score += 0.15
        
        # Check for role/title mentions
        if introducer.get('title', '').lower() in body_lower:
            score += 0.1
        if prospect.get('title', '').lower() in body_lower:
            score += 0.1
        
        # Check for industry-specific terms
        industry_terms = ['synergy', 'collaborate', 'partnership', 'opportunity']
        for term in industry_terms:
            if term in body_lower:
                score += 0.025
        
        return min(score, 1.0)
    
    def _get_fallback_message(
        self,
        introducer: Dict,
        prospect: Dict,
        message_type: MessageType
    ) -> GeneratedMessage:
        """Get fallback template message if AI generation fails"""
        
        templates = {
            MessageType.WARM_INTRO: {
                "subject": f"Introduction to {prospect.get('full_name', 'your connection')}?",
                "body": f"""Hi {introducer.get('full_name', 'there').split()[0]},

I hope this message finds you well. I noticed you're connected with {prospect.get('full_name', 'someone')} at {prospect.get('company', 'their company')}, and I was wondering if you might be open to making an introduction.

We're working on some exciting initiatives that could be valuable for their team, and I believe a conversation could be mutually beneficial.

Would you be comfortable making this introduction? I'm happy to provide more context if helpful.

Best regards,
[Your name]""",
                "preview_text": "Quick introduction request"
            },
            MessageType.FOLLOW_UP: {
                "subject": f"Following up - Introduction to {prospect.get('full_name', 'your connection')}",
                "body": f"""Hi {introducer.get('full_name', 'there').split()[0]},

I wanted to follow up on my previous message about connecting with {prospect.get('full_name', 'your connection')}.

I understand you're busy, so I'll keep this brief. If you're open to it, I'd still love an introduction. If not, no worries at all!

Thanks for considering,
[Your name]""",
                "preview_text": "Quick follow-up on introduction request"
            }
        }
        
        template = templates.get(
            message_type,
            templates[MessageType.WARM_INTRO]
        )
        
        return GeneratedMessage(
            subject=template["subject"],
            body=template["body"],
            preview_text=template["preview_text"],
            tone="professional",
            word_count=len(template["body"].split()),
            personalization_score=0.3  # Lower score for templates
        )
    
    async def generate_variants(
        self,
        introducer: Dict,
        prospect: Dict,
        message_type: str = "warm_intro",
        context: Optional[Dict] = None,
        num_variants: int = 3
    ) -> List[GeneratedMessage]:
        """
        Generate multiple variants for A/B testing
        """
        variants = []
        # Use normal temperature values for supported models
        temperatures = [0.7, 0.9, 1.0]
        
        for i in range(min(num_variants, 3)):
            variant = await self.generate_email(
                introducer=introducer,
                prospect=prospect,
                message_type=message_type,
                context=context,
                temperature=temperatures[i % len(temperatures)]
            )
            variant.variant_id = f"variant_{i+1}"
            variants.append(variant)
        
        return variants
    
    async def optimize_message(
        self,
        original_message: str,
        optimization_goal: str = "clarity"
    ) -> str:
        """
        Optimize an existing message for specific goals
        """
        optimization_prompts = {
            "clarity": "Make this message clearer and more concise while maintaining the key points:",
            "warmth": "Make this message warmer and more personable while staying professional:",
            "urgency": "Add appropriate urgency to this message without being pushy:",
            "brevity": "Shorten this message to under 100 words while keeping the essential information:"
        }
        
        prompt = optimization_prompts.get(optimization_goal, optimization_prompts["clarity"])
        
        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert email editor. Optimize the message as requested."},
                    {"role": "user", "content": f"{prompt}\n\n{original_message}"}
                ],
                temperature=0.7,
                max_completion_tokens=500
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Message optimization failed: {e}")
            return original_message  # Return original if optimization fails
    
    async def analyze_message(self, message: str) -> Dict:
        """
        Analyze a message for quality metrics
        """
        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Analyze this email and provide scores (0-10) for: clarity, professionalism, persuasiveness, and brevity. Return as JSON."
                    },
                    {"role": "user", "content": message}
                ],
                temperature=0.7,
                max_completion_tokens=200,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            logger.error(f"Message analysis failed: {e}")
            return {
                "clarity": 5,
                "professionalism": 5,
                "persuasiveness": 5,
                "brevity": 5
            }
    
    async def generate_introduction_message(
        self,
        prospect_name: str,
        prospect_company: str = "",
        connector_name: str = "",
        connector_title: str = "",
        connector_company: str = "",
        message_type: str = "warm_intro",
        channel: str = "email",
        custom_prompt: Optional[str] = None
    ) -> GeneratedMessage:
        """
        Generate introduction message with the expected signature from routes_email.py
        """
        # Convert parameters to the format expected by generate_email
        prospect = {
            'full_name': prospect_name,
            'company': prospect_company,
        }
        
        introducer = {
            'full_name': connector_name,
            'title': connector_title,
            'company': connector_company,
        }
        
        context = {
            'channel': channel,
            'sender_name': 'I',
            'value_proposition': 'exploring potential collaboration opportunities'
        }
        
        # Use the existing generate_email method
        return await self.generate_email(
            introducer=introducer,
            prospect=prospect,
            message_type=message_type,
            context=context,
            custom_prompt=custom_prompt
        )

    async def generate_linkedin_message(
        self,
        prospect: Dict,
        introducer: Dict,
        message_type: str = "direct_introduction",
        custom_context: Optional[str] = None
    ) -> str:
        """
        Generate LinkedIn message (300 character limit)
        """
        try:
            # LinkedIn message types system prompt
            system_prompt = """You are an expert LinkedIn messaging specialist creating concise introduction requests.

LinkedIn messages must be:
- Under 300 characters (strict limit)
- Professional yet personable
- Focused on mutual benefit
- Include clear call-to-action

Message types:
- direct_introduction: Direct request to connect prospect with sender
- warm_introduction: Leverage existing relationship for introduction  
- meeting_request: Request to facilitate a meeting between parties
- custom: Use provided context for personalized message

Return ONLY the message text, no JSON formatting."""
            
            # Build user prompt
            user_prompt = f"""Generate a {message_type.replace('_', ' ')} LinkedIn message.

From: You (the sender)
To: {introducer.get('name', 'Connection')} at {introducer.get('company', '')}
About: Introducing {prospect.get('name', 'Prospect')} from {prospect.get('company', '')}

Prospect details:
- Name: {prospect.get('name', 'Prospect')}
- Company: {prospect.get('company', 'their company')}
- Title: {prospect.get('title', prospect.get('headline', ''))}
- LinkedIn: {prospect.get('linkedin_url', '')}

Context: {custom_context or 'Professional networking introduction for mutual benefit'}

Generate a LinkedIn message under 300 characters that feels natural and compelling."""

            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_completion_tokens=150  # Keep response short
            )
            
            message = response.choices[0].message.content.strip()
            
            # Ensure character limit
            if len(message) > 300:
                # Truncate and add ellipsis if needed
                message = message[:297] + "..."
                
            # Track usage
            tokens_used = response.usage.total_tokens
            cost = (response.usage.prompt_tokens * self.INPUT_COST_PER_1K / 1000) + \
                   (response.usage.completion_tokens * self.OUTPUT_COST_PER_1K / 1000)
            
            self._track_usage(tokens_used, cost)
            
            return message
            
        except Exception as e:
            logger.error(f"LinkedIn message generation failed: {e}")
            
            # Fallback template
            prospect_name = prospect.get('name', 'your connection')
            introducer_name = introducer.get('name', 'there').split()[0]
            
            fallback = f"Hi {introducer_name}! Would you be open to connecting me with {prospect_name}? I think we could create some great synergy. Happy to provide more context if helpful. Thanks!"
            
            # Ensure fallback is under 300 chars
            if len(fallback) > 300:
                fallback = f"Hi {introducer_name}! Could you connect me with {prospect_name}? I believe we could create mutual value. Thanks!"
            
            return fallback

# Per-tenant client instances for thread safety
_openai_clients = {}
_client_lock = asyncio.Lock()

async def get_openai_client(tenant_id: Optional[int] = None) -> OpenAIEmailClient:
    """Get or create OpenAI client per tenant"""
    async with _client_lock:
        if tenant_id not in _openai_clients:
            _openai_clients[tenant_id] = OpenAIEmailClient(tenant_id=tenant_id)
        
        return _openai_clients[tenant_id]

async def get_openai_email_client(tenant_id: Optional[int] = None) -> OpenAIEmailClient:
    """Get OpenAI client for email generation (alias for backwards compatibility)"""
    return await get_openai_client(tenant_id)


OpenAIClient = OpenAIEmailClient
