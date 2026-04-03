from services.shopify_ai_agent import ShopifyAIAgent
agent = ShopifyAIAgent()
print('ready', agent.ready())
print('deepseek_key', agent.deepseek_key)
print('store_url', agent.store_url)
print('token', agent.token)
print('get_metrics', agent.get_metrics())
print('get_last_order', agent.get_last_order())
