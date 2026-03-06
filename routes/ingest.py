# routes/ingest.py
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from services.scraper import crawl_and_scrape
from services.vector_service import process_and_store
from database.vector_db import get_pinecone_index

router = APIRouter()

@router.post("/ingest")
async def ingest_url(
    url: str, 
    customer_id: str = "demo_user_01",
    max_pages: int = Query(default=500, ge=1, le=5000),  # ✅ Add limits
    dynamic: bool = True,
    wait_for_api: Optional[str] = Query(default=None, description="API pattern to wait for, e.g., /api/tours")
):
    print("\n" + "="*60)
    print(f"🚀 INGEST REQUEST")
    print(f"   URL: {url}")
    print(f"   Max Pages: {max_pages}")
    print(f"   Dynamic: {dynamic}")
    print(f"   API Pattern: {wait_for_api or 'None'}")
    print("="*60)
    
    try:
        if not dynamic:
            # Static fallback (implement if needed)
            raise HTTPException(status_code=400, detail="Static mode not implemented, use dynamic=true")
        
        # Use dynamic scraper
        crawled_pages = await crawl_and_scrape(
            base_url=url,
            max_pages=max_pages,
            wait_for_api_pattern=wait_for_api
        )
        
        if not crawled_pages:
            raise HTTPException(
                status_code=422,
                detail="No content extracted. The site may block scrapers or require JavaScript."
            )
        
        print(f"\n📊 Processing {len(crawled_pages)} pages to vectors...")
        
        total_chunks = 0
        for page in crawled_pages:
            page_url = page["url"]
            page_content = page["content"]
            chunks = await process_and_store(customer_id, page_url, page_content)
            total_chunks += chunks
            print(f"   💾 {page_url}: {chunks} chunks")

        print(f"\n✅ Total: {total_chunks} chunks saved")

        return {
            "status": "Success",
            "base_url": url,
            "pages_crawled": len(crawled_pages),
            "customer_id": customer_id,
            "chunks_saved_to_db": total_chunks
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/delete")
async def delete_url_data(url: str, customer_id: str):
    print(f"\n🗑️  Delete request: {url}")
    try:
        index = get_pinecone_index()
        index.delete(
            namespace=customer_id,
            filter={"source_url": {"$eq": url}}
        )
        print("✅ Vectors deleted")
        return {"status": "Success", "message": "Knowledge base deleted."}
    except Exception as e:
        print(f"❌ Delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))