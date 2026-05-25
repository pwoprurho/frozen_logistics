from fastapi import FastAPI, HTTPException, Depends, status, File, UploadFile
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import sqlalchemy
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, JSON, Boolean, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import uvicorn
import requests
import uuid
import os
import shutil
from typing import List, Optional

from dotenv import load_dotenv
import logging

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("arctic_logistics")

# --- Configuration & Security ---
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "DEVELOPMENT_FALLBACK_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
FLW_SECRET_KEY = os.getenv("FLW_SECRET_KEY", "FLWSECK_TEST-YOUR-KEY-HERE")
FLW_BASE_URL = "https://api.flutterwave.com/v3"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Database Setup ---
SQLALCHEMY_DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL", "sqlite:///./arctic_logistics.db")
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String)
    fullname = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    wallet_balance = Column(Float, default=0.0)
    is_online = Column(Boolean, default=False)

class ProductDB(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price_per_kg = Column(Float)
    description = Column(String)
    image = Column(String)
    video = Column(String, nullable=True)
    is_featured = Column(Boolean, default=False)
    category = Column(String, default="General")

class WarehouseDB(Base):
    __tablename__ = "warehouses"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    city = Column(String)

class StockDB(Base):
    __tablename__ = "stocks"
    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Float)

class ReviewDB(Base):
    __tablename__ = "reviews"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    courier_id = Column(Integer, ForeignKey("users.id"))
    rating = Column(Integer) # 1-5
    comment = Column(String, nullable=True)

class PackageDB(Base):
    __tablename__ = "packages"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price = Column(Float)
    description = Column(String)
    city = Column(String)
    is_featured = Column(Boolean, default=False)

class OrderDB(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    tx_ref = Column(String, unique=True)
    tx_id = Column(String, nullable=True)
    customer_name = Column(String)
    city = Column(String)
    amount = Column(Float)
    status = Column(String, default="received")
    items = Column(JSON)
    courier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    proof_pickup = Column(String, nullable=True)
    proof_delivery = Column(String, nullable=True)
    delivery_pin = Column(String, nullable=True)
    preparation_duration = Column(Integer, nullable=True)
    rejection_reason = Column(String, nullable=True)
    payout_amount = Column(Float, default=0.0)

class TelemetryDB(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    hub_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    temp = Column(Float) # Celsius
    humidity = Column(Float)
    timestamp = Column(String, default=lambda: datetime.now().isoformat())

class RestockRequestDB(Base):
    __tablename__ = "restock_requests"
    id = Column(Integer, primary_key=True, index=True)
    seller_name = Column(String)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    scheduled_date = Column(String)
    items = Column(JSON) # List of {product_id, kg}
    status = Column(String, default="pending")

Base.metadata.create_all(bind=engine)

# --- App Initialization ---
app = FastAPI(title="Arctic Logistics API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Dependencies ---
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None: raise HTTPException(status_code=401)
    except JWTError: raise HTTPException(status_code=401)
    user = db.query(UserDB).filter(UserDB.email == email).first()
    if not user: raise HTTPException(status_code=401)
    return user

# --- Auth Helper Functions ---
def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- API ROUTES (MUST COME BEFORE STATIC MOUNT) ---

@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}

@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).all()

@app.get("/packages/{city}")
def get_packages(city: str, db: Session = Depends(get_db)):
    return db.query(PackageDB).filter(PackageDB.city.ilike(city)).all()

@app.get("/stock/{city}")
def get_stock(city: str, db: Session = Depends(get_db)):
    whs = db.query(WarehouseDB).filter(WarehouseDB.city.ilike(city)).all()
    stock_dict = {}
    for wh in whs:
        stocks = db.query(StockDB).filter(StockDB.warehouse_id == wh.id).all()
        for s in stocks:
            stock_dict[s.product_id] = stock_dict.get(s.product_id, 0) + s.quantity
    return {"city": city, "stock": stock_dict}

@app.post("/init-payment")
def init_payment(order_data: dict, db: Session = Depends(get_db)):
    import random
    total_amount = 0
    total_weight = 0
    tx_ref = str(uuid.uuid4())
    for item in order_data["items"]:
        prod = db.query(ProductDB).filter(ProductDB.id == item["product_id"]).first()
        total_amount += prod.price_per_kg * item["kg"]
        total_weight += item["kg"]
    
    delivery_pin = f"{random.randint(1000, 9999)}"
    payout_amount = 1500.0 + (total_weight * 200.0)
    
    new_order = OrderDB(
        tx_ref=tx_ref,
        customer_name=order_data["customer_name"],
        city=order_data["city"],
        amount=total_amount,
        items=order_data["items"],
        delivery_pin=delivery_pin,
        payout_amount=payout_amount,
        status="pending"
    )
    db.add(new_order)
    db.commit()
    return {"status": "success", "link": f"/verify-payment?status=successful&tx_ref={tx_ref}&transaction_id=mock_{uuid.uuid4().hex[:8]}"}

@app.get("/verify-payment")
def verify_payment(transaction_id: str, status: str, tx_ref: str, db: Session = Depends(get_db)):
    if status != "successful": return {"status": "failed"}
    order = db.query(OrderDB).filter(OrderDB.tx_ref == tx_ref).first()
    if not order: raise HTTPException(status_code=404)

    # --- SOLID MOCK BYPASS: NEVER CALL FLW API FOR MOCK IDS ---
    if transaction_id.startswith("mock_"):
        order.status = "received"
        order.tx_id = transaction_id
        # Deduct Stock with Validation
        whs = db.query(WarehouseDB).filter(WarehouseDB.city.ilike(order.city)).all()
        hub_ids = [wh.id for wh in whs]
        
        for item in order.items:
            rem = item["kg"]
            product = db.query(ProductDB).filter(ProductDB.id == item["product_id"]).first()
            
            # Check availability first
            total_available = db.query(sqlalchemy.func.sum(StockDB.quantity)).filter(
                StockDB.warehouse_id.in_(hub_ids), 
                StockDB.product_id == item["product_id"]
            ).scalar() or 0
            
            if total_available < rem:
                logger.error(f"Stock shortage for {product.name} in {order.city}. Required: {rem}, Available: {total_available}")
                order.status = "error_shortage"
                db.commit()
                return {"status": "error", "detail": f"Insufficient stock for {product.name}"}

            for wh in whs:
                stock = db.query(StockDB).filter(StockDB.warehouse_id == wh.id, StockDB.product_id == item["product_id"]).with_for_update().first()
                if stock:
                    take = min(stock.quantity, rem)
                    stock.quantity -= take
                    rem -= take
                    if rem <= 0: break
        
        logger.info(f"Payment verified and stock deducted for Order {order.tx_ref}")
        db.commit()
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/track.html?ref={tx_ref}")

    return {"status": "error", "detail": "Live payments not configured"}

from fastapi import File, UploadFile
import shutil

@app.post("/upload-media")
async def upload_media(file: UploadFile = File(...)):
    UPLOAD_DIR = "C:/Users/Administrator/frozen_logistics/frontend/uploads"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"uploads/{filename}"}

@app.post("/add-product")
async def add_product(data: dict, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(status_code=403)
    p = data["product"]
    new_prod = ProductDB(
        id=int(datetime.now().timestamp()),
        name=p["name"],
        price_per_kg=p["price_per_kg"],
        description=p["description"],
        image=p.get("image", "placeholder.jpg"),
        video=p.get("video"),
        is_featured=p.get("is_featured", False),
        category=p.get("category", "General")
    )
    db.add(new_prod)
    db.commit()
    
    for city, qty in data.get("initial_stock", {}).items():
        wh = db.query(WarehouseDB).filter(WarehouseDB.city.ilike(city)).first()
        if wh:
            db.add(StockDB(warehouse_id=wh.id, product_id=new_prod.id, quantity=qty))
    db.commit()
    return {"status": "success"}

@app.post("/edit-product/{product_id}")
async def edit_product(product_id: int, data: dict, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(status_code=403)
    p = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not p: raise HTTPException(status_code=404)
    
    update_data = data["product"]
    p.name = update_data.get("name", p.name)
    p.price_per_kg = update_data.get("price_per_kg", p.price_per_kg)
    p.description = update_data.get("description", p.description)
    p.image = update_data.get("image", p.image)
    p.video = update_data.get("video", p.video)
    p.is_featured = update_data.get("is_featured", p.is_featured)
    p.category = update_data.get("category", p.category)
    
    db.commit()
    return {"status": "success"}

@app.post("/delete-product/{product_id}")
async def delete_product(product_id: int, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(status_code=403)
    p = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not p: raise HTTPException(status_code=404)
    db.delete(p)
    db.commit()
    return {"status": "success"}

@app.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    cats = db.query(ProductDB.category).distinct().all()
    return [c[0] for c in cats]

@app.post("/register")
async def register(user_data: dict, db: Session = Depends(get_db)):
    if db.query(UserDB).filter(UserDB.email == user_data["email"]).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    profile = user_data.get("profile", {})
    new_user = UserDB(
        email=user_data["email"],
        hashed_password=get_password_hash(user_data["password"]),
        role=user_data.get("role", "customer"),
        fullname=profile.get("fullname"),
        phone=profile.get("phone")
    )
    db.add(new_user)
    db.commit()
    return {"status": "success"}

@app.get("/track-order/{tx_ref}")
def track_order(tx_ref: str, db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.tx_ref == tx_ref).first()
    if not order: raise HTTPException(status_code=404)
    
    courier_info = None
    if order.courier_id:
        courier = db.query(UserDB).filter(UserDB.id == order.courier_id).first()
        if courier:
            courier_info = {"name": courier.fullname, "phone": courier.phone}
            
    # Get Telemetry (Product Protection Service #1)
    telemetry = db.query(TelemetryDB).filter(TelemetryDB.order_id == order.id).order_by(TelemetryDB.id.desc()).limit(10).all()
    
    return {
        "status": order.status,
        "city": order.city,
        "amount": order.amount,
        "courier": courier_info,
        "proof_pickup": order.proof_pickup,
        "proof_delivery": order.proof_delivery,
        "delivery_pin": order.delivery_pin,
        "preparation_duration": order.preparation_duration,
        "rejection_reason": order.rejection_reason,
        "telemetry": [{"temp": t.temp, "time": t.timestamp} for t in telemetry]
    }

# --- Delivery & Protection Routes ---

@app.get("/deliveries/available")
def get_available_deliveries(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "delivery_provider": raise HTTPException(status_code=403)
    return db.query(OrderDB).filter(OrderDB.status == "awaiting_pickup").all()

@app.post("/deliveries/claim/{order_id}")
def claim_delivery(order_id: int, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "delivery_provider": raise HTTPException(status_code=403)
    order = db.query(OrderDB).filter(OrderDB.id == order_id, OrderDB.status == "awaiting_pickup").with_for_update().first()
    if not order: raise HTTPException(status_code=404, detail="Order not available or already claimed")
    
    order.courier_id = user.id
    order.status = "claimed"
    db.commit()
    return {"status": "success"}

@app.post("/deliveries/update-status/{order_id}")
def update_delivery_status(order_id: int, status: str, proof: Optional[str] = None, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "delivery_provider": raise HTTPException(status_code=403)
    order = db.query(OrderDB).filter(OrderDB.id == order_id, OrderDB.courier_id == user.id).first()
    if not order: raise HTTPException(status_code=404)
    
    order.status = status
    if status == "in_transit" and proof:
        order.proof_pickup = proof
    db.commit()
    
    if status == "in_transit":
        import random
        db.add(TelemetryDB(order_id=order.id, temp=random.uniform(-22.0, -18.0), humidity=random.uniform(40.0, 60.0)))
        db.commit()
        
    return {"status": "success"}

@app.post("/deliveries/complete/{order_id}")
def complete_delivery(order_id: int, complete_data: dict, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "delivery_provider": raise HTTPException(status_code=403)
    order = db.query(OrderDB).filter(OrderDB.id == order_id, OrderDB.courier_id == user.id).first()
    if not order: raise HTTPException(status_code=404, detail="Order not found or not claimed by you")
    
    if order.delivery_pin != complete_data.get("delivery_pin"):
        raise HTTPException(status_code=400, detail="Invalid Delivery PIN. Order cannot be completed.")
        
    order.status = "delivered"
    if complete_data.get("proof"):
        order.proof_delivery = complete_data.get("proof")
    
    user.wallet_balance += order.payout_amount
    
    import random
    db.add(TelemetryDB(order_id=order.id, temp=random.uniform(-22.0, -18.0), humidity=random.uniform(40.0, 60.0)))
    db.commit()
    return {"status": "success", "wallet_balance": user.wallet_balance}

@app.get("/courier/profile")
def get_courier_profile(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "delivery_provider": raise HTTPException(status_code=403)
    completed_runs = db.query(OrderDB).filter(OrderDB.courier_id == user.id, OrderDB.status == "delivered").count()
    return {
        "fullname": user.fullname,
        "email": user.email,
        "phone": user.phone,
        "wallet_balance": user.wallet_balance,
        "completed_runs": completed_runs,
        "is_online": getattr(user, "is_online", False)
    }

@app.post("/courier/toggle-status")
def toggle_courier_status(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "delivery_provider": raise HTTPException(status_code=403)
    user.is_online = not getattr(user, "is_online", False)
    db.commit()
    return {"status": "success", "is_online": user.is_online}

@app.get("/orders/{city}")
def get_orders_by_city(city: str, db: Session = Depends(get_db)):
    return db.query(OrderDB).filter(OrderDB.city.ilike(city)).all()

@app.put("/orders/{order_id}/accept")
def accept_order(order_id: int, duration_data: dict, db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order: raise HTTPException(status_code=404, detail="Order not found")
    order.status = "preparing"
    order.preparation_duration = duration_data.get("preparation_duration", 15)
    db.commit()
    return {"status": "success"}

@app.put("/orders/{order_id}/reject")
def reject_order(order_id: int, reject_data: dict, db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order: raise HTTPException(status_code=404, detail="Order not found")
    order.status = "rejected"
    order.rejection_reason = reject_data.get("reason", "Out of stock")
    db.commit()
    return {"status": "success"}

@app.put("/orders/{order_id}/ready")
def ready_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(OrderDB).filter(OrderDB.id == order_id).first()
    if not order: raise HTTPException(status_code=404, detail="Order not found")
    order.status = "awaiting_pickup"
    db.commit()
    return {"status": "success"}

@app.get("/hub/telemetry/{city}")
def get_hub_telemetry(city: str, db: Session = Depends(get_db)):
    hub = db.query(WarehouseDB).filter(WarehouseDB.city.ilike(city)).first()
    if not hub: raise HTTPException(status_code=404)
    
    # Simulate real-time hub health
    import random
    return {
        "city": city,
        "current_temp": random.uniform(-25.0, -20.0),
        "status": "Optimal",
        "last_defrost": (datetime.now() - timedelta(hours=4)).isoformat()
    }

# --- B2B Restock Services ---

@app.post("/restock-request")
def create_restock_request(data: dict, db: Session = Depends(get_db)):
    # This protects our B2B pipeline by scheduling replenishments
    new_request = RestockRequestDB(
        seller_name=data["seller_name"],
        warehouse_id=data["warehouse_id"],
        scheduled_date=data["scheduled_date"],
        items=data["items"]
    )
    db.add(new_request)
    db.commit()
    return {"status": "success"}

@app.get("/admin/restock-requests")
def get_restock_requests(db: Session = Depends(get_db)):
    return db.query(RestockRequestDB).all()

@app.get("/paid-orders")
def get_paid_orders(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "delivery_provider":
        return db.query(OrderDB).filter(OrderDB.courier_id == user.id).all()
    return db.query(OrderDB).filter(OrderDB.status.in_(["received", "preparing", "awaiting_pickup", "claimed", "in_transit", "delivered"])).all()

@app.post("/submit-review")
def submit_review(data: dict, db: Session = Depends(get_db)):
    # Simple check if order exists and is delivered
    order = db.query(OrderDB).filter(OrderDB.tx_ref == data["tx_ref"]).first()
    if not order or order.status != "delivered":
        raise HTTPException(status_code=400, detail="Invalid order or not delivered yet")
    
    new_review = ReviewDB(
        order_id=order.id,
        courier_id=order.courier_id,
        rating=data["rating"],
        comment=data.get("comment")
    )
    db.add(new_review)
    db.commit()
    return {"status": "success"}

@app.post("/admin/update-stock")
def update_stock(data: dict, user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(status_code=403)
    
    # data: { product_id, hub_id, quantity }
    stock = db.query(StockDB).filter(
        StockDB.product_id == data["product_id"],
        StockDB.warehouse_id == data["hub_id"]
    ).first()
    
    if stock:
        stock.quantity = data["quantity"]
        db.commit()
        return {"status": "success"}
    else:
        # Create stock entry if not exists
        new_stock = StockDB(
            warehouse_id=data["hub_id"],
            product_id=data["product_id"],
            quantity=data["quantity"]
        )
        db.add(new_stock)
        db.commit()
        return {"status": "success"}

@app.get("/admin/kpi")
def get_admin_kpi(user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin": raise HTTPException(status_code=403)
    
    # Revenue & Orders
    orders = db.query(OrderDB).filter(OrderDB.status != "pending").all()
    total_revenue = sum(o.amount for o in orders)
    total_orders = len(orders)
    
    # Best Sellers & Hub Performance
    hub_sales = {"Lagos": 0, "Abuja": 0, "Warri": 0}
    product_sales = {}
    
    for o in orders:
        hub_sales[o.city] = hub_sales.get(o.city, 0) + 1
        for item in o.items:
            pid = str(item["product_id"])
            product_sales[pid] = product_sales.get(pid, 0) + item["kg"]
            
    # Reviews
    reviews = db.query(ReviewDB).all()
    avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0
    
    return {
        "revenue": total_revenue,
        "order_count": total_orders,
        "avg_rating": round(avg_rating, 1),
        "hubs": hub_sales,
        "product_performance": product_sales,
        "inventory_health": "stable" # Simplified for now
    }

# --- Initial Seed Data ---
@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    # Always ensure Admin exists
    if not db.query(UserDB).filter(UserDB.email == "admin@arctic.com").first():
        db.add(UserDB(email="admin@arctic.com", hashed_password=get_password_hash("admin123"), role="admin", fullname="Arctic Admin"))
    # Ensure default rider exists
    if not db.query(UserDB).filter(UserDB.email == "rider@arctic.com").first():
        db.add(UserDB(email="rider@arctic.com", hashed_password=get_password_hash("rider123"), role="delivery_provider", fullname="Arctic Swift Rider", phone="+2348012345678"))
    
    # Seed Products if empty
    if not db.query(ProductDB).first():
        p1 = ProductDB(id=1, name="Frozen Atlantic Salmon", price_per_kg=12500.00, description="Premium fillets.", image="salmon.jpg", is_featured=True)
        p2 = ProductDB(id=2, name="IQF Chicken Breasts", price_per_kg=8500.00, description="Individually frozen.", image="chicken.jpg")
        p3 = ProductDB(id=3, name="Frozen Tiger Prawns", price_per_kg=22000.00, description="Extra large prawns.", image="prawns.jpg", is_featured=True)
        db.add_all([p1, p2, p3])
        
        hubs = db.query(WarehouseDB).all()
        if not hubs:
            hubs = [WarehouseDB(id=1, name="Lagos Hub", city="Lagos"), WarehouseDB(id=2, name="Abuja Hub", city="Abuja"), WarehouseDB(id=3, name="Warri Hub", city="Warri")]
            db.add_all(hubs)
        db.commit()
        
        for wh in hubs:
            db.add_all([
                StockDB(warehouse_id=wh.id, product_id=1, quantity=500.0),
                StockDB(warehouse_id=wh.id, product_id=2, quantity=1000.0),
                StockDB(warehouse_id=wh.id, product_id=3, quantity=300.0)
            ])
            # Seed a default package per hub
            db.add(PackageDB(name="Family Frost Pack", price=45000.00, description="3kg Salmon + 5kg Chicken combo.", city=wh.city, is_featured=True))
        db.commit()
    db.close()

# --- STATIC FILES (LAST) ---
FRONTEND_PATH = os.getenv("FRONTEND_PATH", "../frontend")
app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
