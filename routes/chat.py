from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.chat_service import generate_answer

router = APIRouter()

# --- THE FIX ---
# By setting history to a standard 'list', we bypass strict Pydantic validation
# and let the JSON array flow through natively, just like Express.
class ChatPayload(BaseModel):
    question: str
    customer_id: str = "demo_user_01"
    history: list = [] 

@router.post("/chat")
async def chat_endpoint(payload: ChatPayload):
    print("\n==================================================")
    print(f"🗣️ NEW CHAT REQUEST: {payload.question}")
    print(f"🧠 MEMORY: Received {len(payload.history)} previous messages")
    print("==================================================")
    
    try:
        # Since history is already a standard list of dictionaries, we pass it directly
        response = await generate_answer(payload.customer_id, payload.question, payload.history)
        
        print("==================================================\n")
        return response
    except Exception as e:
        print(f"--> [FATAL ERROR] Chat pipeline crashed: {e}")
        raise HTTPException(status_code=500, detail=str(e))