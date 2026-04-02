from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .db import engine, SessionLocal
from .models import Base, Habit
from .auth import require_roles
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")
