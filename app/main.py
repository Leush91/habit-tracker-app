from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .db import engine, SessionLocal
from .models import Base, Habit
from .auth import require_roles
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import Request
import uuid

app = FastAPI()

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/habits")
def list_habits(
    payload: dict = Depends(require_roles(["reader", "writer", "admin"])),
    db: Session = Depends(get_db),
):
    return db.query(Habit).all()

@app.post("/habits")
def create_habit(
    name: str,
    payload: dict = Depends(require_roles(["writer", "admin"])),
    db: Session = Depends(get_db),
):
    habit = Habit(name=name)
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return habit

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-Id")

    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    request.state.correlation_id = correlation_id

    response = await call_next(request)
    response.headers["X-Correlation-Id"] = correlation_id
    return response

@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")
