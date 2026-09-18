import csv
import datetime
import logging
import os
from typing import Any, Dict
import httpx

logger = logging.getLogger(__name__)

BACKUP_CSV_FILE = "orders_backup.csv"

def determine_zone(address: str, total_price: float, items_summary: str) -> str:
    """Determine whether the order is Inside Dhaka or Outside Dhaka."""
    addr_lower = (address or "").lower()
    dhaka_keywords = [
        "dhaka", "ঢাকা", "dhanmondi", "ধানমন্ডি", "mirpur", "মিরপুর", "uttara", "উত্তরা",
        "gulshan", "গুলশান", "banani", "বনানী", "mohammadpur", "মোহাম্মদপুর", "motijheel", "মতিঝিল",
        "badda", "বাড্ডা", "bashundhara", "বসুন্ধরা", "jatrabari", "যাত্রাবাড়ী", "rampura", "রামপুরা"
    ]
    for kw in dhaka_keywords:
        if kw in addr_lower:
            return "Inside Dhaka"
    return "Outside Dhaka"

def save_to_local_csv(order_dict: Dict[str, Any], zone: str):
    """Saves order to a clean local CSV file as an offline backup."""
    file_exists = os.path.exists(BACKUP_CSV_FILE)
    headers = [
        "Date & Time",
        "Order ID",
        "Customer Name",
        "Phone Number",
        "Address",
        "Zone",
        "Items & Size",
        "Total (BDT)",
        "Payment Method",
        "Status"
    ]
    
    try:
        with open(BACKUP_CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(headers)
            writer.writerow([
                order_dict.get("date_time", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                order_dict.get("order_id", ""),
                order_dict.get("customer_name", ""),
                str(order_dict.get("customer_phone", "")),
                order_dict.get("shipping_address", ""),
                zone,
                order_dict.get("items", ""),
                order_dict.get("total_price", ""),
                order_dict.get("payment_method", "Cash on Delivery"),
                order_dict.get("status", "Pending")
            ])
    except Exception as e:
        logger.error(f"Failed to write order backup CSV: {e}")

async def send_order_to_google_sheet(order_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sends the order to Google Sheets via Google Apps Script Webhook.
    Appends to 'All Orders' and either 'Inside Dhaka' or 'Outside Dhaka'.
    """
    webhook_url = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
    
    # Determine Zone
    zone = determine_zone(
        address=order_dict.get("shipping_address", ""),
        total_price=float(order_dict.get("total_price", 0)),
        items_summary=order_dict.get("items", "")
    )
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    payload = {
        "date_time": now_str,
        "order_id": order_dict.get("order_id"),
        "customer_name": order_dict.get("customer_name"),
        "customer_phone": order_dict.get("customer_phone"),
        "shipping_address": order_dict.get("shipping_address"),
        "zone": zone,
        "items": order_dict.get("items"),
        "total_price": order_dict.get("total_price"),
        "payment_method": order_dict.get("payment_method", "Cash on Delivery"),
        "status": "Pending"
    }
    
    # Save to local CSV backup regardless
    save_to_local_csv(payload, zone)
    
    if not webhook_url:
        logger.info("GOOGLE_SHEETS_WEBHOOK_URL is not configured. Saved to local CSV only.")
        return {
            "success": True, 
            "sheet_updated": False, 
            "zone": zone, 
            "message": "Saved to local database & CSV."
        }
    
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.post(webhook_url, json=payload)
            if res.status_code == 200:
                logger.info(f"Order {order_dict.get('order_id')} successfully posted to Google Sheet ({zone}).")
                return {"success": True, "sheet_updated": True, "zone": zone, "message": "Google Sheet updated successfully."}
            else:
                logger.warning(f"Google Sheet webhook returned status {res.status_code}: {res.text}")
                return {"success": False, "sheet_updated": False, "zone": zone, "message": f"HTTP {res.status_code}"}
    except Exception as e:
        logger.error(f"Error sending order to Google Sheet webhook: {e}")
        return {"success": False, "sheet_updated": False, "zone": zone, "message": str(e)}
