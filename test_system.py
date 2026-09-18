import asyncio
import os
import database
import sheets_sync
import gemini_agent

async def run_tests():
    print("🧪 Running System Verification Tests...")

    # 1. Initialize Database
    print("1. Initializing DB...")
    await database.init_db()
    await database.seed_products_from_json("catalog.json")

    # 2. Test Product Search
    print("2. Testing Product Search...")
    prods = await database.search_products(query="smartwatch")
    assert len(prods) > 0, "Product search failed"
    print(f"   Found: {prods[0]['name']} - Price: {prods[0]['price']} BDT")

    # 3. Test Order Creation
    print("3. Testing Order Creation...")
    order_id = await database.create_order(
        telegram_user_id=12345678,
        customer_name="রাকিবুল হাসান",
        customer_phone="01712345678",
        shipping_address="ধানমন্ডি ৩২, ঢাকা",
        items_summary="1x Ultra Smartwatch Series 9",
        total_amount=2530.0,
        payment_method="Cash on Delivery",
        trx_id=""
    )
    assert order_id.startswith("ORD-"), "Order ID generation failed"
    print(f"   Created Order ID: {order_id}")

    # 4. Test Order Lookup
    print("4. Testing Order Status Lookup...")
    orders = await database.get_order_by_id_or_phone(order_id)
    assert len(orders) > 0, "Order lookup failed"
    print(f"   Order Found: {orders[0]['id']} | Status: {orders[0]['status']}")

    # 5. Test Order Status Update
    print("5. Testing Order Status Update...")
    updated = await database.update_order_status(order_id, "Shipped")
    assert updated is True, "Status update failed"
    orders_after = await database.get_order_by_id_or_phone(order_id)
    assert orders_after[0]['status'] == "Shipped", "Status did not update"
    print(f"   Updated Status: {orders_after[0]['status']}")

    # 6. Test 2-Way Support Ticket Bridging
    print("6. Testing 2-Way Support Ticket Bridging...")
    await database.record_support_ticket(
        telegram_user_id=12345678,
        user_name="রাকিবুল হাসান",
        admin_message_id=998877
    )
    retrieved_user = await database.get_user_id_by_admin_message(998877)
    assert retrieved_user == 12345678, "Support ticket user bridging failed"
    print(f"   Bridge Verified: Admin Msg 998877 -> Customer ID {retrieved_user}")

    # 7. Test Local Catalog Sync
    print("7. Testing Local Catalog Sync...")
    sync_res = await sheets_sync.sync_from_local_json("catalog.json")
    assert sync_res["success"] is True, "Catalog sync failed"
    print(f"   Sync Result: {sync_res['message']}")

    # 8. Test Agent Tool Execution
    print("8. Testing Agent Tool Execution logic...")
    os.environ["STORE_NAME"] = "টেস্ট শপ"
    agent = gemini_agent.GeminiSalesAgent.__new__(gemini_agent.GeminiSalesAgent)
    
    # Test execute_tool search_products
    tool_res, side_effect = await agent.execute_tool("search_products", {"query": "earbuds"}, 12345678)
    assert tool_res["found"] is True, "Tool search_products failed"
    print(f"   Tool search_products passed: {tool_res['count']} items found")

    # Test execute_tool place_order
    tool_order, order_effect = await agent.execute_tool("place_order", {
        "customer_name": "তানভীর আহমেদ",
        "customer_phone": "01811223344",
        "delivery_address": "মিরপুর ১০, ঢাকা",
        "items_and_quantities": "1x Noise Cancelling Earbuds",
        "total_price": 1730
    }, 12345678)
    assert tool_order["success"] is True, "Tool place_order failed"
    print(f"   Tool place_order passed: {tool_order['order_id']}")

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🚀")

if __name__ == "__main__":
    asyncio.run(run_tests())
