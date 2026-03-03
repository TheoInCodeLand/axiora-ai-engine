import os
import uuid
import re
from fastembed import TextEmbedding
from langchain_text_splitters import MarkdownTextSplitter
from database.vector_db import get_pinecone_index

# Initialize the local CPU model
# This downloads ~80MB model on the very first run
print("--> [SYSTEM] Initializing Local FastEmbed Engine...")
embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

def clean_markdown(text: str):
    """Cleans up excessive whitespace but PRESERVES all links for the chatbot to use."""
    print("--> [DEBUG] Cleaning whitespace (keeping links intact)...")
    
    # Replace multiple newlines with a single double-newline
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Replace multiple spaces with a single space
    text = re.sub(r' {2,}', ' ', text)
    
    return text.strip()

def chunk_text(text: str):
    clean_text = clean_markdown(text)
    
    print(f"--> [DEBUG] Chunking text of length: {len(clean_text)} characters.")
    
    # Intelligently splits by headers and paragraphs, not just random character counts
    splitter = MarkdownTextSplitter(
        chunk_size=1000,
        chunk_overlap=150
    )
    
    chunks = splitter.split_text(clean_text)
    print(f"--> [DEBUG] Successfully created {len(chunks)} contextual chunks.")
    return chunks

async def process_and_store(customer_id: str, url: str, markdown_text: str):
    chunks = chunk_text(markdown_text)
    if not chunks:
        return 0

    index = get_pinecone_index()
    total_saved = 0
    
    # --- THE RAM SAVER ---
    # We process and upload exactly 50 chunks at a time. 
    # This prevents the list() from consuming all your laptop's memory.
    batch_size = 50 

    print(f"--> [DEBUG] Streaming embeddings to Pinecone in batches of {batch_size}...")
    
    for i in range(0, len(chunks), batch_size):
        chunk_batch = chunks[i:i + batch_size]
        
        # 1. Generate embeddings JUST for this small batch locally
        embeddings_generator = embedding_model.embed(chunk_batch)
        embeddings = list(embeddings_generator)
        
        # 2. Prepare Pinecone Payload
        vectors = []
        for j, (chunk, emb) in enumerate(zip(chunk_batch, embeddings)):
            chunk_id = f"{customer_id}-{uuid.uuid4()}"
            vectors.append({
                "id": chunk_id,
                "values": emb.tolist(),
                "metadata": {
                    "customer_id": customer_id,
                    "url": url,
                    "text": chunk
                }
            })
            
        # 3. Upload to Pinecone immediately and let Python clear the memory
        index.upsert(vectors=vectors, namespace=customer_id)
        total_saved += len(vectors)
        print(f"--> [DEBUG] Uploaded batch... ({total_saved}/{len(chunks)} total vectors saved)")

    print("--> [DEBUG] Pipeline Complete. Memory freed.")
    return total_saved