"""
services/shopify_profit.py
Shopify Profit Report Engine
Source of truth: Shopify API
Business rules: applied ON TOP for internal cost/profit only
"""

import os
import re
import csv
import io
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional


# ════════════════════════════════════════════════════════════════════════
# CONFIG — edit these to match your business
# ════════════════════════════════════════════════════════════════════════

class ShippingConfig:
    """Business shipping costs — applied ON TOP of Shopify values."""

    DUBAI_BASE        = 23
    UAE_BASE          = 23
    INTERNATIONAL_BASE = 85
    SAMEDAY_BASE      = 35

    DUBAI_VARIANTS    = {"dubai", "dubai emirate", "dxb"}

    # Keyword detection from Shopify shipping line title
    SAMEDAY_KEYWORDS  = ["same day", "sameday", "express", "today"]
    INTERNATIONAL_KW  = ["international", "global", "outside uae", "worldwide"]


class ChannelConfig:
    """Channel classification — lowercase matching."""
    POS_KEYWORDS      = ["pos", "shopify_pos", "web pos"]
    AMAZON_KEYWORDS   = ["amazon"]
    TRENDYOL_KEYWORDS = ["trendyol"]


class UpsellConfig:
    """Product-based upsell detection."""
    KEYWORDS = [
        "warranty", "packing", "protection plan", "add-on", "addon",
        "service fee", "markup", "upsell", "gift wrap", "installation",
        "extended", "extra", "premium pack",
    ]
    SKUS     = []
    # Set to product_type values if your store uses them
    TYPES    = []


class ReturnConfig:
    EXCLUDE_CANCELLED = True
    EXCLUDE_VOIDED    = True
    EXCLUDED_STATUSES = {"cancelled", "voided"}


# ════════════════════════════════════════════════════════════════════════
# PROFIT ENGINE
# ════════════════════════════════════════════════════════════════════════

class ProfitEngine:

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

    # ── TIMEZONE ──────────────────────────────────────────────────────

    @staticmethod
    def to_utc(date_str: str, end: bool = False) -> str:
        """Asia/Dubai (UTC+4) date → UTC ISO for Shopify API."""
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if end:
            dt = dt.replace(hour=23, minute=59, second=59)
        else:
            dt = dt.replace(hour=0, minute=0, second=0)
        dt -= timedelta(hours=4)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"

    # ── SHOPIFY FETCH (REST, paginated) ───────────────────────────────

    def fetch_orders(self, from_date: str, to_date: str) -> List[Dict]:
        if not self.ready():
            return []
        orders = []
        since_id = 0
        created_min = self.to_utc(from_date)
        created_max = self.to_utc(to_date, end=True)
        limit = 250

        while True:
            params = {
                "status": "any",
                "limit": str(limit),
                "created_at_min": created_min,
                "created_at_max": created_max,
                "since_id": str(since_id),
                "order": "id asc",
            }
            try:
                r = requests.get(
                    f"{self.base_url}/orders.json",
                    headers=self.headers, params=params, timeout=30,
                )
                if r.status_code == 429:
                    retry = float(r.headers.get("Retry-After", "2"))
                    time.sleep(retry)
                    continue
                if r.status_code != 200:
                    break
                batch = r.json().get("orders", [])
                if not batch:
                    break
                orders.extend(batch)
                since_id = batch[-1]["id"]
                if len(batch) < limit:
                    break
            except Exception:
                break
        return orders

    # ── SHIPPING DETECTION ────────────────────────────────────────────

    @staticmethod
    def _norm_city(city: str) -> str:
        if not city:
            return ""
        c = city.strip().lower()
        for v in ShippingConfig.DUBAI_VARIANTS:
            if v in c:
                return "dubai"
        return c

    @classmethod
    def detect_shipping_type(cls, order: Dict) -> str:
        addr  = order.get("shipping_address") or {}
        city  = cls._norm_city(addr.get("city", ""))
        lines = order.get("shipping_lines") or []
        title = " ".join(
            (sl.get("title") or "") for sl in lines
        ).lower()

        if city != "dubai" and city:
            return "UAE"
        if any(kw in title for kw in ShippingConfig.INTERNATIONAL_KW):
            return "International"
        if any(kw in title for kw in ShippingConfig.SAMEDAY_KEYWORDS):
            return "Dubai Same Day"
        if city == "dubai":
            return "Dubai Standard"
        return "Dubai Standard"

    @classmethod
    def calc_shipping_cost(cls, ship_type: str) -> float:
        return {
            "Dubai Standard":    ShippingConfig.DUBAI_BASE,
            "Dubai Same Day":    ShippingConfig.SAMEDAY_BASE,
            "UAE":               ShippingConfig.UAE_BASE,
            "International":     ShippingConfig.INTERNATIONAL_BASE,
        }.get(ship_type, ShippingConfig.DUBAI_BASE)

    # ── CHANNEL CLASSIFICATION ───────────────────────────────────────

    @classmethod
    def classify_channel(cls, order: Dict) -> str:
        tags = (order.get("tags") or "").lower()
        src  = (order.get("source_name") or "").lower()
        app  = str(order.get("app_id", "")).lower()
        combo = f"{src} {app} {tags}"

        for kw in ChannelConfig.POS_KEYWORDS:
            if kw in combo:
                return "POS"
        for kw in ChannelConfig.AMAZON_KEYWORDS:
            if kw in combo:
                return "Amazon"
        for kw in ChannelConfig.TRENDYOL_KEYWORDS:
            if kw in combo:
                return "Trendyol"
        if "web" in combo or "online_store" in combo:
            return "Online Store"
        return "Online Store"

    @classmethod
    def channel_group(cls, order: Dict) -> str:
        src = cls.classify_channel(order)
        return "Online" if src == "Online Store" else "POS-grouped"

    # ── UPSELL DETECTION ──────────────────────────────────────────────

    @classmethod
    def is_product_upsell(cls, item: Dict) -> bool:
        title = (item.get("title") or "").lower()
        sku   = (item.get("sku") or "").lower()
        ptype = (item.get("product_type") or "").lower()
        for kw in UpsellConfig.KEYWORDS:
            if kw in title or kw in sku or kw in ptype:
                return True
        for s in UpsellConfig.SKUS:
            if s.lower() in sku:
                return True
        return False

    # ── LINE ITEM PROCESSOR ───────────────────────────────────────────

    def process_line_item(
        self,
        item: Dict,
        order: Dict,
        refund_info: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Process ONE line item from ONE order.
        Shopify values are source of truth.
        Business rules applied ONLY for internal cost/profit.
        """
        qty     = int(item.get("quantity", 1))
        price   = float(item.get("price", 0))
        orig    = price * qty

        # Discount (from Shopify discount_allocations)
        disc = sum(
            float(da.get("amount", 0))
            for da in item.get("discount_allocations", [])
        )
        after_disc = orig - disc

        # Cost (Shopify cost if available)
        cost_per = item.get("cost")
        cost_total = None
        if cost_per is not None:
            try:
                cost_total = round(float(cost_per) * qty, 2)
            except (ValueError, TypeError):
                pass

        # Shipping (per order — distributed to line items equally)
        ship_lines = order.get("shipping_lines") or []
        ship_charged = sum(
            float(sl.get("price", 0)) for sl in ship_lines
        )
        ship_type    = self.detect_shipping_type(order)
        ship_cost    = self.calc_shipping_cost(ship_type)
        ship_upsell  = round(ship_charged - ship_cost, 2)

        # Product upsell (per line item)
        is_upsell = self.is_product_upsell(item)
        product_upsell = after_disc if is_upsell else 0.0

        # Returns
        ret_qty    = 0
        ret_amount = 0.0
        ret_date   = ""
        if refund_info:
            ret_qty    = refund_info.get("quantity", 0)
            ret_amount = refund_info.get("amount", 0.0)
            ret_date   = refund_info.get("date", "")[:10]

        # Sold (post-discount value)
        sold = after_disc

        # Profit per unit
        profit = None
        if cost_total is not None:
            profit = round(
                sold + product_upsell + ship_upsell
                - cost_total - ret_amount,
                2,
            )

        cust = order.get("customer") or {}
        cust_name = " ".join(filter(None, [
            cust.get("first_name", ""),
            cust.get("last_name", ""),
        ])).strip() or "Guest"
        addr = order.get("shipping_address") or {}

        return {
            "platform":            "Shopify",
            "channel_group":       self.channel_group(order),
            "channel_source":      self.classify_channel(order),
            "order_number":        order.get("order_number") or order.get("name"),
            "product_name":        item.get("title", ""),
            "sku":                 item.get("sku", ""),
            "order_date":          (order.get("created_at") or "")[:10],
            "fulfillment_date":    self._first_fulfillment(order),
            "qty":                 qty,
            "original_unit_price": round(price, 2),
            "item_price_after_disc": round(after_disc / qty, 2) if qty else 0,
            "discount_amount":     round(disc, 2),
            "sold_price_aed":      round(sold, 2),
            "shipping_charged":    round(ship_charged, 2),
            "shipping_cost":       round(ship_cost, 2),
            "shipping_upsell":     round(ship_upsell, 2),
            "shipping_type":       ship_type,
            "product_upsell":      round(product_upsell, 2),
            "expenses":            0.0,
            "returns":             round(ret_amount, 2),
            "return_date":         ret_date,
            "cost_price":          cost_total,
            "sold":                round(sold, 2),
            "profit":              profit,
            # extra
            "customer_name":       cust_name,
            "shipping_city":       addr.get("city", "") or "N/A",
        }

    @staticmethod
    def _first_fulfillment(order: Dict) -> str:
        ffs = order.get("fulfillments") or []
        if ffs:
            return (ffs[0].get("created_at") or "")[:10]
        return ""

    # ── REFUND MATCHING ──────────────────────────────────────────────────────

    @classmethod
    def _build_refund_map(cls, order: Dict) -> Dict[int, Dict]:
        """Map line_item_id → {quantity, amount, date}."""
        refund_map: Dict[int, Dict] = {}
        for refund in order.get("refunds") or []:
            rdate = (refund.get("created_at") or "")[:10]
            for rl in refund.get("refund_line_items") or []:
                lid = rl.get("line_item_id")
                if lid is not None:
                    existing = refund_map.get(lid, {
                        "quantity": 0, "amount": 0.0, "date": rdate
                    })
                    existing["quantity"] += int(rl.get("quantity", 0))
                    existing["amount"]  += float(rl.get("subtotal", 0))
                    if not existing.get("date"):
                        existing["date"] = rdate
                    refund_map[lid] = existing
        return refund_map

    # ── FULL ORDER PROCESSING ────────────────────────────────────────────────────

    def process_order(self, order: Dict) -> List[Dict]:
        """Returns one row PER line item."""
        if ReturnConfig.EXCLUDE_CANCELLED:
            if order.get("cancelled_at"):
                return []
        if order.get("financial_status") in ReturnConfig.EXCLUDED_STATUSES:
            return []

        refund_map = self._build_refund_map(order)
        rows = []
        for item in order.get("line_items", []):
            lid  = item.get("id")
            rmap = refund_map.get(lid)
            rows.append(self.process_line_item(item, order, rmap))
        return rows

    # ── AGGREGATION ───────────────────────────────────────────────────

    @staticmethod
    def _s(rows: List[Dict], key: str) -> float:
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals), 2)

    def build_report(self, from_date: str, to_date: str,
                     channel: str = "all") -> Dict:
        if not self.ready():
            return {"status": "not_configured"}

        raw = self.fetch_orders(from_date, to_date)
        all_rows: List[Dict] = []
        for o in raw:
            all_rows.extend(self.process_order(o))

        # Channel filter
        if channel == "online":
            rows = [r for r in all_rows if r["channel_group"] == "Online"]
        elif channel == "pos":
            rows = [r for r in all_rows if r["channel_group"] != "Online"]
        else:
            rows = all_rows

        online_rows = [r for r in all_rows if r["channel_group"] == "Online"]
        pos_rows    = [r for r in all_rows if r["channel_group"] != "Online"]
        cost_rows   = [r for r in rows if r["cost_price"] is not None]
        profit_rows = [r for r in rows if r["profit"] is not None]

        summary = {
            "total_orders":        len({r["order_number"] for r in rows}),
            "total_line_items":    len(rows),
            "gross_sales":         self._s(rows, "discount_amount") + self._s(rows, "sold_price_aed"),
            "discounts":           self._s(rows, "discount_amount"),
            "net_sales":           self._s(rows, "sold_price_aed"),
            "shipping_collected":  self._s(rows, "shipping_charged"),
            "shipping_cost":       self._s(rows, "shipping_cost"),
            "shipping_upsell":     self._s(rows, "shipping_upsell"),
            "product_upsell":      self._s(rows, "product_upsell"),
            "returns":             self._s(rows, "returns"),
            "total_cost":          self._s(cost_rows, "cost_price"),
            "total_expenses":      0.0,
            "total_profit":        self._s(profit_rows, "profit"),
            "cost_available":      bool(cost_rows),
            "profit_available":    bool(profit_rows),
        }

        return {
            "status":  "success",
            "period":  {"from": from_date, "to": to_date},
            "filter":  channel,
            "summary": summary,
            "online":  self._agg(online_rows),
            "pos":     self._agg(pos_rows),
            "rows":    rows,
            "raw_order_count": len(raw),
        }

    def _agg(self, rows: List[Dict]) -> Dict:
        cost = [r for r in rows if r.get("cost_price") is not None]
        prof = [r for r in rows if r.get("profit") is not None]
        return {
            "orders":           len({r["order_number"] for r in rows}),
            "line_items":       len(rows),
            "sold":             self._s(rows, "sold_price_aed"),
            "shipping_upsell":  self._s(rows, "shipping_upsell"),
            "product_upsell":   self._s(rows, "product_upsell"),
            "returns":          self._s(rows, "returns"),
            "cost":             self._s(cost, "cost_price"),
            "profit":           self._s(prof, "profit"),
        }

    # ── CSV EXPORT ────────────────────────────────────────────────────

    @staticmethod
    def to_csv(rows: List[Dict]) -> str:
        buf  = io.StringIO()
        cols = [
            "platform", "channel_group", "channel_source", "order_number",
            "product_name", "sku", "order_date", "fulfillment_date",
            "qty", "original_unit_price", "item_price_after_disc",
            "discount_amount", "sold_price_aed", "shipping_charged",
            "shipping_cost", "shipping_type", "shipping_upsell",
            "product_upsell", "expenses", "returns", "return_date",
            "cost_price", "sold", "profit",
        ]
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = dict(r)
            for k in ("cost_price", "profit"):
                if row.get(k) is None:
                    row[k] = "N/A"
            w.writerow(row)
        return buf.getvalue()
