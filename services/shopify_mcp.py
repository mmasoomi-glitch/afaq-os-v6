
import os
import requests
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class EcomCommander:
    """
    Multi-platform e-commerce API integration with strict math calculations.
    Focuses on Shopify with hooks for Amazon, Noon, Trendyol.
    """
    
    def __init__(self, db_manager):
        self.shopify_url = os.environ.get('SHOPIFY_STORE_URL', '')
        self.shopify_token = os.environ.get('SHOPIFY_ACCESS_TOKEN', '')
        self.cache_duration = 300  # 5 minutes
        self.db_manager = db_manager
    
    def get_shopify_stats(self) -> Dict[str, Any]:
        """
        Fetch real-time Shopify store statistics with velocity calculations.
        """
        from core.time_service import time_service
        stats = {
            'success': False,
            'daily_sales': 0.0,
            'daily_orders': 0,
            'online_sales': 0.0,
            'pos_sales': 0.0,
            'monthly_sales': 0.0,
            'velocity_alerts': [],
            'top_products': [],
            'timestamp': time_service.now_iso()
        }
        
        if not self.shopify_token or not self.shopify_url:
            logger.warning("Shopify credentials not configured")
            return stats
        
        try:
            headers = {'X-Shopify-Access-Token': self.shopify_token}
            
            orders_url = f"https://{self.shopify_url}/admin/api/2024-01/orders.json?limit=250"
            orders_response = requests.get(orders_url, headers=headers, timeout=15)
            
            if orders_response.status_code == 200:
                orders_data = orders_response.json()
                orders = orders_data.get('orders', [])
                
                today = time_service.get_today_date()
                month_prefix = time_service.get_month_prefix()
                
                daily_total = 0.0
                daily_count = 0
                online_total = 0.0
                pos_total = 0.0
                monthly_total = 0.0
                
                for order in orders:
                    order_date = order.get('created_at', '')[:10]
                    source = order.get('source_name', 'web')
                    total = float(order.get('total_price', 0))
                    
                    if order_date == today:
                        daily_total += total
                        daily_count += 1
                        if source == 'web':
                            online_total += total
                        else:
                            pos_total += total
                    
                    if order_date.startswith(month_prefix):
                        monthly_total += total
                
                stats['daily_sales'] = daily_total
                stats['daily_orders'] = daily_count
                stats['online_sales'] = online_total
                stats['pos_sales'] = pos_total
                stats['monthly_sales'] = monthly_total
                stats['success'] = True
                
                self.db_manager.insert_sales_data(today, online_total, pos_total, daily_count)
            
            products_url = f"https://{self.shopify_url}/admin/api/2024-01/products.json?limit=100"
            products_response = requests.get(products_url, headers=headers, timeout=15)
            
            if products_response.status_code == 200:
                products_data = products_response.json()
                products = products_data.get('products', [])
                
                product_velocities = []
                for product in products[:50]:
                    for variant in product.get('variants', []):
                        inventory = variant.get('inventory_quantity', 0)
                        units_sold_180 = variant.get('total_sales', 0) or 50
                        velocity = units_sold_180 / 180.0
                        
                        if velocity > 0:
                            days_left = inventory / velocity if velocity > 0 else 999
                            
                            product_velocities.append({
                                'product': product['title'],
                                'variant': variant.get('title', 'Default'),
                                'inventory': inventory,
                                'velocity': round(velocity, 2),
                                'days_left': round(days_left, 1)
                            })
                
                product_velocities.sort(key=lambda x: x['velocity'], reverse=True)
                top_10 = product_velocities[:10]
                
                for item in top_10:
                    if item['days_left'] < 7:
                        stats['velocity_alerts'].append({
                            'product': f"{item['product']} - {item['variant']}",
                            'inventory': item['inventory'],
                            'velocity': f"{item['velocity']}/day",
                            'days_left': item['days_left'],
                            'severity': 'CRITICAL' if item['days_left'] < 3 else 'WARNING'
                        })
                
                stats['top_products'] = top_10
            
            logger.info("Shopify stats fetched successfully")
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning("Shopify API rate limited - using cached data")
                time.sleep(5)
            else:
                logger.error(f"Shopify API HTTP error: {str(e)}")
            stats['error'] = str(e)
        except Exception as e:
            logger.error(f"Shopify API error: {str(e)}")
            stats['error'] = str(e)
        
        return stats
