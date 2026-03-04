import os
from fastembed import TextEmbedding
from database.vector_db import get_pinecone_index
from groq import AsyncGroq

print("--> [SYSTEM] Loading FastEmbed for search queries...")
embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

async def generate_answer(customer_id: str, user_question: str, history: list):
    
    # --- 1. THE REFORMULATOR (Solving the context logic) ---
    search_query = user_question
    
    # Only reformulate if there is an actual conversation history to look back on
    if len(history) > 0:
        reformulate_prompt = (
            "You are an AI query extractor. Your ONLY job is to rewrite the user's latest question "
            "into a standalone search query using the conversation history. "
            "If the question contains pronouns (he, she, it) or refers to past context, replace them with the actual names. "
            "If the question is small talk (e.g., 'hello', 'my day is good'), output exactly: SKIP_SEARCH. "
            "Do NOT answer the question. ONLY output the rewritten query."
        )
        
        # We only need the last ~4 messages to figure out pronouns
        reformulate_msgs = [{"role": "system", "content": reformulate_prompt}]
        for msg in history[-4:]:
            reformulate_msgs.append(msg)
        reformulate_msgs.append({"role": "user", "content": user_question})
        
        try:
            rewrite_completion = await groq_client.chat.completions.create(
                messages=reformulate_msgs,
                model="llama-3.1-8b-instant",
                temperature=0.0, # 0.0 means zero creativity, just literal extraction
                max_tokens=40
            )
            rewritten_text = rewrite_completion.choices[0].message.content.strip()
            
            # If it's small talk, we won't waste time searching the DB
            if rewritten_text != "SKIP_SEARCH":
                search_query = rewritten_text
                
        except Exception as e:
            print(f"--> [DEBUG] Reformulator skipped due to error: {e}")

    print(f"--> [DEBUG] Original: '{user_question}' | Pinecone Search: '{search_query}'")
    
    # --- 2. VECTOR SEARCH ---
    retrieved_chunks = []
    if search_query != "SKIP_SEARCH":
        query_generator = embedding_model.embed([search_query])
        query_embedding = list(query_generator)[0].tolist()

        index = get_pinecone_index()
        search_results = index.query(
            namespace=customer_id,
            vector=query_embedding,
            top_k=5, 
            include_metadata=True
        )

        for match in search_results['matches']:
            if 'metadata' in match and 'text' in match['metadata']:
                retrieved_chunks.append(match['metadata']['text'])

    if not retrieved_chunks:
        context_text = "No direct information found in the database. Rely on Chit-Chat rules."
    else:
        context_text = "\n\n---\n\n".join(retrieved_chunks)

    # --- 3. FINAL GENERATION ---
    system_prompt = (
        "You are an intelligent, friendly AI assistant. Follow these rules strictly:\n"
        "1. If the user is making small talk, respond politely without checking the knowledge base.\n"
        "2. For factual questions, answer using ONLY the provided Knowledge Base Context.\n"
        "3. If the user asks a factual question and the answer is NOT in the context, say exactly: 'That information is not in the knowledge base.'"
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append(msg)
        
    user_prompt = f"Knowledge Base Context:\n{context_text}\n\nNew User Question: {user_question}"
    messages.append({"role": "user", "content": user_prompt})
    
    try:
        chat_completion = await groq_client.chat.completions.create(
            messages=messages,
            model="llama-3.1-8b-instant", 
            temperature=0.2, 
        )

        return {
            "answer": chat_completion.choices[0].message.content,
            "sources_used": len(retrieved_chunks)
        }
    except Exception as e:
        raise e