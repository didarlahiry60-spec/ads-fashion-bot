import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from google import genai
from google.genai import types
import database

logger = logging.getLogger(__name__)

# Fallback models in priority order for high availability
AVAILABLE_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite"
]

def get_system_instruction() -> str:
    store_name = os.getenv("STORE_NAME", "স্মার্ট গ্যাজেট ও লাইফস্টাইল শপ")
    fee_dhaka = os.getenv("DELIVERY_FEE_INSIDE_DHAKA", "80")
    fee_outside = os.getenv("DELIVERY_FEE_OUTSIDE_DHAKA", "150")
    bkash_no = os.getenv("BKASH_NUMBER", "01700000000 (Personal)")
    nagad_no = os.getenv("NAGAD_NUMBER", "01700000000 (Personal)")
    currency = os.getenv("CURRENCY", "৳")

    return f"""
You are the official 24/7 AI Customer Support & Sales Assistant for "{store_name}".
Your goal is to guide customers, help them discover products, take orders, provide order tracking, answer questions about policies, and escalate to human agents when requested.

CORE PERSONALITY & TONE:
1. Highly polite, welcoming, helpful, and professional. Use respectful greetings (e.g., "আসসালামু আলাইকুম / Welcome to {store_name}!").
2. Language Adaptation:
   - If the customer writes in Bengali (বাংলা), reply in sweet, professional Bengali.
   - If the customer writes in Banglish (e.g. "bhai ami akta smartwatch kinte chai"), reply in friendly, clear Banglish or simple Bengali matching their style.
   - If the customer writes in English, reply in fluent English.
3. Currency: All prices are in Bangladeshi Taka ({currency}).

STORE POLICIES & DELIVERY CHARGES:
- Delivery Fee: Inside Dhaka = {fee_dhaka}{currency}, Outside Dhaka = {fee_outside}{currency}.
- Delivery Time: Inside Dhaka 24-48 hours, Outside Dhaka 3-5 business days.
- Payment Methods:
  1. Cash on Delivery (COD) - Delivery charge ({fee_dhaka}/{fee_outside}{currency}) can be paid in advance via bKash/Nagad or full COD depending on customer preference.
  2. bKash / Nagad payment: bKash: {bkash_no}, Nagad: {nagad_no}.
- Return Policy: 7 days free replacement/warranty for manufacturing defects with unboxing video proof.

ORDER PLACEMENT RULES:
- Before placing an order via the `place_order` tool, collect or confirm:
  1. Products, quantity, and variant (color/size if applicable).
  2. Customer Full Name.
  3. Valid Phone Number (e.g., 01XXXXXXXXX).
  4. Delivery Address (with district/city so correct delivery fee is calculated).
  5. Payment Method (Cash on Delivery or bKash/Nagad).
- Always calculate and state the Total = (Products total + Delivery Fee).
- Once confirmed, execute `place_order`. Give the customer the Order ID (e.g. ORD-1001) and reassure them that their order is being processed!

TOOL USAGE:
- Whenever a user asks for products, search using `search_products`.
- Whenever a user gives order details, place the order using `place_order`.
- Whenever a user inquires about an existing order, check using `check_order_status`.
- If the customer asks to speak to an admin, owner, or human agent, or has an angry complaint, call `escalate_to_human_agent` and tell them a representative has been notified and will reply shortly.
"""

def get_tools_declarations() -> List[types.Tool]:
    search_products_func = types.FunctionDeclaration(
        name="search_products",
        description="Search products by keyword, name, or category from the store catalog.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or product name (e.g. 'smartwatch', 'earbuds', 'shirt')"},
                "category": {"type": "string", "description": "Optional category name"}
            }
        }
    )

    get_product_details_func = types.FunctionDeclaration(
        name="get_product_details",
        description="Retrieve full specifications, stock, price, and image URL for a given product ID.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The unique product ID (e.g. PROD-101)"}
            },
            "required": ["product_id"]
        }
    )

    place_order_func = types.FunctionDeclaration(
        name="place_order",
        description="Place a confirmed order in the database for the customer.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer's full name"},
                "customer_phone": {"type": "string", "description": "Customer's mobile phone number"},
                "delivery_address": {"type": "string", "description": "Complete shipping address"},
                "items_and_quantities": {"type": "string", "description": "Summary of products ordered (e.g. '1x PROD-101 Ultra Smartwatch (Black)')"},
                "total_price": {"type": "number", "description": "Total amount in BDT including delivery fee"},
                "payment_method": {"type": "string", "description": "Cash on Delivery or bKash or Nagad"},
                "trx_id": {"type": "string", "description": "Transaction ID if paid via bKash/Nagad"},
                "notes": {"type": "string", "description": "Any special customer instructions"}
            },
            "required": ["customer_name", "customer_phone", "delivery_address", "items_and_quantities", "total_price"]
        }
    )

    check_order_status_func = types.FunctionDeclaration(
        name="check_order_status",
        description="Check status and details of an order using Order ID (e.g. ORD-1001) or customer phone number.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "order_id_or_phone": {"type": "string", "description": "Order ID or Customer's Phone Number"}
            },
            "required": ["order_id_or_phone"]
        }
    )

    escalate_to_human_func = types.FunctionDeclaration(
        name="escalate_to_human_agent",
        description="Escalate conversation to human support admin when customer requests human help or has a grievance.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Brief reason for human escalation"}
            },
            "required": ["reason"]
        }
    )

    get_policy_func = types.FunctionDeclaration(
        name="get_store_policy",
        description="Get store policy on shipping rates, delivery timelines, return warranty, and payment methods.",
        parameters_json_schema={
            "type": "object",
            "properties": {}
        }
    )

    return [types.Tool(function_declarations=[
        search_products_func,
        get_product_details_func,
        place_order_func,
        check_order_status_func,
        escalate_to_human_func,
        get_policy_func
    ])]

class GeminiSalesAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
        self.client = genai.Client(api_key=self.api_key)
        self.tools = get_tools_declarations()
        self.system_instruction = get_system_instruction()

    async def _call_gemini_with_failover(
        self, 
        contents: List[types.Content], 
        config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        """Tries primary model, and falls back to alternatives if Google returns 503 or overload."""
        last_error = None
        for model_name in AVAILABLE_MODELS:
            try:
                logger.info(f"Calling Gemini with model '{model_name}'")
                response = await self.client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                return response
            except Exception as e:
                err_str = str(e)
                logger.warning(f"Model {model_name} encountered error: {err_str[:120]}. Trying fallback...")
                last_error = e
                # If 400 invalid argument or fatal client error, don't repeat bad request unless 404/503
                if "400 INVALID_ARGUMENT" in err_str:
                    raise e
        raise last_error

    async def execute_tool(
        self, 
        tool_name: str, 
        args: Dict[str, Any], 
        telegram_user_id: int
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        logger.info(f"Executing tool '{tool_name}' with args {args}")
        side_effect = None

        try:
            if tool_name == "search_products":
                query = args.get("query", "")
                cat = args.get("category", "")
                prods = await database.search_products(query=query, category=cat, limit=5)
                if prods:
                    side_effect = {"type": "products_found", "products": prods}
                    return {"found": True, "count": len(prods), "products": prods}, side_effect
                return {"found": False, "message": "No in-stock products matching the search query."}, side_effect

            elif tool_name == "get_product_details":
                pid = args.get("product_id", "")
                p = await database.get_product_by_id(pid)
                if p:
                    side_effect = {"type": "products_found", "products": [p]}
                    return {"found": True, "product": p}, side_effect
                return {"found": False, "message": f"Product with ID '{pid}' not found."}, side_effect

            elif tool_name == "place_order":
                order_id = await database.create_order(
                    telegram_user_id=telegram_user_id,
                    customer_name=args.get("customer_name", ""),
                    customer_phone=args.get("customer_phone", ""),
                    shipping_address=args.get("delivery_address", ""),
                    items_summary=args.get("items_and_quantities", ""),
                    total_amount=float(args.get("total_price", 0)),
                    payment_method=args.get("payment_method", "Cash on Delivery"),
                    trx_id=args.get("trx_id", ""),
                    notes=args.get("notes", "")
                )
                order_details = {
                    "order_id": order_id,
                    "customer_name": args.get("customer_name"),
                    "customer_phone": args.get("customer_phone"),
                    "shipping_address": args.get("delivery_address"),
                    "items": args.get("items_and_quantities"),
                    "total_price": args.get("total_price"),
                    "payment_method": args.get("payment_method"),
                    "trx_id": args.get("trx_id"),
                    "telegram_user_id": telegram_user_id
                }
                side_effect = {"type": "order_placed", "order": order_details}
                return {"success": True, "order_id": order_id, "status": "Pending", "message": "Order placed successfully."}, side_effect

            elif tool_name == "check_order_status":
                q = args.get("order_id_or_phone", "")
                orders = await database.get_order_by_id_or_phone(q)
                if orders:
                    return {"found": True, "orders": orders}, None
                return {"found": False, "message": f"No order found matching '{q}'."}, None

            elif tool_name == "escalate_to_human_agent":
                reason = args.get("reason", "Customer requested human support.")
                side_effect = {"type": "human_escalated", "reason": reason, "telegram_user_id": telegram_user_id}
                return {"success": True, "message": "Admin alerted. Human support representative will contact shortly."}, side_effect

            elif tool_name == "get_store_policy":
                fee_dhaka = os.getenv("DELIVERY_FEE_INSIDE_DHAKA", "80")
                fee_outside = os.getenv("DELIVERY_FEE_OUTSIDE_DHAKA", "150")
                return {
                    "delivery_charge_dhaka": f"{fee_dhaka} BDT",
                    "delivery_charge_outside_dhaka": f"{fee_outside} BDT",
                    "delivery_timeline": "1-2 days in Dhaka, 3-5 days outside Dhaka",
                    "payment": "Cash on delivery, bKash, Nagad",
                    "warranty": "7 days replacement warranty for manufacturing defects"
                }, None

            return {"error": f"Unknown tool: {tool_name}"}, None

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {"error": str(e)}, None

    async def chat(
        self, 
        telegram_user_id: int, 
        user_text: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        side_effects: List[Dict[str, Any]] = []

        history = await database.get_conversation_history(telegram_user_id, limit=6)

        contents: List[types.Content] = []
        for turn in history:
            role = "user" if turn["role"] == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=turn["content"])]
            ))

        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_text)]
        )
        contents.append(user_content)

        config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            tools=self.tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.4
        )

        try:
            response = await self._call_gemini_with_failover(contents, config)

            step_count = 0
            while response.function_calls and step_count < 3:
                step_count += 1
                fc = response.function_calls[0]
                tool_name = fc.name
                tool_args = fc.args or {}

                tool_result, side_effect = await self.execute_tool(tool_name, tool_args, telegram_user_id)
                if side_effect:
                    side_effects.append(side_effect)

                function_call_content = response.candidates[0].content
                contents.append(function_call_content)

                tool_response_content = types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(
                        name=tool_name,
                        response={"result": tool_result}
                    )]
                )
                contents.append(tool_response_content)

                response = await self._call_gemini_with_failover(contents, config)

            reply_text = response.text or "ধন্যবাদ! আমি কি আপনাকে আর কোনো বিষয়ে সহায়তা করতে পারি?"

            await database.save_message(telegram_user_id, "user", user_text)
            await database.save_message(telegram_user_id, "model", reply_text)

            return reply_text, side_effects

        except Exception as e:
            logger.error(f"Gemini API chat error: {e}", exc_info=True)
            fallback = "দুঃখিত, এই মুহূর্তে সার্ভারে সাময়িক ত্রুটি হয়েছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন অথবা সরাসরি আমাদের হেল্পলাইনে যোগাযোগ করুন।"
            return fallback, []
