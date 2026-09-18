import csv
import io
import logging
import os
from typing import Dict, Any, List
import httpx
import database

logger = logging.getLogger(__name__)

async def sync_from_csv_url(csv_url: str) -> Dict[str, Any]:
    """
    Downloads CSV from Google Sheets published URL and updates SQLite database.
    Required CSV headers: id, name, category, price, description, stock, image_url
    """
    if not csv_url or not csv_url.strip():
        return {"success": False, "message": "Google Sheets CSV URL প্রদান করা হয়নি।"}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(csv_url.strip())
            response.raise_for_status()
            
            content = response.content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            
            products: List[Dict[str, Any]] = []
            for row in reader:
                p_id = row.get("id") or row.get("ID")
                p_name = row.get("name") or row.get("Name")
                if not p_id or not p_name:
                    continue
                
                try:
                    price = float(row.get("price") or row.get("Price") or 0)
                except ValueError:
                    price = 0.0
                    
                try:
                    stock = int(row.get("stock") or row.get("Stock") or 0)
                except ValueError:
                    stock = 0
                    
                products.append({
                    "id": p_id.strip(),
                    "name": p_name.strip(),
                    "category": (row.get("category") or row.get("Category") or "General").strip(),
                    "price": price,
                    "description": (row.get("description") or row.get("Description") or "").strip(),
                    "stock": stock,
                    "image_url": (row.get("image_url") or row.get("Image_URL") or "").strip()
                })
            
            if not products:
                return {"success": False, "message": "CSV ফাইলে কোনো বৈধ প্রোডাক্ট পাওয়া যায়নি।"}
            
            conn = await database.get_db_connection()
            try:
                for p in products:
                    await conn.execute("""
                        INSERT INTO products (id, name, category, price, description, stock, image_url, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(id) DO UPDATE SET
                            name=excluded.name,
                            category=excluded.category,
                            price=excluded.price,
                            description=excluded.description,
                            stock=excluded.stock,
                            image_url=excluded.image_url,
                            updated_at=CURRENT_TIMESTAMP
                    """, (p["id"], p["name"], p["category"], p["price"], p["description"], p["stock"], p["image_url"]))
                await conn.commit()
            finally:
                await conn.close()
                
            return {
                "success": True, 
                "count": len(products),
                "message": f"গুগল শিট থেকে সফলভাবে {len(products)} টি প্রোডাক্ট সিঙ্ক করা হয়েছে।"
            }
    except Exception as e:
        logger.error(f"Error syncing from Google Sheets CSV: {e}")
        return {"success": False, "message": f"সিঙ্ক ব্যর্থ হয়েছে: {str(e)}"}

async def sync_from_local_json(json_path: str = "catalog.json") -> Dict[str, Any]:
    try:
        await database.seed_products_from_json(json_path)
        all_prods = await database.get_all_products(100)
        return {
            "success": True,
            "count": len(all_prods),
            "message": f"catalog.json থেকে সফলভাবে {len(all_prods)} টি প্রোডাক্ট সিঙ্ক করা হয়েছে।"
        }
    except Exception as e:
        logger.error(f"Error syncing from local json: {e}")
        return {"success": False, "message": f"লোকাল সিঙ্ক ব্যর্থ: {str(e)}"}
