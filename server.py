import os
import uuid
import hmac
import hashlib
import json
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional
import dotenv

class InvalidTokenError(Exception):
    pass

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def base64url_decode(data: str) -> bytes:
    padding = '=' * (4 - (len(data) % 4))
    return base64.urlsafe_b64decode(data + padding)

def jwt_encode(payload: dict, key: str) -> str:
    clean_payload = {}
    for k, v in payload.items():
        if isinstance(v, datetime):
            clean_payload[k] = int(v.timestamp())
        else:
            clean_payload[k] = v
            
    header = {"alg": "HS256", "typ": "JWT"}
    header_json = json.dumps(header, separators=(',', ':')).encode('utf-8')
    payload_json = json.dumps(clean_payload, separators=(',', ':')).encode('utf-8')
    
    signing_input = base64url_encode(header_json) + "." + base64url_encode(payload_json)
    
    signature = hmac.new(key.encode('utf-8'), signing_input.encode('utf-8'), hashlib.sha256).digest()
    return signing_input + "." + base64url_encode(signature)

def jwt_decode(token: str, key: str) -> dict:
    parts = token.split('.')
    if len(parts) != 3:
        raise InvalidTokenError("Token JWT inválido: formato incorreto")
        
    try:
        signing_input = parts[0] + "." + parts[1]
        signature_received = base64url_decode(parts[2])
        
        signature_expected = hmac.new(key.encode('utf-8'), signing_input.encode('utf-8'), hashlib.sha256).digest()
        if not hmac.compare_digest(signature_received, signature_expected):
            raise InvalidTokenError("Assinatura do token inválida")
            
        payload_json = base64url_decode(parts[1])
        return json.loads(payload_json.decode('utf-8'))
    except Exception as e:
        raise InvalidTokenError(f"Falha ao decodificar: {e}")
import sqlalchemy as sa
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
dotenv.load_dotenv(dotenv_path=env_path)

DB_FILE = os.getenv("LICENSE_DB", "./licenses.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "w7J3z$kP8vB!Qf9u#Xn2%YhTmL4s@r1*")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "V%wx<7%9qR8hV%wx<7%9qR8hV%wx<7%9qR8hV%wx<7%9qR8hV%wx<7%9qR8h")

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL")
engine = None

if DATABASE_URL:
    DATABASE_URL = DATABASE_URL.strip()
    print(f"DEBUG: Original DATABASE_URL prefix: {DATABASE_URL[:30] if DATABASE_URL else None}")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+pg8000://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+pg8000://", 1)
    print(f"DEBUG: Modified DATABASE_URL prefix: {DATABASE_URL[:30] if DATABASE_URL else None}")
    try:
        print("Tentando conectar ao banco de dados PostgreSQL (Supabase)...")
        engine = sa.create_engine(
            DATABASE_URL, 
            future=True, 
            pool_pre_ping=True
        )
        # Testa a conexão
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        print("Conectado ao PostgreSQL com sucesso!")
    except Exception as e:
        print(f"Aviso: Não foi possível conectar ao PostgreSQL: {e}")
        print("Fazendo fallback para banco de dados SQLite local...")
        engine = None

if engine is None:
    engine = sa.create_engine(f"sqlite:///{DB_FILE}", future=True, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()

class ProductKey(Base):
    __tablename__ = 'product_keys'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_key = Column(String, nullable=False, unique=True)
    tier = Column(String, nullable=False, default="pro")
    subscription_duration_days = Column(Integer, nullable=False, default=365)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    activated_at = Column(DateTime(timezone=True), nullable=True)
    activated_machine_id = Column(String, nullable=True)

# Initialize database
def init_db():
    Base.metadata.create_all(bind=engine)

init_db()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FastAPI App
app = FastAPI(title="RemBG Automation Unified Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class GenerateKeyRequest(BaseModel):
    tier: str = "pro"
    duration_days: int = 365
    is_active: bool = True

class ActivateRequest(BaseModel):
    productKey: str
    machineId: str

# Helper to generate formatted keys
def generate_key_string() -> str:
    key_base = str(uuid.uuid4()).upper().replace('-', '')[:16]
    return '-'.join(key_base[i:i+4] for i in range(0, len(key_base), 4))

# ---------- Activation Routes ----------

@app.post("/activate")
async def activate_license(payload: ActivateRequest, db: Session = Depends(get_db)):
    product_key = payload.productKey
    machine_id = payload.machineId

    db_key = db.query(ProductKey).filter(ProductKey.product_key == product_key).first()
    if not db_key:
        return JSONResponse(status_code=404, content={"success": False, "message": "Chave de produto não encontrada."})

    if not db_key.is_active:
        return JSONResponse(status_code=403, content={"success": False, "message": "Esta chave de produto foi desativada."})

    if db_key.activated_machine_id and db_key.activated_machine_id != machine_id:
        return JSONResponse(status_code=403, content={"success": False, "message": "Esta chave já foi ativada em outra máquina."})

    # Activate key if not already activated
    if not db_key.activated_at:
        db_key.activated_at = datetime.now(timezone.utc)
        db_key.activated_machine_id = machine_id
        db.commit()
        db.refresh(db_key)

    # Calculate expiration time
    exp_time = db_key.activated_at + timedelta(days=db_key.subscription_duration_days)
    if exp_time.tzinfo is None:
        exp_time = exp_time.replace(tzinfo=timezone.utc)

    # Create JWT token
    token_payload = {
        "sub": f"user_{db_key.id}",
        "machineId": machine_id,
        "tier": db_key.tier,
        "iat": datetime.now(timezone.utc),
        "exp": exp_time
    }
    token = jwt_encode(token_payload, JWT_SECRET_KEY)

    print(f"Chave '{product_key}' ativada com sucesso para a máquina '{machine_id[:10]}...'. Token gerado.")
    return {"success": True, "token": token}

@app.post("/refresh-token")
async def refresh_token(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return JSONResponse(status_code=401, content={"success": False, "message": "Token de autorização ausente ou inválido."})

    token = auth_header.split(' ')[1]

    try:
        # Decode but ignore expiration so we can renew expired licenses
        payload = jwt_decode(token, JWT_SECRET_KEY)
        
        sub = payload.get("sub", "")
        if not sub.startswith("user_"):
            return JSONResponse(status_code=401, content={"success": False, "message": "Sub do token inválido."})
            
        key_id = int(sub.split("_")[1])
        db_key = db.query(ProductKey).filter(ProductKey.id == key_id).first()
        
        if not db_key:
            return JSONResponse(status_code=401, content={"success": False, "message": "Chave de licença não encontrada."})
            
        if not db_key.is_active:
            return JSONResponse(status_code=401, content={"success": False, "message": "Esta licença foi desativada."})

        # Check if the subscription has actually expired
        expiration = db_key.activated_at + timedelta(days=db_key.subscription_duration_days)
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=timezone.utc)
            
        if datetime.now(timezone.utc) > expiration:
            return JSONResponse(status_code=401, content={"success": False, "message": "Sua assinatura expirou e não foi renovada."})

        # Re-emit token
        new_payload = {
            "sub": f"user_{db_key.id}",
            "machineId": payload.get("machineId"),
            "tier": db_key.tier,
            "iat": datetime.now(timezone.utc),
            "exp": expiration
        }
        new_token = jwt_encode(new_payload, JWT_SECRET_KEY)
        
        print(f"Token renovado com sucesso para o usuário '{sub}'.")
        return {"success": True, "token": new_token}

    except InvalidTokenError as e:
        return JSONResponse(status_code=401, content={"success": False, "message": f"Token inválido: {e}"})

# Backward compatibility / verify endpoint
@app.post("/api/verify")
async def verify_license(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    product_key = data.get("productKey")
    if not product_key:
        raise HTTPException(status_code=400, detail="productKey ausente")
        
    db_key = db.query(ProductKey).filter(ProductKey.product_key == product_key).first()
    if not db_key:
        return JSONResponse(status_code=404, content={"success": False, "message": "Chave não encontrada"})
        
    if not db_key.is_active:
        return JSONResponse(status_code=403, content={"success": False, "message": "Chave desativada"})
        
    # Generate token
    expiration = datetime.now(timezone.utc) + timedelta(days=db_key.subscription_duration_days)
    payload = {
        "sub": f"user_{db_key.id}",
        "tier": db_key.tier,
        "exp": expiration,
        "iat": datetime.now(timezone.utc)
    }
    token = jwt_encode(payload, JWT_SECRET_KEY)
    return {"success": True, "message": "Licença válida", "tier": db_key.tier, "token": token}

# ---------- Admin routes ----------

admin_static_path = Path(__file__).resolve().parent / "admin_server" / "static"
app.mount("/admin/static", StaticFiles(directory=admin_static_path), name="admin-static")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    index_path = admin_static_path / "admin.html"
    return FileResponse(index_path)

@app.get("/admin.css")
async def admin_css():
    return FileResponse(admin_static_path / "admin.css")

@app.get("/admin.js")
async def admin_js():
    return FileResponse(admin_static_path / "admin.js")

@app.get("/admin/keys", response_model=list)
async def list_keys(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token admin inválido")
        
    keys = db.query(ProductKey).order_by(ProductKey.created_at.desc()).all()
    return [
        {
            "productKey": k.product_key,
            "tier": k.tier,
            "durationDays": k.subscription_duration_days,
            "isActive": k.is_active,
            "createdAt": k.created_at.isoformat() if k.created_at else None,
            "activatedAt": k.activated_at.isoformat() if k.activated_at else None,
            "activatedMachineId": k.activated_machine_id
        }
        for k in keys
    ]

@app.post("/admin/generate-key")
async def generate_key(payload: GenerateKeyRequest, request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token admin inválido")
        
    new_key = generate_key_string()
    db_key = ProductKey(
        product_key=new_key,
        tier=payload.tier,
        subscription_duration_days=payload.duration_days,
        is_active=payload.is_active
    )
    db.add(db_key)
    db.commit()
    return {"success": True, "productKey": new_key}

@app.delete("/admin/keys/{product_key}")
async def delete_key(product_key: str, request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token admin inválido")
        
    db_key = db.query(ProductKey).filter(ProductKey.product_key == product_key).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="Chave não encontrada")
        
    db.delete(db_key)
    db.commit()
    return {"success": True}

@app.patch("/admin/keys/{product_key}/activate")
async def toggle_key(product_key: str, request: Request, body: dict, db: Session = Depends(get_db)):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token admin inválido")
        
    is_active = body.get("is_active")
    if is_active is None:
        raise HTTPException(status_code=400, detail="Campo is_active ausente")
        
    db_key = db.query(ProductKey).filter(ProductKey.product_key == product_key).first()
    if not db_key:
        raise HTTPException(status_code=404, detail="Chave não encontrada")
        
    db_key.is_active = bool(is_active)
    db.commit()
    return {"success": True}

# Root route
@app.get("/")
async def root():
    return {"message": "Servidor Unificado RemBG Automation está ativo"}

if __name__ == "__main__":
    import uvicorn
    import argparse
    parser = argparse.ArgumentParser(description="Run RemBG unified server")
    parser.add_argument("--mode", choices=["all", "admin", "activation"], default="all",
                        help="Which part of the server to run")
    args = parser.parse_args()
    if args.mode == "admin":
        app.router.routes = [r for r in app.router.routes if r.path.startswith("/admin") or r.path == "/"]
    elif args.mode == "activation":
        app.router.routes = [r for r in app.router.routes if not r.path.startswith("/admin")] 
    print(f"Servidor Unificado rodando em http://0.0.0.0:8000 (modo={args.mode})")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
