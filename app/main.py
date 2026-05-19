from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .db import engine, SessionLocal
from .models import Base, Habit
from .auth import require_roles
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import Request
import json
import time
from datetime import datetime, timezone
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
    run_id = request.headers.get("X-Run-Id")
    traceparent = request.headers.get("traceparent")

    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    request.state.correlation_id = correlation_id
    request.state.run_id = run_id

    start_time = time.time()
    error_class = None

    try:
        response = await call_next(request)
    except Exception as exc:
        error_class = exc.__class__.__name__
        raise
    finally:
        latency_ms = round((time.time() - start_time) * 1000, 2)

        status_code = response.status_code if "response" in locals() else 500

        log_event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "habit-tracker",
            "env": "dev",
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "correlation_id": correlation_id,
            "run_id": run_id,
            "traceparent": traceparent,
            "error_class": error_class,
        }

        print(json.dumps(log_event))

    response.headers["X-Correlation-Id"] = correlation_id
    return response

@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")
