import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

async def fetch_html(session, url):
    """Fetches the HTML content of a URL asynchronously."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status == 200:
                return await response.text()
            return None
    except Exception as e:
        print(f"--> [WARNING] Failed to fetch {url}: {e}")
        return None

def extract_clean_text(html):
    """Strips out headers, footers, and nav bars to keep only the core content."""
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
        element.decompose()
        
    text = soup.get_text(separator="\n")
    return text

def get_internal_links(base_url, html):
    """Finds all valid internal links on a page."""
    soup = BeautifulSoup(html, "html.parser")
    internal_links = set()
    domain = urlparse(base_url).netloc

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        parsed_url = urlparse(full_url)
        
        if parsed_url.netloc == domain:
            # Remove anchor fragments (e.g., /page#section) to avoid duplicate scraping
            clean_url = full_url.split('#')[0]
            
            # Ignore media files and mailto links
            if not any(clean_url.lower().endswith(ext) for ext in ['.pdf', '.png', '.jpg', '.jpeg', '.zip', '.mp4']) and not clean_url.startswith('mailto:'):
                internal_links.add(clean_url)
                
    return internal_links

async def suck_website_data(start_url: str, max_pages: int = 15):
    """
    Crawls the domain starting from the target URL.
    Returns a list of dictionaries: [{"url": "...", "content": "..."}, ...]
    """
    visited = set()
    to_visit = [start_url]
    scraped_data = []

    print(f"\n--> [SYSTEM] Initiating Domain Crawl: {start_url} (Max {max_pages} pages)")
    
    async with aiohttp.ClientSession() as session:
        while to_visit and len(visited) < max_pages:
            current_url = to_visit.pop(0)
            
            if current_url in visited:
                continue
                
            visited.add(current_url)
            print(f"--> [CRAWLER] Scraping page {len(visited)}/{max_pages}: {current_url}")
            
            html = await fetch_html(session, current_url)
            if not html:
                continue
                
            text_content = extract_clean_text(html)
            
            if text_content and len(text_content.strip()) > 50:
                scraped_data.append({
                    "url": current_url,
                    "content": text_content
                })
                
            # Find new links on this page and add them to the queue
            new_links = get_internal_links(start_url, html)
            for link in new_links:
                if link not in visited and link not in to_visit:
                    to_visit.append(link)

    print(f"--> [SYSTEM] Crawl complete. Successfully extracted {len(scraped_data)} unique pages.")
    return scraped_data