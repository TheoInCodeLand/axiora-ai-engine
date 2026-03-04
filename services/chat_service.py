import os
from dotenv import load_dotenv
from fastembed import TextEmbedding
from database.vector_db import get_pinecone_index
from groq import AsyncGroq

print("--> [SYSTEM] Initializing FastEmbed for search queries...")
embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

print("--> [SYSTEM] Initializing Groq Client...")

groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

async def generate_answer(customer_id: str, user_question: str, history: list):
    # --- 1. FIX RETRIEVAL AMNESIA ---
    # If there is history, combine the last message with the new question 
    # so FastEmbed knows who "he", "she", or "it" is.
    search_query = user_question
    if len(history) > 0:
        last_context = history[-1].get("content", "")
        # Take the last 50 characters of the previous message to add context without diluting the search
        search_query = f"{last_context[-50:]} {user_question}"
        
    print(f"--> [DEBUG] Searching Pinecone using contextual query: '{search_query}'")
    
    query_generator = embedding_model.embed([search_query])
    query_embedding = list(query_generator)[0].tolist()

    index = get_pinecone_index()
    search_results = index.query(
        namespace=customer_id,
        vector=query_embedding,
        top_k=5, 
        include_metadata=True
    )

    retrieved_chunks = []
    for match in search_results['matches']:
        if 'metadata' in match and 'text' in match['metadata']:
            retrieved_chunks.append(match['metadata']['text'])

    if not retrieved_chunks:
        context_text = "No direct information found in the database."
    else:
        context_text = "\n\n---\n\n".join(retrieved_chunks)
        print(f"--> [DEBUG] Retrieved {len(retrieved_chunks)} chunks from Pinecone.")

    # --- 2. FIX GENERATION AMNESIA ---
    system_prompt = (
        "You are an intelligent, helpful AI assistant. Answer the user's question using ONLY the provided context. "
        "If the answer is not in the context, say 'That information is not in the knowledge base.' "
        "You have access to the conversation history. Use it to understand context, but base your facts on the provided Knowledge Base Context."
    )
    
    # Start the message array with the system instructions
    messages = [{"role": "system", "content": system_prompt}]
    
    # Append the last 10 messages of the conversation to give the AI its memory
    # (We limit to 10 to keep responses blazing fast, though Llama 3.1 can handle much more)
    for msg in history[-10:]:
        messages.append(msg)
        
    # Finally, append the brand new question and the Pinecone data
    user_prompt = f"Knowledge Base Context:\n{context_text}\n\nNew User Question: {user_question}"
    messages.append({"role": "user", "content": user_prompt})

    print("--> [DEBUG] Sending memory, context, and question to Groq (Llama-3.1)...")
    
    try:
        chat_completion = await groq_client.chat.completions.create(
            messages=messages,
            model="llama-3.1-8b-instant", 
            temperature=0.2, 
        )

        answer = chat_completion.choices[0].message.content
        print("--> [DEBUG] Contextual answer generated successfully.")
        
        return {
            "answer": answer,
            "sources_used": len(retrieved_chunks)
        }
    except Exception as e:
        print(f"--> [DEBUG] GROQ API ERROR: {e}")
        raise e