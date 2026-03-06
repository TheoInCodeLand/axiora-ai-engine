# services/chat_service.py (Complete Rewrite)
import os
import json
from typing import List, Dict, Optional
from fastembed import TextEmbedding
from groq import AsyncGroq

from .conversation_state import ConversationContext, ConversationPhase
from .emotional_intelligence import EmotionalIntelligence
from .persona_engine import ConsultantPersona
from .flow_controller import FlowController
from database.vector_db import get_pinecone_index

class ConversationalAI:
    def __init__(self):
        self.embedding_model = TextEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        self.groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.flow_controller = FlowController()
        self.contexts: Dict[str, ConversationContext] = {}  # In-memory, use Redis in prod
    
    async def generate_response(
        self, 
        customer_id: str, 
        user_message: str, 
        history: List[Dict]
    ) -> Dict:
        """Main entry point for conversational response"""
        
        # Get or create conversation context
        context = self.contexts.get(customer_id, ConversationContext())
        self.contexts[customer_id] = context
        
        print(f"\n---------> [TURN {context.conversation_turns + 1}] Phase: {context.phase.name}")
        print(f"--------> Emotion: {context.user_emotion} | Urgency: {context.urgency_level}")
        
        # --- THE FIX: STEP 1 MUST BE RETRIEVAL ---
        # The AI needs to search the database BEFORE deciding how to reply
        knowledge = await self._retrieve_knowledge(customer_id, user_message, history)
        if knowledge:
            context.topic_confidence = knowledge[0]['score']
        else:
            context.topic_confidence = 0.0
            
        # --- STEP 2: FLOW CONTROLLER ---
        # Now pass the ACTUAL retrieved knowledge to the controller
        next_phase, clarification, meta = await self.flow_controller.determine_next_action(
            user_message, context, knowledge
        )
        
        # Step 3: Handle clarification requests
        if clarification and next_phase == ConversationPhase.CLARIFICATION:
            context.pending_clarification = clarification
            return {
                "answer": clarification,
                "phase": next_phase.name,
                "sources_used": 0,
                "confidence": 0.0,
                "emotion_detected": context.user_emotion,
                "rapport_score": context.rapport_score
            }
        
        # Step 4: Build dynamic prompt
        system_prompt = ConsultantPersona.build_system_prompt(
            emotion=context.user_emotion,
            urgency=context.urgency_level,
            phase=next_phase.name,
            rapport_score=context.rapport_score,
            user_preferences={}
        )
        
        # Step 5: Construct messages with context awareness
        messages = self._build_message_chain(
            system_prompt, history, user_message, knowledge, context, meta
        )
        
        # Step 6: Generate response with appropriate parameters
        response = await self._generate_with_parameters(messages, context)
        
        # Step 7: Post-process for natural flow
        final_answer = self._post_process_response(
            response, context, knowledge, meta
        )
        
        return {
            "answer": final_answer,
            "phase": next_phase.name,
            "sources_used": len(knowledge),
            "confidence": context.topic_confidence,
            "emotion_detected": context.user_emotion,
            "rapport_score": context.rapport_score
        }
    
    async def _retrieve_knowledge(
        self, 
        customer_id: str, 
        query: str, 
        history: List[Dict]
    ) -> List[Dict]:
        """Smart retrieval with query enhancement"""
        
        # Enhance query with context from history
        enhanced_query = await self._enhance_query(query, history)
        
        # Generate embedding
        query_embedding = list(self.embedding_model.embed([enhanced_query]))[0].tolist()
        
        # Search
        index = get_pinecone_index()
        results = index.query(
            namespace=customer_id,
            vector=query_embedding,
            top_k=5,
            include_metadata=True
        )
        
        # Filter and rank
        knowledge = []
        for match in results['matches']:
            if match['score'] > 0.45:  # Relevance threshold
                knowledge.append({
                    "text": match['metadata']['text'],
                    "source": match['metadata'].get('source_url', 'documentation'),
                    "score": match['score']
                })
        
        return knowledge
    
    async def _enhance_query(self, query: str, history: List[Dict]) -> str:
        """Add context from conversation history to improve retrieval"""
        
        if not history:
            return query
        
        # Check for pronouns that need resolution
        pronouns = ["it", "this", "that", "they", "them", "their"]
        if any(p in query.lower() for p in pronouns):
            # Get last user message for context
            last_user_msgs = [h['content'] for h in history if h['role'] == 'user'][-2:]
            context = " ".join(last_user_msgs)
            return f"{context} {query}"
        
        return query
    
    def _build_message_chain(
        self,
        system_prompt: str,
        history: List[Dict],
        current_message: str,
        knowledge: List[Dict],
        context: ConversationContext,
        meta: Dict
    ) -> List[Dict]:
        """Construct conversation-aware message chain"""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent history (last 6 turns for context window efficiency)
        recent_history = history[-12:] if len(history) > 12 else history
        for msg in recent_history:
            messages.append(msg)
        
        # Add knowledge context if available
        if knowledge:
            knowledge_text = self._format_knowledge(knowledge, context)
            messages.append({
                "role": "system", 
                "content": f"RELEVANT INFORMATION:\n{knowledge_text}\n\nUse this to answer, but speak naturally. Cite sources when specific."
            })
        
        # Add phase-specific instructions
        if meta.get("topic_shift"):
            messages.append({
                "role": "system",
                "content": f"Note: User is shifting from '{meta['previous_topic']}' to a new topic. Acknowledge the change smoothly."
            })
        
        if meta.get("alternative_approach"):
            messages.append({
                "role": "system",
                "content": "The previous solution didn't work. Acknowledge this, apologize for the inconvenience, and try a completely different approach."
            })
        
        # Finally, add user message
        messages.append({"role": "user", "content": current_message})
        
        return messages
    
    def _format_knowledge(self, knowledge: List[Dict], context: ConversationContext) -> str:
        """Format knowledge for LLM consumption based on urgency"""
        
        if context.urgency_level >= 4:
            # Urgent - just the facts
            return "\n\n".join([
                f"- {k['text'][:200]}..." for k in knowledge[:2]
            ])
        
        # Normal - full context with sources
        formatted = []
        for i, k in enumerate(knowledge, 1):
            formatted.append(f"[Source {i}] From {k['source']}:\n{k['text']}")
        
        return "\n\n---\n\n".join(formatted)
    
    async def _generate_with_parameters(
        self, 
        messages: List[Dict], 
        context: ConversationContext
    ) -> str:
        """Generate with emotion-appropriate parameters"""
        
        # --- THE FACTUAL LOCKDOWN ---
        # If the phase is SOLUTION_PRESENTATION, force temperature to 0.0 so it cannot invent facts
        if context.phase.name == "SOLUTION_PRESENTATION":
            temperature = 0.0
            max_tokens = 300
        elif context.user_emotion == "frustrated":
            temperature = 0.1  
            max_tokens = 150   
        elif context.user_emotion == "confused":
            temperature = 0.2  
            max_tokens = 300   
        elif context.phase.name == "GREETING":
            temperature = 0.5  
            max_tokens = 100
        else:
            temperature = 0.1  
            max_tokens = 250
        
        completion = await self.groq_client.chat.completions.create(
            messages=messages,
            model="llama-3.1-8b-instant",
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.9
        )
        
        return completion.choices[0].message.content
    
    def _post_process_response(
        self, 
        response: str, 
        context: ConversationContext,
        knowledge: List[Dict],
        meta: Dict
    ) -> str:
        """Add natural conversational elements"""
        
        # Remove robotic prefixes
        robotic_prefixes = [
            "As an AI assistant", "As a language model", "I am an AI",
            "Based on the provided context", "According to the information"
        ]
        for prefix in robotic_prefixes:
            if response.startswith(prefix):
                response = response[len(prefix):].strip()
                if response.startswith(","):
                    response = response[1:].strip()
        
        # Add natural variation to closing questions
        if "?" in response[-20:] and context.conversation_turns > 2:
            closings = [
                "Does that help?",
                "Is that what you were looking for?",
                "Let me know if you need any clarification!",
                "Feel free to ask if anything's unclear.",
                "How does that sound?"
            ]
            # Only replace if it's the generic "anything else"
            if "anything else" in response.lower()[-30:]:
                import random
                response = response[:response.rfind("?") + 1]  # Remove old closing
                response += " " + random.choice(closings)
        
        # Add source references naturally if not already present
        # if knowledge and not any("Source" in response or "http" in response for _ in [1]):
        #     if context.topic_confidence > 0.8:
        #         response += f"\n\nYou can find more details in our [documentation]({knowledge[0]['source']})."
        
        # return response.strip()
        if knowledge and not any("http" in response for _ in [1]):
            if context.topic_confidence > 0.4:
                # Get the best matching URL
                best_link = knowledge[0]['source']
                response += f"\n\nHere is the direct link to exactly what we just discussed: [View Details]({best_link})."
        
        return response.strip()

# Singleton instance
ai_engine = ConversationalAI()

async def generate_answer(customer_id: str, user_question: str, history: list):
    """Public interface"""
    return await ai_engine.generate_response(customer_id, user_question, history)