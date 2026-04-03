"""
services/shopify_report.py
Shopify Sales Report — Online vs POS-grouped
Reads credentials from os.environ (populated by main app from .env)
"""

import os
import csv
import io
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List


# ══════════════════════════════════════════════════════════════════════
# CONFIG — edit these to match your business
# ══════════════════════════════════════════════════════════════════════

class Config:
    # Channel classification — lowercase matching
    POS_CHANNELS     = ["pos", "shopify_pos", "web pos"]
    AMAZON_CHANNELS  = ["amazon"]
    TRENDYOL_CHANNELS = ["trendyol"]

    # Upsell detection
    UPSELL_KEYWORDS = [
        "warranty", "packing", "protection plan",
        "add-on", "addon", "service fee",
        "markup", "upsell", "gift wrap",
        "installation", "extended",
    ]
    UPSELL_SKUS = []

    # Shipping — AED
    DUBAI_FREE_THRESHOLD  = 99
    DUBAI_CHARGE          = 12
    OTHER_CITIES_CHARGE   = 12

    DUBAI_VARIANTS = {"dubai", "dubai emirate", "dxb"}
    OTHER_VARIANTS = set()          # add if needed

    EXCLUDED_STATUSES = {"cancelled", "voided"}


# ══════════════════════════════════════════════════════════════════════
# REPORT ENGINE
# ══════════════════════════════════════════════════════════════════════

class ShopifyReport:

    def __init__(self):
        self.store_url = os.environ.get("SHOPIFY_STORE_URL", "")
        self.token     = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
        self.base_url  = f"https://{self.store_url}/admin/api/2024-10" if self.store_url else ""
        self.headers   = {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
        } if self.token else {}

    def ready(self) -> bool:
        return bool(self.store_url and self.token)

    # ── dates ────────────────────────────────────────────────────────

    @staticmethod
    def _to_ts(date_str: str, end: bool = False) -> str:
        """date string → ISO 8601 for Asia/Dubai (UTC+4)."""
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if end:
            dt = dt.replace(hour=23, minute=59, second=59)
        else:
            dt = dt.replace(hour=0, minute=0, second=0)
        dt -= timedelta(hours=4)            # Dubai → UTC
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"

    # ── channel classification ───────────────────────────────────────

    @classmethod
    def _classify(cls, order: Dict) -> str:
        # tag-based (fastest check)
        tags = (order.get("tags") or "").lower()
        if any(t in tags for t in cls._list("amazon")):
            return "POS-grouped"
        if any(t in tags for t in cls._list("trendyol")):
            return "POS-grouped"
        if "pos" in tags:
            return "POS-grouped"

        # source_name / app_id
        src = (order.get("source_name") or "").lower()
        app = str(order.get("app_id", "")).lower()
        combined = f"{src} {app}"
        for kw in Config.POS_CHANNELS + Config.AMAZON_CHANNELS + Config.TRENDYOL_CHANNELS:
            if kw in combined:
                return "POS-grouped"
        if "web" in combined or "online_store" in combined:
            return "Online"

        return "Online"          # default

    @staticmethod
    def _list(kind: str) -> list:
        if kind == "amazon":
            return Config.AMAZON_CHANNELS
        if kind == "trendyol":
            return Config.TRENDYOL_CHANNELS
        return Config.POS_CHANNELS

    @classmethod
    def _channel_source(cls, order: Dict) -> str:
        src = (order.get("source_name") or "unknown").lower()
        tags = (order.get("tags") or "").lower()
        if any(k in src or k in tags for k in Config.AMAZON_CHANNELS):
            return "Amazon"
        if any(k in src or k in tags for k in Config.TRENDYOL_CHANNELS):
            return "Trendyol"
        if any(k in src for k in Config.POS_CHANNELS):
            return "POS"
        return "Online Store"

    # ── upsell detection ─────────────────────────────────────────────

    @classmethod
    def _is_upsell(cls, item: Dict) -> bool:
        title = (item.get("title") or "").lower()
        sku   = (item.get("sku") or "").lower()
        ptype = (item.get("product_type") or "").lower()
        for kw in Config.UPSELL_KEYWORDS:
            if kw in title or kw in sku or kw in ptype:
                return True
        for s in Config.UPSELL_SKUS:
            if s.lower() in sku:
                return True
        return False

    # ── shipping (business rules) ────────────────────────────────────

    @classmethod
    def _shipping_charge(cls, city: str, net_sales: float) -> float:
        city_norm = cls._norm_city(city)
        if city_norm in Config.DUBAI_VARIANTS:
            return 0.0 if net_sales > Config.DUBAI_FREE_THRESHOLD else float(Config.DUBAI_CHARGE)
        return float(Config.OTHER_CITIES_CHARGE)

    @staticmethod
    def _norm_city(city: str) -> str:
        if not city:
            return ""
        c = city.strip().lower()
        for v in Config.DUBAI_VARIANTS:
            if v in c:
                return "dubai"
        return c

    # ── single order processor ───────────────────────────────────────

    def _process_order(self, o: Dict) -> Dict[str, Any]:
        cg = self._classify(o)
        cs = self._channel_source(o)

        cust = o.get("customer") or {}
        cust_name = " ".join(filter(None, [
            cust.get("first_name", ""),
            cust.get("last_name", ""),
        ])).strip() or "Guest"

        addr   = (o.get("shipping_address") or {})
        city   = addr.get("city", "") or ""

        gross, cogs, disc, upsell = 0.0, 0.0, 0.0, 0.0

        for item in o.get("line_items", []):
            price = float(item.get("price", 0))
            qty   = int(item.get("quantity", 1))
            gross += price * qty

            item_cogs = item.get("cost")
            if item_cogs:
                try:
                    cogs += float(item_cogs) * qty
                except (ValueError, TypeError):
                    pass

            for da in item.get("discount_allocations", []):
                disc += float(da.get("amount", 0))

            if self._is_upsell(item):
                item_total = float(item.get("original_line_price",
                                 price * qty))
                upsell += item_total - sum(
                    float(da.get("amount", 0))
                    for da in item.get("discount_allocations", [])
                )

        net_sales    = gross - disc
        ship_charge  = self._shipping_charge(city, net_sales)
        final_sales  = net_sales + upsell + ship_charge
        gp           = round(final_sales - cogs, 2) if cogs else None

        return {
            "order_number":    o.get("order_number") or o.get("name"),
            "order_date":      o.get("created_at", "")[:19],
            "channel_group":   cg,
            "channel_source":  cs,
            "customer_name":   cust_name,
            "shipping_city":   city or "N/A",
            "gross_sales":     round(gross, 2),
            "discounts":       round(disc, 2),
            "net_sales":       round(net_sales, 2),
            "upsell":          round(upsell, 2),
            "shipping_charge": round(ship_charge, 2),
            "final_sales":     round(final_sales, 2),
            "cogs":            round(cogs, 2) if cogs else None,
            "gross_profit":    gp,
        }

    # ── fetch orders (paginated) ─────────────────────────────────────

    def fetch_orders(self, from_date: str, to_date: str) -> List[Dict]:
        if not self.ready():
            return []

        created_min = self._to_ts(from_date)
        created_max = self._to_ts(to_date, end=True)
        orders: list[Dict] = []
        url = (f"{self.base_url}/orders.json"
               f"?status=any&limit=250"
               f"&created_at_min={created_min}"
               f"&created_at_max={created_max}")

        while url:
            try:
                r = requests.get(url, headers=self.headers, timeout=30)
                if r.status_code != 200:
                    break
                body = r.json()
                orders.extend(body.get("orders", []))

                # pagination via Link header
                link = r.headers.get("Link", "")
                nxt  = None
                for part in link.split(","):
                    if 'rel="next"' in part:
                        nxt = part.split("<")[1].split(">")[0]
                url = nxt

            except Exception:
                break

        return orders

    # ── full report ──────────────────────────────────────────────────

    def generate_report(self, from_date: str, to_date: str,
                        channel: str = "all") -> Dict[str, Any]:

        raw_orders = self.fetch_orders(from_date, to_date)
        processed  = [self._process_order(o) for o in raw_orders]

        if channel == "online":
            filtered = [o for o in processed if o["channel_group"] == "Online"]
        elif channel == "pos":
            filtered = [o for o in processed if o["channel_group"] == "POS-grouped"]
        else:
            filtered = processed

        def _sum(key, items):
            return round(sum(o[key] for o in items if o[key] is not None), 2)

        def _non_none(key, items):
            return [o for o in items if o[key] is not None]

        online = [o for o in processed if o["channel_group"] == "Online"]
        pos    = [o for o in processed if o["channel_group"] == "POS-grouped"]
        cogs_filtered = _non_none("cogs", filtered)

        return {
            "status": "success",
            "period": {"from": from_date, "to": to_date},
            "channel_filter": channel,
            "summary": {
                "total_orders":        len(filtered),
                "gross_sales":         _sum("gross_sales", filtered),
                "discounts":           _sum("discounts", filtered),
                "net_sales":           _sum("net_sales", filtered),
                "upsell":              _sum("upsell", filtered),
                "shipping_charged":    _sum("shipping_charge", filtered),
                "final_sales":         _sum("final_sales", filtered),
                "cogs_total":          _sum("cogs", cogs_filtered),
                "gross_profit":        _sum("gross_profit", cogs_filtered),
                "cogs_available":      bool(cogs_filtered),
            },
            "online": {
                "total_orders":    len(online),
                "gross_sales":     _sum("gross_sales", online),
                "net_sales":       _sum("net_sales", online),
                "upsell":          _sum("upsell", online),
                "shipping_charged":_sum("shipping_charge", online),
                "final_sales":     _sum("final_sales", online),
            },
            "pos": {
                "total_orders":    len(pos),
                "gross_sales":     _sum("gross_sales", pos),
                "net_sales":       _sum("net_sales", pos),
                "upsell":          _sum("upsell", pos),
                "shipping_charged":_sum("shipping_charge", pos),
                "final_sales":     _sum("final_sales", pos),
            },
            "orders": filtered,
        }

    # ── CSV export ───────────────────────────────────────────────────

    def to_csv(self, orders: List[Dict]) -> str:
        buf = io.StringIO()
        fields = [
            "order_number", "order_date", "channel_group",
            "channel_source", "customer_name", "shipping_city",
            "gross_sales", "discounts", "net_sales",
            "upsell", "shipping_charge", "final_sales",
            "cogs", "gross_profit",
        ]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for o in orders:
            row = dict(o)
            for k in ("cogs", "gross_profit"):
                if row.get(k) is None:
                    row[k] = "N/A"
            w.writerow(row)
        return buf.getvalue()
