"""
Database Schemas for E-commerce App

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
- User -> "user"
- Product -> "product"
- CartItem -> "cartitem"
- Order -> "order"
"""

from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr


class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="BCrypt hashed password")
    avatar_url: Optional[str] = Field(None, description="Profile image URL")
    is_active: bool = Field(True, description="Whether user is active")


class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in USD")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")
    image_url: Optional[str] = Field(None, description="Main product image URL")
    rating: float = Field(4.5, ge=0, le=5, description="Average rating")


class CartItem(BaseModel):
    user_id: str = Field(..., description="ID of the user who owns this cart item")
    product_id: str = Field(..., description="ID of the product")
    quantity: int = Field(1, ge=1, description="Quantity of the product")


class OrderItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int
    image_url: Optional[str] = None


class PaymentDetails(BaseModel):
    cardholder_name: str
    card_last4: str
    brand: str
    status: str = "succeeded"


class ShippingAddress(BaseModel):
    full_name: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str


class Order(BaseModel):
    user_id: str
    items: List[OrderItem]
    subtotal: float
    tax: float
    total: float
    payment: PaymentDetails
    shipping: ShippingAddress
    status: str = "processing"
