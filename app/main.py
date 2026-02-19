from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .db import engine, SessionLocal
from .models import Base, Habit

app = FastAPI()

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/habits")
def list_habits(db: Session = Depends(get_db)):
    return db.query(Habit).all()

@app.post("/habits")
def create_habit(name: str, db: Session = Depends(get_db)):
    habit = Habit(name=name)
    db.add(habit)
    db.commit()
    db.refresh(habit)
    return habit

