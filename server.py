import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
import jwt

# Carrega variáveis de ambiente a partir do .env na raiz do projeto
env_path = Path(__file__).resolve().parents[0] / ".env"
dotenv.load_dotenv(dotenv_path=env_path)

# Configurações
DB_FILE = os.getenv("LICENSE_DB", "./licenses.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN não definido no .env")
if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY não definido no .env")

app = FastAPI(title="RemBG Automation Unified Server")

# ---------- Utilitários ----------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- Modelos ----------
class GenerateKeyRequest(BaseModel):
    tier: str = "pro"
    duration_days: int = 365
    is_active: bool = True

# ---------- Rotas de Ativação (origem do activation_server) ----------
# Exemplo simplificado: verifica licença (o código original pode ser mais complexo)
@app.post("/api/verify")
async def verify_license(request: Request):
    data = await request.json()
    product_key = data.get("productKey")
    if not product_key:
        raise HTTPException(status_code=400, detail="productKey ausente")
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM product_keys WHERE product_key = ?", (product_key,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "message": "Chave não encontrada"})
    if not row["is_active"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "Chave desativada"})
    # Gera token JWT contendo sub, tier e exp
    payload = {
        "sub": f"user_{row['id']}",
        "tier": row["tier"],
        "exp": datetime.now(timezone.utc) + timedelta(days=row["subscription_duration_days"]),
        "iat": datetime.now(timezone.utc)
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
    return {"success": True, "message": "Licença válida", "tier": row["tier"], "token": token}

# ---------- Rotas de Administração (admin UI) ----------
# Monta arquivos estáticos da pasta admin_server/static
admin_static_path = Path(__file__).resolve().parents[0] / "admin_server" / "static"
app.mount("/admin/static", StaticFiles(directory=admin_static_path), name="admin-static")

# Servir a página HTML principal
@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    index_path = admin_static_path / "admin.html"
    return FileResponse(index_path)

# Endpoint de geração de chave (protected by ADMIN_TOKEN)
@app.post("/admin/generate-key")
async def generate_key(payload: GenerateKeyRequest, request: Request):
    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Token admin inválido")
    new_key = uuid.uuid4().hex
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO product_keys (product_key, tier, subscription_duration_days, is_active) VALUES (?,?,?,?)",
        (new_key, payload.tier, payload.duration_days, int(payload.is_active)),
    )
    conn.commit()
    conn.close()
    return {"success": True, "productKey": new_key}

# ---------- Rota raiz ----------
@app.get("/")
async def root():
    return {"message": "Servidor Unificado RemBG Automation está ativo"}

# ---------- Execução direta ----------
if __name__ == "__main__":
    import uvicorn
    import argparse
    parser = argparse.ArgumentParser(description="Run RemBG unified server")
    parser.add_argument("--mode", choices=["all", "admin", "activation"], default="all",
                        help="Which part of the server to run")
    args = parser.parse_args()
    if args.mode == "admin":
        # Desmonta rotas de ativação
        app.router.routes = [r for r in app.router.routes if r.path.startswith("/admin") or r.path == "/"]
    elif args.mode == "activation":
        # Desmonta rotas de admin
        app.router.routes = [r for r in app.router.routes if not r.path.startswith("/admin")] 
    print(f"Servidor Unificado rodando em http://0.0.0.0:8000 (modo={args.mode})")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
