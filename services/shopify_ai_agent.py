import os, requests
from datetime import datetime, timedelta


class ShopifyAIAgent:
    """Fetches Shopify data and answers with DeepSeek."""

    def __init__(self):
        self.deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
        self.store_url = os.environ.get("SHOPIFY_STORE_URL")
        self.token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        self.base_url = (
            f"https://{self.store_url}/admin/api/2025-01"
            if self.store_url else None
        )
        self.headers = (
            {"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"}
            if self.token else None
        )
        self._build_rag()

    # ---- RAG context baked in ----------------------------------------
    def _build_rag(self):
        self.rag = (
            "You are the senior Business Analyst for Afaq Alnaseem Trading LLC.\n"
            "Prioritize: Profitability, Customer Retention, Growth Efficiency.\n"
            "\n"
            "=== SALES & PROFITABILITY ===\n"
            "Net Profit Margin = (Revenue - COGS - Marketing - Shipping) / Revenue x 100\n"
            "AOV = total_sales / order_count\n"
            "Gross Profit Margin = (Revenue - COGS) / Revenue x 100\n"
            "\n"
            "=== CUSTOMER RETENTION ===\n"
            "CLV: use total_spent + orders_count per customer\n"
            "Returning Rate = customers_with_>1_order / total_unique x 100\n"
            "Cart Abandonment = abandoned / (abandoned + orders) x 100\n"
            "\n"
            "=== INVENTORY ===\n"
            "Sell-Through = units_sold / (units_sold + stock) x 100\n"
            "\n"
            "Always return clear numbers, time period, and recommendations.\n"
        )

    # ---- helpers -----------------------------------------------------
    def ready(self):
        return bool(self.deepseek_key and self.base_url and self.headers)

    def fetch_orders(self, days=30):
        if not self.ready():
            return {"error": "Shopify env vars missing"}
        try:
            since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
            url = self.base_url + "/orders.json?status=any&limit=250&created_at_min=" + since
            r = requests.get(url, headers=self.headers, timeout=20)
            if r.status_code == 200:
                return r.json().get("orders", [])
            return {"error": "HTTP " + str(r.status_code)}
        except Exception as e:
            return {"error": str(e)}

    def get_metrics(self):
        orders = self.fetch_orders()
        if isinstance(orders, dict) and "error" in orders:
            return {"status": "error", "message": orders["error"]}
        if not orders:
            return {"status": "no_data"}
        total = sum(float(o.get("total_price", 0)) for o in orders)
        count = len(orders)
        aov = round(total / count, 2) if count else 0
        custs = set()
        for o in orders:
            c = o.get("customer")
            if c and c.get("id"):
                custs.add(c["id"])
        return {
            "status": "success",
            "period": "last 30 days",
            "total_sales": round(total, 2),
            "orders": count,
            "aov": aov,
            "unique_customers": len(custs),
        }

    def get_last_order(self):
        orders = self.fetch_orders(days=30)
        if isinstance(orders, dict) and "error" in orders:
            return {"status": "error", "message": orders["error"]}
        if not orders:
            return {"status": "no_data"}
        try:
            sorted_orders = sorted(
                orders,
                key=lambda o: o.get("created_at", ""),
                reverse=True
            )
            top = sorted_orders[0]
            order_number = top.get("name") or top.get("order_number") or str(top.get("id"))
            created_at = top.get("created_at", "unknown")
            return {
                "status": "success",
                "order_number": order_number,
                "created_at": created_at,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ---- main chat method --------------------------------------------
    def chat(self, user_message):
        if not self.deepseek_key:
            return "DEEPSEEK_API_KEY missing in .env"
        low = (user_message or "").strip().lower()
        if "last order" in low or "order number" in low or "my last order" in low:
            last = self.get_last_order()
            if last.get("status") == "success":
                return (
                    f"Last order is {last['order_number']} (created at {last['created_at']}). "
                    "Use this number in Shopify orders for exact lookup."
                )
            if last.get("status") == "no_data":
                return "No orders found in the last 30 days."
            return f"Shopify order lookup error: {last.get('message', 'unknown')}"

        metrics = self.get_metrics()
        context = self.rag
        if metrics.get("status") == "success":
            m = metrics
            context += (
                "\nCurrent store data (" + m["period"] + "): "
                "$" + str(m["total_sales"]) + " sales, "
                + str(m["orders"]) + " orders, "
                "AOV=$" + str(m["aov"]) + ", "
                + str(m["unique_customers"]) + " unique customers."
            )
        try:
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": context},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.7,
                "max_tokens": 4000,
            }
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": "Bearer " + self.deepseek_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            return "DeepSeek error " + str(r.status_code)
        except Exception as e:
            return "Connection error: " + str(e)


EcomCommander = ShopifyAIAgent
IntelligenceEngine = ShopifyAIAgent
