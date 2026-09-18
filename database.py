import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
import aiosqlite

DB_FILE = os.getenv("DB_FILE", "store.db")
logger = logging.getLogger(__name__)

async def get_db_connection() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_FILE)
    conn.row_factory = aiosqlite.Row
    return conn

async def init_db():
    """Create all necessary tables if they do not exist."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                price REAL NOT NULL,
                description TEXT,
                stock INTEGER DEFAULT 0,
                image_url TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                telegram_user_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                shipping_address TEXT NOT NULL,
                items_summary TEXT NOT NULL,
                total_amount REAL NOT NULL,
                payment_method TEXT NOT NULL,
                trx_id TEXT DEFAULT '',
                status TEXT DEFAULT 'Pending',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                user_name TEXT,
                admin_message_id INTEGER UNIQUE,
                status TEXT DEFAULT 'Open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    logger.info("Database initialized successfully.")

async def seed_products_from_json(json_path: str = "catalog.json"):
    """Seeds the products table from catalog.json if table is empty or updates products."""
    if not os.path.exists(json_path):
        return
    with open(json_path, "r", encoding="utf-8-sig") as f:
        products = json.load(f)
    
    async with aiosqlite.connect(DB_FILE) as db:
        for p in products:
            await db.execute("""
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
            """, (
                p["id"],
                p["name"],
                p.get("category", "General"),
                float(p["price"]),
                p.get("description", ""),
                int(p.get("stock", 0)),
                p.get("image_url", "")
            ))
        await db.commit()
    logger.info(f"Loaded {len(products)} products from {json_path}")

async def search_products(query: str = "", category: str = "", limit: int = 5) -> List[Dict[str, Any]]:
    """Search products by title/description or category."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        sql = "SELECT * FROM products WHERE stock > 0"
        params = []
        
        if query:
            sql += " AND (name LIKE ? OR description LIKE ? OR category LIKE ?)"
            term = f"%{query.strip()}%"
            params.extend([term, term, term])
            
        if category:
            sql += " AND category LIKE ?"
            params.append(f"%{category.strip()}%")
            
        sql += " ORDER BY id LIMIT ?"
        params.append(limit)
        
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_product_by_id(product_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products WHERE id = ?", (product_id.strip(),)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_all_products(limit: int = 25) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products ORDER BY id LIMIT ?", (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_stock(product_id: str, quantity: int) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT stock FROM products WHERE id = ?", (product_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False
            current_stock = row["stock"]
            new_stock = max(0, current_stock - quantity)
            await db.execute("UPDATE products SET stock = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_stock, product_id))
            await db.commit()
            return True

async def generate_order_id() -> str:
    """Generates ORD-XXXX sequence."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) as count FROM orders") as cursor:
            row = await cursor.fetchone()
            count = row["count"] + 1001
            return f"ORD-{count}"

async def create_order(
    telegram_user_id: int,
    customer_name: str,
    customer_phone: str,
    shipping_address: str,
    items_summary: str,
    total_amount: float,
    payment_method: str = "Cash on Delivery",
    trx_id: str = "",
    notes: str = ""
) -> str:
    order_id = await generate_order_id()
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO orders (id, telegram_user_id, customer_name, customer_phone, shipping_address, items_summary, total_amount, payment_method, trx_id, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (
            order_id,
            telegram_user_id,
            customer_name,
            customer_phone,
            shipping_address,
            items_summary,
            total_amount,
            payment_method,
            trx_id,
            notes
        ))
        await db.commit()
    return order_id

async def get_order_by_id_or_phone(query: str) -> List[Dict[str, Any]]:
    clean_query = query.strip().upper()
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM orders 
            WHERE UPPER(id) = ? OR customer_phone LIKE ? OR telegram_user_id = ?
            ORDER BY created_at DESC LIMIT 3
        """, (clean_query, f"%{clean_query}%", clean_query if clean_query.isdigit() else 0)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_recent_orders(limit: int = 10) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def update_order_status(order_id: str, new_status: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("UPDATE orders SET status = ? WHERE UPPER(id) = ?", (new_status.capitalize(), order_id.strip().upper()))
        await db.commit()
        return cursor.rowcount > 0

# Support bridge for 2-way admin-customer communication
async def record_support_ticket(telegram_user_id: int, user_name: str, admin_message_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO support_tickets (telegram_user_id, user_name, admin_message_id, status)
            VALUES (?, ?, ?, 'Open')
        """, (telegram_user_id, user_name, admin_message_id))
        await db.commit()

async def get_user_id_by_admin_message(admin_message_id: int) -> Optional[int]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT telegram_user_id FROM support_tickets WHERE admin_message_id = ?", (admin_message_id,)) as cursor:
            row = await cursor.fetchone()
            return row["telegram_user_id"] if row else None

# Chat history memory
async def save_message(telegram_user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            INSERT INTO conversations (telegram_user_id, role, content)
            VALUES (?, ?, ?)
        """, (telegram_user_id, role, content))
        await db.commit()

async def get_conversation_history(telegram_user_id: int, limit: int = 8) -> List[Dict[str, str]]:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT role, content FROM conversations 
            WHERE telegram_user_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (telegram_user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            history = [dict(row) for row in reversed(rows)]
            return history

async def clear_user_history(telegram_user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM conversations WHERE telegram_user_id = ?", (telegram_user_id,))
        await db.commit()

