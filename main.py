import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime
from database import db, create_document, get_documents
from bson import ObjectId
import bcrypt

app = FastAPI(title="E-commerce API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Utility helpers
# -----------------------------

def oid(id_str: str) -> ObjectId:
    if not ObjectId.is_valid(id_str):
        raise HTTPException(status_code=400, detail="Invalid id")
    return ObjectId(id_str)


def serialize_doc(doc: dict) -> dict:
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    # Remove sensitive fields if present
    if "password_hash" in doc:
        doc.pop("password_hash")
    return doc


# -----------------------------
# Models
# -----------------------------
class RegisterPayload(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class CartPayload(BaseModel):
    user_id: str
    product_id: str
    quantity: int = 1


class UpdateCartPayload(BaseModel):
    quantity: int


class ShippingAddress(BaseModel):
    full_name: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str


class PaymentDetails(BaseModel):
    cardholder_name: str
    card_number: str
    expiry: str
    cvc: str


class CheckoutPayload(BaseModel):
    user_id: str
    shipping: ShippingAddress
    payment: PaymentDetails


# -----------------------------
# Root & health
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "E-commerce API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:20]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -----------------------------
# Auth
# -----------------------------
@app.post("/api/auth/register")
def register(payload: RegisterPayload):
    users = db["user"]
    if users.find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    salt = bcrypt.gensalt()
    pw_hash = bcrypt.hashpw(payload.password.encode("utf-8"), salt).decode("utf-8")
    user_doc = {
        "name": payload.name,
        "email": payload.email,
        "password_hash": pw_hash,
        "avatar_url": f"https://api.dicebear.com/7.x/identicon/svg?seed={payload.email}",
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    return serialize_doc(user_doc)


@app.post("/api/auth/login")
def login(payload: LoginPayload):
    users = db["user"]
    user = users.find_one({"email": payload.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(payload.password.encode("utf-8"), user.get("password_hash", "").encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return serialize_doc(user)


# -----------------------------
# Products
# -----------------------------
@app.get("/api/products")
def list_products(q: Optional[str] = None, category: Optional[str] = None):
    products_col = db["product"]
    query = {"in_stock": True}
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"category": {"$regex": q, "$options": "i"}},
        ]
    if category:
        query["category"] = category
    items = [serialize_doc(p) for p in products_col.find(query).limit(100)]
    return {"items": items}


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    p = db["product"].find_one({"_id": oid(product_id)})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_doc(p)


# -----------------------------
# Cart
# -----------------------------
@app.get("/api/cart/{user_id}")
def get_cart(user_id: str):
    cart = []
    for item in db["cartitem"].find({"user_id": user_id}):
        product = db["product"].find_one({"_id": item["product_id"] if isinstance(item["product_id"], ObjectId) else oid(item["product_id"])})
        cart.append({
            "id": str(item["_id"]),
            "product_id": str(item["product_id"]) if isinstance(item["product_id"], ObjectId) else item["product_id"],
            "quantity": item.get("quantity", 1),
            "product": serialize_doc(product) if product else None,
        })
    return {"items": cart}


@app.post("/api/cart")
def add_to_cart(payload: CartPayload):
    # validate product
    product = db["product"].find_one({"_id": oid(payload.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    cart_col = db["cartitem"]
    existing = cart_col.find_one({"user_id": payload.user_id, "product_id": payload.product_id})
    if existing:
        cart_col.update_one({"_id": existing["_id"]}, {"$inc": {"quantity": payload.quantity}, "$set": {"updated_at": datetime.utcnow()}})
        updated = cart_col.find_one({"_id": existing["_id"]})
        return {"id": str(updated["_id"]), "quantity": updated.get("quantity", 1)}
    else:
        doc = {
            "user_id": payload.user_id,
            "product_id": payload.product_id,
            "quantity": payload.quantity,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        res = cart_col.insert_one(doc)
        return {"id": str(res.inserted_id), "quantity": payload.quantity}


@app.patch("/api/cart/{item_id}")
def update_cart_item(item_id: str, payload: UpdateCartPayload):
    if payload.quantity <= 0:
        db["cartitem"].delete_one({"_id": oid(item_id)})
        return {"deleted": True}
    db["cartitem"].update_one({"_id": oid(item_id)}, {"$set": {"quantity": payload.quantity, "updated_at": datetime.utcnow()}})
    item = db["cartitem"].find_one({"_id": oid(item_id)})
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    return {"id": item_id, "quantity": item.get("quantity", 1)}


@app.delete("/api/cart/{item_id}")
def delete_cart_item(item_id: str):
    db["cartitem"].delete_one({"_id": oid(item_id)})
    return {"deleted": True}


# -----------------------------
# Checkout / Orders
# -----------------------------
@app.post("/api/checkout")
def checkout(payload: CheckoutPayload):
    # Load cart
    items_cursor = list(db["cartitem"].find({"user_id": payload.user_id}))
    if not items_cursor:
        raise HTTPException(status_code=400, detail="Cart is empty")

    order_items = []
    subtotal = 0.0
    for item in items_cursor:
        product = db["product"].find_one({"_id": oid(item["product_id"]) if not isinstance(item["product_id"], ObjectId) else item["product_id"]})
        if not product:
            continue
        qty = int(item.get("quantity", 1))
        line_total = float(product.get("price", 0)) * qty
        subtotal += line_total
        order_items.append({
            "product_id": str(product["_id"]),
            "title": product.get("title"),
            "price": float(product.get("price", 0)),
            "quantity": qty,
            "image_url": product.get("image_url"),
        })

    tax = round(subtotal * 0.08, 2)
    total = round(subtotal + tax, 2)

    # Simulate payment success
    payment = {
        "cardholder_name": payload.payment.cardholder_name,
        "card_last4": payload.payment.card_number[-4:],
        "brand": "VISA" if payload.payment.card_number.startswith("4") else "CARD",
        "status": "succeeded",
    }

    order_doc = {
        "user_id": payload.user_id,
        "items": order_items,
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "total": total,
        "payment": payment,
        "shipping": payload.shipping.model_dump(),
        "status": "processing",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    res = db["order"].insert_one(order_doc)

    # Clear cart
    db["cartitem"].delete_many({"user_id": payload.user_id})

    order_doc["_id"] = res.inserted_id
    return serialize_doc(order_doc)


@app.get("/api/orders/{user_id}")
def user_orders(user_id: str):
    orders = [serialize_doc(o) for o in db["order"].find({"user_id": user_id}).sort("created_at", -1)]
    return {"items": orders}


# -----------------------------
# Seed sample products (idempotent)
# -----------------------------
@app.post("/api/seed")
def seed_products():
    products_col = db["product"]
    if products_col.count_documents({}) > 0:
        return {"seeded": True, "count": products_col.count_documents({})}

    sample_products = [
        {
            "title": "Aurora Wireless Headphones",
            "description": "Immersive sound with active noise cancellation and 40h battery.",
            "price": 129.99,
            "category": "Audio",
            "in_stock": True,
            "image_url": "https://images.unsplash.com/photo-1518441902113-c1d3d850f3f7?q=80&w=1600&auto=format&fit=crop",
            "rating": 4.7,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
        {
            "title": "Nebula Smartwatch",
            "description": "Track fitness, sleep, and notifications with a vibrant AMOLED display.",
            "price": 199.0,
            "category": "Wearables",
            "in_stock": True,
            "image_url": "https://images.unsplash.com/photo-1511739001486-6bfe10ce785f?q=80&w=1600&auto=format&fit=crop",
            "rating": 4.5,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
        {
            "title": "Stellar 4K Action Camera",
            "description": "Capture adventures in stunning 4K with stabilization and waterproof design.",
            "price": 259.0,
            "category": "Cameras",
            "in_stock": True,
            "image_url": "https://images.unsplash.com/photo-1519183071298-a2962be96f83?q=80&w=1600&auto=format&fit=crop",
            "rating": 4.6,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
        {
            "title": "Lumen Desk Lamp",
            "description": "Minimal LED lamp with adjustable color temperature and wireless charging.",
            "price": 59.99,
            "category": "Home",
            "in_stock": True,
            "image_url": "https://images.unsplash.com/photo-1505692794403-34d4982f88aa?q=80&w=1600&auto=format&fit=crop",
            "rating": 4.4,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
        {
            "title": "Echo Bluetooth Speaker",
            "description": "Rich, room-filling sound with deep bass in a compact design.",
            "price": 89.0,
            "category": "Audio",
            "in_stock": True,
            "image_url": "https://images.unsplash.com/photo-1495562569060-2eec283d3391?q=80&w=1600&auto=format&fit=crop",
            "rating": 4.3,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
    ]

    res = products_col.insert_many(sample_products)
    return {"seeded": True, "count": len(res.inserted_ids)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
