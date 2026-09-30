import os, json, sqlite3, hashlib, secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from gemini_utils import recommend

load_dotenv()
@asynccontextmanager
async def lifespan(app):
    startup()
    yield

app = FastAPI(title="PocketSmart AI", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-secret"))
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
templates = Jinja2Templates(directory="templates")
DB = "pocketsmart.db"

PLANNERS = {
    "home": ("Home Interior Planner", [("budget", "Total budget (₹)", "number"), ("rooms", "Rooms (e.g. Living Room, Kitchen)", "text"),
             ("quantities", "Items & quantities (e.g. 4 lights, 2 fans, 1 dining table)", "text"), ("style", "Style (modern, minimal...)", "text")]),
    "party": ("Party Planner", [("budget", "Total budget (₹)", "number"), ("guests", "Guest count", "number"),
             ("event_type", "Event type (birthday, wedding...)", "text"), ("venue", "Venue details", "text")]),
    "jewelry": ("Jewelry Planner", [("budget", "Total budget (₹)", "number"), ("occasion", "Occasion", "text"),
             ("style", "Style preference", "text"), ("image", "Outfit image (optional)", "file")]),
}

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def startup():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, username TEXT, kind TEXT, inputs TEXT, results TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")

def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000).hex()

def check_pw(pw, stored):
    return hash_pw(pw, stored.split("$")[0]) == stored

def me(request): return request.session.get("user")

def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, {"user": me(request), **ctx})

@app.get("/")
def home(request: Request): return render(request, "index.html", planners=PLANNERS)

@app.get("/register")
def register_page(request: Request): return render(request, "auth.html", mode="register", error=None)

@app.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        with db() as c: c.execute("INSERT INTO users(username,pw) VALUES(?,?)", (username, hash_pw(password)))
    except sqlite3.IntegrityError:
        return render(request, "auth.html", mode="register", error="Username already taken")
    return RedirectResponse("/login", 303)

@app.get("/login")
def login_page(request: Request): return render(request, "auth.html", mode="login", error=None)

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    row = db().execute("SELECT pw FROM users WHERE username=?", (username,)).fetchone()
    if not row or not check_pw(password, row["pw"]):
        return render(request, "auth.html", mode="login", error="Invalid username or password")
    request.session["user"] = username
    return RedirectResponse("/dashboard", 303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/login", 303)

@app.get("/session-info")
def session_info(request: Request): return {"user": me(request), "logged_in": bool(me(request))}

@app.get("/planner/{kind}")
def planner(request: Request, kind: str):
    if not me(request): return RedirectResponse("/login", 303)
    title, fields = PLANNERS[kind]
    return render(request, "planner.html", kind=kind, title=title, fields=fields)

def make_route(kind):
    async def handler(request: Request):
        if not me(request): return RedirectResponse("/login", 303)
        form = await request.form()
        data = {k: v for k, v in form.items() if isinstance(v, str)}
        img = form.get("image"); image = None
        if img is not None and getattr(img, "filename", ""):
            image = (await img.read(), img.content_type or "image/jpeg")
        items = recommend(kind, data, image)
        with db() as c:
            c.execute("INSERT INTO history(username,kind,inputs,results) VALUES(?,?,?,?)", (me(request), kind, json.dumps(data), json.dumps(items)))
        total = sum(float(i.get("price", 0) or 0) for i in items)
        return render(request, "result.html", title=PLANNERS[kind][0], items=items, total=total, budget=data.get("budget"))
    return handler

for k in PLANNERS:
    app.add_api_route(f"/generate-{k}", make_route(k), methods=["POST"])

@app.get("/dashboard")
def dashboard(request: Request):
    if not me(request): return RedirectResponse("/login", 303)
    rows = db().execute("SELECT kind,created,inputs FROM history WHERE username=? ORDER BY id DESC LIMIT 5", (me(request),)).fetchall()
    recent = [{"kind": r["kind"], "created": r["created"], "budget": json.loads(r["inputs"]).get("budget")} for r in rows]
    return render(request, "dashboard.html", planners=PLANNERS, recent=recent)

@app.get("/history")
def history(request: Request):
    if not me(request): return RedirectResponse("/login", 303)
    rows = db().execute("SELECT * FROM history WHERE username=? ORDER BY id DESC", (me(request),)).fetchall()
    data = [{"kind": r["kind"], "created": r["created"], "inputs": json.loads(r["inputs"]), "items": json.loads(r["results"])} for r in rows]
    return render(request, "history.html", rows=data)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)