
import requests
from bs4 import BeautifulSoup
import re
import queue
import threading
import time
import logging
from urllib.parse import quote_plus
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class TacticalRecon:
    """
    Market intelligence gathering through web crawling and search.
    Targets UAE marketplaces for competitor analysis.
    """
    
    def __init__(self, db_manager):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })
        self.crawl_queue = queue.Queue()
        self.results_cache = {}
        self.db_manager = db_manager
    
    def crawl_url(self, url: str, extract_pricing: bool = True) -> Dict[str, Any]:
        """
        Crawl a URL and extract relevant data.
        """
        from core.time_service import time_service
        result = {
            'url': url,
            'success': False,
            'title': '',
            'content_summary': '',
            'pricing': [],
            'timestamp': time_service.now_iso()
        }
        
        try:
            response = self.session.get(url, timeout=15, allow_redirects=True)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title_tag = soup.find('title')
            result['title'] = title_tag.string.strip() if title_tag else 'No title'
            
            content_tags = soup.find_all(['p', 'h1', 'h2', 'h3'])
            result['content_summary'] = ' '.join([tag.get_text(strip=True) for tag in content_tags[:10]])
            
            if extract_pricing:
                price_patterns = [
                    r'[\$€£AEDد.إ]+\s*[\d,]+\.?\d*',
                    r'[\d,]+\.?\d*\s*[\$€£AEDد.إ]+',
                    r'Price[:\s]*[\$€£AEDد.إ]*\s*[\d,]+\.?\d*'
                ]
                text_content = soup.get_text()
                for pattern in price_patterns:
                    prices = re.findall(pattern, text_content, re.IGNORECASE)
                    result['pricing'].extend(prices[:5])
            
            result['success'] = True
            logger.info(f"Successfully crawled: {url}")
            
        except Exception as e:
            logger.error(f"Crawl error for {url}: {str(e)}")
            result['error'] = str(e)
        
        return result
    
    def search_competitors(self, product_name: str, 
                           marketplaces: List[str] = None) -> List[Dict]:
        """
        Search competitor pricing across marketplaces.
        """
        if marketplaces is None:
            marketplaces = ['noon.com', 'amazon.ae', 'trendyol.com']
        
        results = []
        for marketplace in marketplaces:
            search_url = f"https://www.{marketplace}/search?q={quote_plus(product_name)}"
            crawl_result = self.crawl_url(search_url)
            crawl_result['marketplace'] = marketplace
            crawl_result['search_term'] = product_name
            
            self.db_manager.insert_crawler_log(
                product_name, 
                marketplace, 
                str({'pricing': crawl_result['pricing'], 'success': crawl_result['success']})
            )
            
            results.append(crawl_result)
            time.sleep(2)
        
        return results
    
    def start_background_crawler(self, keywords: List[str]):
        """Start background crawler thread for continuous monitoring"""
        def crawl_loop():
            while True:
                try:
                    for keyword in keywords:
                        results = self.search_competitors(keyword)
                        for result in results:
                            if result['success']:
                                logger.info(f"Crawler found data for {keyword} on {result['marketplace']}")
                        time.sleep(30)
                except Exception as e:
                    logger.error(f"Crawler loop error: {e}")
                    time.sleep(60)
        
        thread = threading.Thread(target=crawl_loop, daemon=True)
        thread.start()
        logger.info("Background crawler started")
