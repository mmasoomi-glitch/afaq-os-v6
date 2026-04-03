import os

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
os.makedirs(os.path.join(BASE, "services"), exist_ok=True)

init_path = os.path.join(BASE, "services", "__init__.py")
with open(init_path, "w", encoding="utf-8") as f:
    f.write("# services package\n")
print("[OK] services/__init__.py")

code = ""
code += "import os, requests\n"
code += "from datetime import datetime, timedelta\n"
code += "\n"
code += "\n"
code += "class ShopifyAIAgent:\n"
code += '    """Fetches Shopify data and answers with DeepSeek."""\n'
code += "\n"
code += "    def __init__(self):\n"
code += '        self.deepseek_key = os.environ.get("DEEPSEEK_API_KEY")\n'
code += '        self.store_url = os.environ.get("SHOPIFY_STORE_URL")\n'
code += '        self.token = os.environ.get("SHOPIFY_ACCESS_TOKEN")\n'
code += "        self.base_url = (\n"
code += '            f"https://{self.store_url}/admin/api/2025-01"\n'
code += "            if self.store_url else None\n"
code += "        )\n"
code += "        self.headers = (\n"
code += '            {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}\n'
code += "            if self.token else None\n"
code += "        )\n"
code += "        self._build_rag()\n"
code += "\n"
code += "    # ---- RAG context baked in ----------------------------------------\n"
code += "    def _build_rag(self):\n"
code += '        self.rag = (\n'
code += '            "You are the senior Business Analyst for Afaq Alnaseem Trading LLC.\\n"\n'
code += '            "Prioritize: Profitability, Customer Retention, Growth Efficiency.\\n"\n'
code += '            "\\n"\n'
code += '            "=== SALES & PROFITABILITY ===\\n"\n'
code += '            "Net Profit Margin = (Revenue - COGS - Marketing - Shipping) / Revenue x 100\\n"\n'
code += '            "AOV = total_sales / order_count\\n"\n'
code += '            "Gross Profit Margin = (Revenue - COGS) / Revenue x 100\\n"\n'
code += '            "\\n"\n'
code += '            "=== CUSTOMER RETENTION ===\\n"\n'
code += '            "CLV: use total_spent + orders_count per customer\\n"\n'
code += '            "Returning Rate = customers_with_>1_order / total_unique x 100\\n"\n'
code += '            "Cart Abandonment = abandoned / (abandoned + orders) x 100\\n"\n'
code += '            "\\n"\n'
code += '            "=== INVENTORY ===\\n"\n'
code += '            "Sell-Through = units_sold / (units_sold + stock) x 100\\n"\n'
code += '            "\\n"\n'
code += '            "Always return clear numbers, time period, and recommendations.\\n"\n'
code += "        )\n"
code += "\n"
code += "    # ---- helpers -----------------------------------------------------\n"
code += "    def ready(self):\n"
code += "        return bool(self.deepseek_key and self.base_url and self.headers)\n"
code += "\n"
code += "    def fetch_orders(self, days=30):\n"
code += "        if not self.ready():\n"
code += '            return {"error": "Shopify env vars missing"}\n'
code += "        try:\n"
code += "            since = (datetime.now() - timedelta(days=days)).strftime(\"%Y-%m-%dT00:00:00\")\n"
code += "            url = self.base_url + \"/orders.json?status=any&limit=250&created_at_min=\" + since\n"
code += "            r = requests.get(url, headers=self.headers, timeout=20)\n"
code += "            if r.status_code == 200:\n"
code += '                return r.json().get("orders", [])\n'
code += '            return {"error": "HTTP " + str(r.status_code)}\n'
code += "        except Exception as e:\n"
code += '            return {"error": str(e)}\n'
code += "\n"
code += "    def get_metrics(self):\n"
code += "        orders = self.fetch_orders()\n"
code += '        if isinstance(orders, dict) and "error" in orders:\n'
code += '            return {"status": "error", "message": orders["error"]}\n'
code += "        if not orders:\n"
code += '            return {"status": "no_data"}\n'
code += "        total = sum(float(o.get(\"total_price\", 0)) for o in orders)\n"
code += "        count = len(orders)\n"
code += "        aov = round(total / count, 2) if count else 0\n"
code += "        custs = set()\n"
code += "        for o in orders:\n"
code += "            c = o.get(\"customer\")\n"
code += "            if c and c.get(\"id\"):\n"
code += "                custs.add(c[\"id\"])\n"
code += "        return {\n"
code += '            "status": "success",\n'
code += '            "period": "last 30 days",\n'
code += '            "total_sales": round(total, 2),\n'
code += '            "orders": count,\n'
code += '            "aov": aov,\n'
code += '            "unique_customers": len(custs),\n'
code += "        }\n"
code += "\n"
code += "    # ---- main chat method --------------------------------------------\n"
code += "    def chat(self, user_message):\n"
code += "        if not self.deepseek_key:\n"
code += '            return "DEEPSEEK_API_KEY missing in .env"\n'
code += "        metrics = self.get_metrics()\n"
code += "        context = self.rag\n"
code += "        if metrics.get(\"status\") == \"success\":\n"
code += "            m = metrics\n"
code += "            context += (\n"
code += '                "\\nCurrent store data (" + m["period"] + "): "\n'
code += '                "$" + str(m["total_sales"]) + " sales, "\n'
code += '                + str(m["orders"]) + " orders, "\n'
code += '                "AOV=$" + str(m["aov"]) + ", "\n'
code += '                + str(m["unique_customers"]) + " unique customers."\n'
code += "            )\n"
code += "        try:\n"
code += "            payload = {\n"
code += '                "model": "deepseek-chat",\n'
code += '                "messages": [\n'
code += '                    {"role": "system", "content": context},\n'
code += '                    {"role": "user", "content": user_message},\n'
code += "                ],\n"
code += '                "temperature": 0.7,\n'
code += '                "max_tokens": 4000,\n'
code += "            }\n"
code += "            r = requests.post(\n"
code += '                "https://api.deepseek.com/chat/completions",\n'
code += '                headers={\n'
code += '                    "Authorization": "Bearer " + self.deepseek_key,\n'
code += '                    "Content-Type": "application/json",\n'
code += "                },\n"
code += "                json=payload,\n"
code += "                timeout=60,\n"
code += "            )\n"
code += "            if r.status_code == 200:\n"
code += '                return r.json()["choices"][0]["message"]["content"]\n'
code += '            return "DeepSeek error " + str(r.status_code)\n'
code += "        except Exception as e:\n"
code += '            return "Connection error: " + str(e)\n'
code += "\n"
code += "\n"
code += "EcomCommander = ShopifyAIAgent\n"
code += "IntelligenceEngine = ShopifyAIAgent\n"

agent_path = os.path.join(BASE, "services", "shopify_ai_agent.py")
with open(agent_path, "w", encoding="utf-8") as f:
    f.write(code)
print("[OK] services/shopify_ai_agent.py")

print("")
print("Done. Now make TWO edits to afaq_attendance.py.")
