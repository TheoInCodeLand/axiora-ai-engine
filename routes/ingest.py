from fastapi import APIRouter, HTTPException
from services.scraper import suck_website_data
from services.vector_service import process_and_store
from database.vector_db import get_pinecone_index

router = APIRouter()

@router.post("/ingest")
async def ingest_url(url: str, customer_id: str = "demo_user_01"):
    print("\n==================================================")
    print(f"🚀 NEW ENTERPRISE INGEST REQUEST: {url}")
    print("==================================================")
    
    try:
        print("--> [STEP 1] Deploying Domain Crawler...")
        # The scraper now returns a list of dictionaries containing URLs and content
        crawled_pages = await suck_website_data(url, max_pages=15)
        
        if not crawled_pages or len(crawled_pages) == 0:
            print("--> [STEP 1 FAILED] Crawler found no valid content.")
            raise HTTPException(status_code=500, detail="Could not extract content from the provided domain.")

        print(f"--> [STEP 1 SUCCESS] Retrieved {len(crawled_pages)} pages from the domain.")
        print("--> [STEP 2] Initializing Vector Pipeline...")

        total_chunks_saved = 0
        
        # Loop through every crawled page and vectorize it
        for page in crawled_pages:
            page_url = page["url"]
            page_content = page["content"]
            
            print(f"    -> Vectorizing: {page_url}")
            chunks_saved = await process_and_store(customer_id, page_url, page_content)
            total_chunks_saved += chunks_saved

        print(f"--> [STEP 3] Finished! {total_chunks_saved} total vectors mapped to Pinecone.")
        print("==================================================\n")

        return {
            "status": "Success",
            "base_url": url,
            "pages_crawled": len(crawled_pages),
            "customer_id": customer_id,
            "chunks_saved_to_db": total_chunks_saved
        }
    except Exception as e:
        print(f"--> [FATAL ERROR] Pipeline crashed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/delete")
async def delete_url_data(url: str, customer_id: str):
    # ... keep your existing delete logic exactly as is ...
    print(f"\n--> [SYSTEM] Request to delete vectors for: {url}")
    try:
        index = get_pinecone_index()
        index.delete(
            namespace=customer_id,
            filter={"source_url": {"$eq": url}}
        )
        print("--> [SUCCESS] Vectors purged from Pinecone.")
        return {"status": "Success", "message": "Knowledge base deleted."}
    except Exception as e:
        print(f"--> [FATAL ERROR] Failed to delete from Pinecone: {e}")
        raise HTTPException(status_code=500, detail=str(e))