# services/scraper.py - ABSOLUTE COMPLETE WEBSITE EXTRACTION
import asyncio
import time
import json
import re
import hashlib
from urllib.parse import urlparse, urljoin, unquote
from typing import List, Dict, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

from playwright.async_api import (
    async_playwright, Page, BrowserContext, Response, 
    Route, Request, WebSocket, JSHandle, ElementHandle
)
from playwright_stealth import stealth_async
from bs4 import BeautifulSoup

@dataclass
class ScrapedPage:
    url: str
    title: str
    content: str
    html: str
    text_content: str = ""  # Pure text for search
    api_data: List[Dict] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)  # Base64 screenshots
    metadata: Dict = field(default_factory=dict)
    links_found: List[str] = field(default_factory=list)
    forms: List[Dict] = field(default_factory=list)
    discovered_apis: Set[str] = field(default_factory=set)

class UltimateScraper:
    """
    ABSOLUTE COMPLETE extraction. Gets EVERYTHING:
    - All pages via every navigation method
    - All dynamically loaded content
    - All API data
    - All client-side routed pages
    - All infinite scroll content
    - All modal/popup content
    - All tab-switched content
    """
    
    def __init__(
        self,
        max_pages: int = 500,  # Much higher for deep crawls
        max_depth: int = 10,
        scroll_timeout: int = 300,  # 5 minutes for heavy pages
        extraction_timeout: int = 600,  # 10 minutes per page
        min_content_length: int = 50,
        enable_screenshots: bool = False,
        respect_robots: bool = True
    ):
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.scroll_timeout = scroll_timeout
        self.extraction_timeout = extraction_timeout
        self.min_content_length = min_content_length
        self.enable_screenshots = enable_screenshots
        self.respect_robots = respect_robots
        
        # State tracking
        self.visited_urls: Set[str] = set()
        self.url_hashes: Set[str] = set()  # Detect duplicate content
        self.discovered_urls: Set[str] = set()
        self.api_endpoints: Set[str] = set()
        self.ws_messages: List[Dict] = []
        
        # Content fingerprints to avoid duplicates
        self.content_hashes: Set[str] = set()
        
        # Rate limiting
        self.domain_delays: Dict[str, float] = {}
        self.min_delay = 0.5
        
        # Browser state
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
    
    async def deep_crawl(
        self,
        start_url: str,
        auth_cookies: Optional[List[Dict]] = None,
        local_storage: Optional[Dict] = None,
        session_storage: Optional[Dict] = None,
        custom_headers: Optional[Dict] = None,
        wait_for_selectors: Optional[List[str]] = None,
        extract_apis: bool = True,
        follow_client_routing: bool = True,
        extract_modals: bool = True
    ) -> List[ScrapedPage]:
        """
        DEEP CRAWL: Extracts literally everything from a website.
        """
        
        print(f"\n{'='*70}")
        print(f"🕷️  ULTIMATE DEEP CRAWL")
        print(f"   Target: {start_url}")
        print(f"   Max Pages: {self.max_pages}")
        print(f"   Max Depth: {self.max_depth}")
        print(f"{'='*70}\n")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--window-size=1920,1080',
                    '--enable-javascript',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            
            self.context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York',
                java_script_enabled=True,
                bypass_csp=True,
            )
            
            # Set authentication and storage
            if auth_cookies:
                await self.context.add_cookies(auth_cookies)
            
            if custom_headers:
                await self.context.set_extra_http_headers(custom_headers)
            
            # Create main page
            self.page = await self.context.new_page()
            await stealth_async(self.page)
            
            # Setup comprehensive monitoring
            await self._setup_monitoring(self.page, extract_apis)
            
            # Inject storage
            if local_storage or session_storage:
                await self._inject_storage(local_storage, session_storage)
            
            # Start crawling
            results = []
            queue = deque([(start_url, 0)])  # (url, depth)
            
            while queue and len(self.visited_urls) < self.max_pages:
                current_url, depth = queue.popleft()
                
                if depth > self.max_depth:
                    continue
                
                normalized = self._normalize_url(current_url)
                if normalized in self.visited_urls:
                    continue
                
                # Scrape this page
                page_data = await self._extract_everything(
                    current_url, 
                    depth,
                    wait_for_selectors=wait_for_selectors,
                    follow_client_routing=follow_client_routing,
                    extract_modals=extract_modals
                )
                
                if page_data:
                    results.append(page_data)
                    
                    # Queue new links
                    for link in page_data.links_found:
                        if self._normalize_url(link) not in self.visited_urls:
                            queue.append((link, depth + 1))
                            self.discovered_urls.add(link)
            
            await self.context.close()
            await browser.close()
        
        print(f"\n{'='*70}")
        print(f"✅ DEEP CRAWL COMPLETE")
        print(f"   Pages scraped: {len(results)}")
        print(f"   Total URLs discovered: {len(self.discovered_urls)}")
        print(f"   API endpoints found: {len(self.api_endpoints)}")
        print(f"{'='*70}\n")
        
        return results
    
    async def _setup_monitoring(self, page: Page, extract_apis: bool):
        """Monitor all network activity."""
        
        # Capture all responses
        async def handle_response(response: Response):
            url = response.url
            content_type = response.headers.get('content-type', '')
            
            # Track API endpoints
            if extract_apis and ('json' in content_type or 'api' in url):
                self.api_endpoints.add(url)
                
                # Try to capture response body
                try:
                    body = await response.json()
                    self.ws_messages.append({
                        'type': 'api',
                        'url': url,
                        'data': body,
                        'time': time.time()
                    })
                except:
                    pass
        
        page.on("response", lambda r: asyncio.create_task(handle_response(r)))
        
        # Monitor WebSockets
        async def handle_ws(ws: WebSocket):
            print(f"   🔌 WebSocket detected: {ws.url}")
            ws.on("framereceived", lambda payload: self.ws_messages.append({
                'type': 'websocket',
                'url': ws.url,
                'data': payload,
                'time': time.time()
            }))
        
        page.on("websocket", handle_ws)
        
        # Monitor console for errors/data
        page.on("console", lambda msg: print(f"   🖥️  Console [{msg.type}]: {msg.text[:100]}") if msg.type == 'error' else None)
        
        # Monitor new pages/popups
        self.context.on("page", lambda page: print(f"   📄 New page opened: {page.url}"))
    
    async def _inject_storage(self, local_storage: Optional[Dict], session_storage: Optional[Dict]):
        """Inject storage items."""
        if not self.page:
            return
        
        script = ""
        if local_storage:
            for key, value in local_storage.items():
                script += f'localStorage.setItem("{key}", {json.dumps(value)});'
        if session_storage:
            for key, value in session_storage.items():
                script += f'sessionStorage.setItem("{key}", {json.dumps(value)});'
        
        if script:
            await self.page.evaluate(script)
    
    async def _extract_everything(
        self,
        url: str,
        depth: int,
        wait_for_selectors: Optional[List[str]] = None,
        follow_client_routing: bool = True,
        extract_modals: bool = True
    ) -> Optional[ScrapedPage]:
        """
        Extract absolutely everything from a single page.
        """
        
        normalized = self._normalize_url(url)
        self.visited_urls.add(normalized)
        
        print(f"\n🔍 [{len(self.visited_urls)}/{self.max_pages}] {url[:70]} (depth {depth})")
        
        await self._respect_rate_limit(url)
        
        try:
            # Navigate with multiple strategies
            await self._smart_navigation(url)
            
            # Wait for initial render
            await self._wait_for_render()
            
            # Extract base content
            base_content = await self._get_page_content()
            
            # PHASE 1: Infinite Scroll (get ALL lazy-loaded content)
            print(f"   📜 Phase 1: Infinite scroll extraction...")
            scroll_content = await self._extract_infinite_scroll()
            
            # PHASE 2: Client-Side Routing (click all internal links)
            routed_content = ""
            if follow_client_routing:
                print(f"   🧭 Phase 2: Client-side routing...")
                routed_content = await self._extract_client_routes()
            
            # PHASE 3: Modals and Popups
            modal_content = ""
            if extract_modals:
                print(f"   🪟 Phase 3: Modal extraction...")
                modal_content = await self._extract_all_modals()
            
            # PHASE 4: Tabbed/Switched Content
            print(f"   🗂️  Phase 4: Tab content...")
            tab_content = await self._extract_tab_content()
            
            # PHASE 5: Form interactions
            print(f"   📝 Phase 5: Form exploration...")
            forms = await self._explore_forms()
            
            # Combine all content
            all_content = self._combine_content([
                base_content,
                scroll_content,
                routed_content,
                modal_content,
                tab_content
            ])
            
            # Deduplicate
            final_content = self._deduplicate_content(all_content)
            
            # Get metadata
            title = await self.page.title()
            html = await self.page.content()
            
            # Extract all links from final state
            links = await self._extract_all_links()
            
            # Get API data from monitoring
            api_data = [m for m in self.ws_messages if m['time'] > time.time() - 60]
            
            print(f"   ✅ Extracted {len(final_content)} chars, {len(links)} links, {len(api_data)} API calls")
            
            return ScrapedPage(
                url=url,
                title=title,
                content=final_content,
                html=html,
                api_data=api_data,
                links_found=links,
                forms=forms,
                discovered_apis=self.api_endpoints.copy()
            )
            
        except Exception as e:
            print(f"   ❌ Error: {str(e)[:100]}")
            return None
    
    async def _smart_navigation(self, url: str):
        """Navigate with multiple fallback strategies."""
        try:
            await self.page.goto(url, wait_until='networkidle', timeout=30000)
        except:
            try:
                await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
            except Exception as e:
                raise Exception(f"Navigation failed: {e}")
    
    async def _wait_for_render(self):
        """Wait for JavaScript frameworks to render."""
        # Wait for common indicators
        indicators = [
            'document.readyState === "complete"',
            'window.__NEXT_DATA__ || window.__INITIAL_STATE__ || window.__DATA__',
            'document.querySelector("main") || document.querySelector("#root") || document.querySelector("#app")'
        ]
        
        for indicator in indicators:
            try:
                await self.page.wait_for_function(
                    f'() => {indicator}',
                    timeout=5000
                )
            except:
                pass
        
        # Additional wait for React/Vue hydration
        await asyncio.sleep(1)
    
    async def _get_page_content(self) -> str:
        """Get current page content."""
        return await self._extract_text_from_page()
    
    async def _extract_infinite_scroll(self) -> str:
        """
        AGGRESSIVE infinite scroll - continues until no new content.
        """
        all_content = []
        last_hash = ""
        no_change_count = 0
        max_no_change = 3
        
        start_time = time.time()
        
        while time.time() - start_time < self.scroll_timeout:
            # Get current content hash
            current_html = await self.page.content()
            current_hash = hashlib.md5(current_html.encode()).hexdigest()
            
            if current_hash == last_hash:
                no_change_count += 1
                if no_change_count >= max_no_change:
                    print(f"   📜 No new content after {no_change_count} scrolls")
                    break
            else:
                no_change_count = 0
                # Extract content at this scroll position
                text = await self._extract_text_from_page()
                all_content.append(text)
            
            last_hash = current_hash
            
            # Scroll down
            await self.page.evaluate('window.scrollBy(0, window.innerHeight * 0.8)')
            await asyncio.sleep(0.5)
            
            # Try clicking "Load More" buttons
            await self._click_load_more()
        
        return "\n\n".join(all_content)
    
    async def _click_load_more(self):
        """Click any load more buttons."""
        selectors = [
            'button:has-text("Load")',
            'button:has-text("More")',
            'button:has-text("Show")',
            '[data-testid*="load"]',
            '[data-testid*="more"]',
            '.load-more',
            '.show-more',
        ]
        
        for selector in selectors:
            try:
                buttons = await self.page.query_selector_all(selector)
                for btn in buttons:
                    if await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(1)
                        return True
            except:
                continue
        return False
    
    async def _extract_client_routes(self) -> str:
        """
        Extract content from client-side routed pages without full navigation.
        """
        all_content = []
        
        # Get all internal links
        links = await self.page.evaluate('''() => {
            const links = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.getAttribute('href');
                if (href && !href.startsWith('http') && !href.startsWith('#')) {
                    links.push(href);
                }
            });
            return [...new Set(links)].slice(0, 20);  // Limit to 20
        }''')
        
        print(f"   🧭 Found {len(links)} internal routes to explore")
        
        base_url = self.page.url
        
        for link in links[:10]:  # Max 10 routes per page
            try:
                # Use client-side navigation
                full_url = urljoin(base_url, link)
                if self._normalize_url(full_url) in self.visited_urls:
                    continue
                
                print(f"   🧭 Navigating to: {link[:50]}")
                
                # Click or use router
                await self.page.evaluate(f'''
                    () => {{
                        if (window.next && window.next.router) {{
                            window.next.router.push("{link}");
                        }} else if (window.history.pushState) {{
                            window.history.pushState(null, "", "{link}");
                            window.dispatchEvent(new PopStateEvent('popstate'));
                        }} else {{
                            window.location.href = "{link}";
                        }}
                    }}
                ''')
                
                await asyncio.sleep(2)  # Wait for route change
                await self._wait_for_render()
                
                # Extract content
                content = await self._extract_text_from_page()
                all_content.append(f"\n[Route: {link}]\n{content}")
                
                # Go back
                await self.page.go_back()
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"   ⚠️  Route failed: {e}")
                continue
        
        return "\n\n".join(all_content)
    
    async def _extract_all_modals(self) -> str:
        """Find and extract all modal/popup content."""
        all_content = []
        
        # Find modal triggers
        triggers = await self.page.query_selector_all('''
            button[data-toggle="modal"],
            [data-target*="modal"],
            [onclick*="modal"],
            .modal-trigger,
            button:has-text("Details"),
            button:has-text("More info"),
            [role="button"]
        ''')
        
        print(f"   🪟 Found {len(triggers)} potential modals")
        
        for i, trigger in enumerate(triggers[:5]):  # Max 5 modals
            try:
                if not await trigger.is_visible():
                    continue
                
                # Click to open
                await trigger.click()
                await asyncio.sleep(1)
                
                # Find modal content
                modal_selectors = [
                    '.modal.show',
                    '.modal.active',
                    '[role="dialog"]',
                    '.popup',
                    '.overlay',
                    '[class*="modal"]'
                ]
                
                for selector in modal_selectors:
                    modal = await self.page.query_selector(selector)
                    if modal:
                        content = await modal.inner_text()
                        if len(content) > 100:
                            all_content.append(f"\n[Modal {i+1}]\n{content}")
                        
                        # Close modal
                        await self._close_modal()
                        break
                        
            except Exception as e:
                continue
        
        return "\n\n".join(all_content)
    
    async def _close_modal(self):
        """Try to close any open modal."""
        close_methods = [
            'document.querySelector(".modal .close, .modal [data-dismiss]")?.click()',
            'document.querySelector(\'[aria-label="Close"]\')?.click()',
            'document.querySelector(".modal")?.classList.remove("show")',
            'document.keydown({key: "Escape"})',
        ]
        
        for method in close_methods:
            try:
                await self.page.evaluate(method)
                await asyncio.sleep(0.3)
            except:
                continue
    
    async def _extract_tab_content(self) -> str:
        """Extract content from all tabs/switches."""
        all_content = []
        
        # Find tab buttons
        tabs = await self.page.query_selector_all('''
            [role="tab"],
            .nav-tabs button,
            .tab-button,
            [data-toggle="tab"],
            button:has-text("Tab")
        ''')
        
        print(f"   🗂️  Found {len(tabs)} tabs")
        
        for i, tab in enumerate(tabs[:8]):  # Max 8 tabs
            try:
                if not await tab.is_visible():
                    continue
                
                await tab.click()
                await asyncio.sleep(0.8)
                
                # Get active tab content
                content = await self._extract_text_from_page()
                
                # Only add if different from base
                if len(content) > 200:
                    all_content.append(f"\n[Tab {i+1}]\n{content}")
                    
            except:
                continue
        
        return "\n\n".join(all_content)
    
    async def _explore_forms(self) -> List[Dict]:
        """Find and describe all forms (don't submit)."""
        forms = await self.page.query_selector_all('form')
        form_data = []
        
        for form in forms:
            try:
                fields = await form.query_selector_all('input, select, textarea')
                field_info = []
                
                for field in fields:
                    name = await field.get_attribute('name') or await field.get_attribute('id') or 'unnamed'
                    field_type = await field.get_attribute('type') or 'text'
                    field_info.append(f"{name}({field_type})")
                
                form_data.append({
                    'fields': field_info,
                    'action': await form.get_attribute('action') or 'current'
                })
            except:
                continue
        
        return form_data
    
    async def _extract_text_from_page(self) -> str:
        """Extract clean text from current page state."""
        try:
            # Try main content areas first
            selectors = ['main', 'article', '[role="main"]', '.content', '#content', 'body']
            
            for selector in selectors:
                element = await self.page.query_selector(selector)
                if element:
                    text = await element.evaluate('''el => {
                        const clone = el.cloneNode(true);
                        
                        // Remove hidden elements
                        clone.querySelectorAll('[style*="display: none"], [style*="visibility: hidden"], [hidden]')
                            .forEach(e => e.remove());
                        
                        // Remove scripts, styles
                        clone.querySelectorAll('script, style, nav, header, footer, aside')
                            .forEach(e => e.remove());
                        
                        // Format headings
                        clone.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
                            const level = parseInt(h.tagName[1]);
                            h.innerHTML = '\\n' + '#'.repeat(level) + ' ' + h.innerText + '\\n';
                        });
                        
                        // Format lists
                        clone.querySelectorAll('li').forEach(li => {
                            li.innerHTML = '- ' + li.innerText;
                        });
                        
                        return clone.innerText;
                    }''')
                    
                    cleaned = self._clean_text(text)
                    if len(cleaned) > self.min_content_length:
                        return cleaned
            
            return ""
        except Exception as e:
            print(f"   ⚠️  Text extraction error: {e}")
            return ""
    
    async def _extract_all_links(self) -> List[str]:
        """Extract all links from current page state."""
        try:
            links = await self.page.evaluate('''() => {
                const found = new Set();
                
                // Standard links
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.getAttribute('href');
                    if (href && !href.startsWith('#') && !href.startsWith('javascript:')) {
                        try {
                            const absolute = new URL(href, window.location.href).href;
                            found.add(absolute);
                        } catch (e) {}
                    }
                });
                
                // Router links (React Router, etc.)
                document.querySelectorAll('[data-href], [data-link], [data-to]').forEach(el => {
                    const href = el.getAttribute('data-href') || 
                                el.getAttribute('data-link') || 
                                el.getAttribute('data-to');
                    if (href) {
                        try {
                            const absolute = new URL(href, window.location.href).href;
                            found.add(absolute);
                        } catch (e) {}
                    }
                });
                
                // Click handlers that might be routes
                document.querySelectorAll('[onclick*="router"], [onclick*="navigate"]').forEach(el => {
                    const onclick = el.getAttribute('onclick');
                    const match = onclick.match(/['"]([^'"]+)['"]/);
                    if (match) {
                        try {
                            const absolute = new URL(match[1], window.location.href).href;
                            found.add(absolute);
                        } catch (e) {}
                    }
                });
                
                return Array.from(found);
            }''')
            
            # Filter to same domain
            base_domain = urlparse(self.page.url).netloc
            same_domain = [l for l in links if urlparse(l).netloc == base_domain]
            
            return same_domain
            
        except Exception as e:
            print(f"   ⚠️  Link extraction error: {e}")
            return []
    
    def _combine_content(self, contents: List[str]) -> str:
        """Combine multiple content sources."""
        return "\n\n".join([c for c in contents if c and len(c) > 50])
    
    def _deduplicate_content(self, content: str) -> str:
        """Remove duplicate paragraphs."""
        paragraphs = content.split('\n\n')
        seen = set()
        unique = []
        
        for p in paragraphs:
            p_hash = hashlib.md5(p.strip().lower().encode()).hexdigest()
            if p_hash not in seen and len(p.strip()) > 10:
                seen.add(p_hash)
                unique.append(p)
        
        return '\n\n'.join(unique)
    
    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        if not text:
            return ""
        
        # Normalize whitespace
        lines = text.split('\n')
        cleaned = []
        
        for line in lines:
            line = ' '.join(line.split())  # Normalize spaces
            if len(line) > 2:
                cleaned.append(line)
        
        # Join with proper spacing
        result = '\n'.join(cleaned)
        
        # Remove excessive blank lines
        while '\n\n\n' in result:
            result = result.replace('\n\n\n', '\n\n')
        
        return result.strip()
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        try:
            parsed = urlparse(url)
            # Remove query params and fragments, lowercase
            path = unquote(parsed.path).rstrip('/').lower()
            return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"
        except:
            return url.lower()
    
    def _should_crawl(self, url: str) -> bool:
        """Determine if URL should be crawled."""
        try:
            parsed = urlparse(url)
            url_lower = url.lower()
            
            # Skip file types
            skip_exts = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.css', '.js', '.zip', '.mp4', '.mp3']
            if any(url_lower.endswith(ext) for ext in skip_exts):
                return False
            
            # Skip utility pages
            skip_paths = ['/login', '/logout', '/auth', '/admin', '/cart', '/checkout', '/api/', '/password', '/reset', '/search']
            path_lower = parsed.path.lower()
            for skip in skip_paths:
                if skip in path_lower:
                    return False
            
            return True
        except:
            return False
    
    async def _respect_rate_limit(self, url: str):
        """Rate limiting."""
        try:
            domain = urlparse(url).netloc
            now = time.time()
            last = self.domain_delays.get(domain, 0)
            
            if now - last < self.min_delay:
                wait = self.min_delay - (now - last)
                await asyncio.sleep(wait)
            
            self.domain_delays[domain] = time.time()
        except:
            pass


# === PUBLIC INTERFACE ===

async def deep_crawl_website(
    url: str,
    max_pages: int = 100,
    auth_cookies: Optional[List[Dict]] = None,
    extract_everything: bool = True
) -> List[Dict]:
    """
    DEEP CRAWL: Extract absolutely everything from a website.
    
    This gets:
    - All pages through every navigation method
    - All infinite scroll content
    - All client-side routed content
    - All modal/popup content
    - All API data
    - All tab-switched content
    """
    
    scraper = UltimateScraper(
        max_pages=max_pages,
        max_depth=5 if extract_everything else 2,
        scroll_timeout=300 if extract_everything else 60,
        extraction_timeout=600 if extract_everything else 120
    )
    
    results = await scraper.deep_crawl(
        url,
        auth_cookies=auth_cookies,
        follow_client_routing=extract_everything,
        extract_modals=extract_everything
    )
    
    return [
        {
            "url": r.url,
            "title": r.title,
            "content": r.content,
            "html": r.html[:50000],  # Truncate for memory
            "api_calls": len(r.api_data),
            "links_found": len(r.links_found),
            "forms": r.forms
        }
        for r in results
    ]


# Legacy compatibility
async def crawl_and_scrape(base_url: str, max_pages: int = 15, **kwargs) -> List[Dict]:
    """Backward compatible wrapper."""
    return await deep_crawl_website(base_url, max_pages=max_pages)

async def suck_website_data(url: str) -> str:
    """Single page extraction."""
    results = await deep_crawl_website(url, max_pages=1)
    return results[0]["content"] if results else ""