# Importăm FastAPI, Depends și Request.
# Request ne trebuie ca să putem citi headere și salva valori în request.state.
from fastapi import FastAPI, Depends, Request

# Session din SQLAlchemy pentru lucrul cu baza de date.
from sqlalchemy.orm import Session

# Importăm engine-ul și factory-ul de sesiuni către DB.
from .db import engine, SessionLocal

# Importăm modelele SQLAlchemy și baza declarativă.
from .models import Base, Habit

# Importăm funcția de RBAC care verifică rolurile din JWT.
from .auth import require_roles

# Ca să servim fișiere statice și index.html.
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# uuid ne trebuie pentru a genera correlation_id când lipsește.
import uuid

# json pentru a scrie logul ca JSON valid.
import json

# time pentru măsurarea duratei requestului.
import time

# datetime + timezone pentru timestamp UTC în logs.
from datetime import datetime, timezone

# Inițializăm aplicația FastAPI.
app = FastAPI()

# Creează tabelele în DB dacă nu există deja.
# Atenție: asta încearcă să se conecteze la DB la startup.
Base.metadata.create_all(bind=engine)


def get_db():
    # Creează o sesiune de DB pentru requestul curent.
    db = SessionLocal()
    try:
        # O oferim endpointului.
        yield db
    finally:
        # La final o închidem mereu.
        db.close()


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    # Citim correlation_id dacă vine din request.
    correlation_id = request.headers.get("X-Correlation-Id")

    # Citim run_id dacă vine din request/test harness.
    run_id = request.headers.get("X-Run-Id")

    # Citim traceparent dacă vine din context de tracing W3C.
    traceparent = request.headers.get("traceparent")

    # Dacă nu vine correlation_id, generăm unul nou.
    if not correlation_id:
        correlation_id = str(uuid.uuid4())

    # Salvăm correlation_id în request.state,
    # ca să poată fi folosit și în alte locuri dacă va fi nevoie.
    request.state.correlation_id = correlation_id

    # Salvăm run_id în request.state.
    # Dacă header-ul lipsește, valoarea va fi None.
    request.state.run_id = run_id

    # Salvăm timpul de start, ca să calculăm latency_ms.
    start_time = time.time()

    # Implicit nu avem eroare.
    error_class = None

    # Inițial răspunsul nu există.
    response = None

    try:
        # Lăsăm requestul să meargă mai departe spre endpoint.
        response = await call_next(request)

        # Dacă totul merge, returnăm răspunsul normal.
        return response

    except Exception as exc:
        # Dacă apare excepție, reținem clasa erorii pentru log.
        error_class = exc.__class__.__name__

        # Ridicăm mai departe excepția.
        raise

    finally:
        # Calculăm cât a durat requestul în milisecunde.
        latency_ms = round((time.time() - start_time) * 1000, 2)

        # Dacă avem response, folosim statusul real.
        # Dacă nu, presupunem 500.
        status_code = response.status_code if response is not None else 500

        # Construim un obiect JSON cu câmpurile importante pentru logs.
        log_event = {
            # Timestamp UTC, util pentru Splunk și corelare temporală.
            "timestamp": datetime.now(timezone.utc).isoformat(),

            # Numele serviciului.
            "service": "habit-tracker",

            # Environment-ul curent.
            "env": "dev",

            # Metoda HTTP: GET, POST etc.
            "method": request.method,

            # Path-ul requestului, ex: /habits
            "path": request.url.path,

            # Status code final.
            "status_code": status_code,

            # Durata requestului în ms.
            "latency_ms": latency_ms,

            # Correlation ID pentru requestul curent.
            "correlation_id": correlation_id,

            # Run ID, util când traficul vine din k6/test harness.
            "run_id": run_id,

            # Trace context W3C, dacă există.
            "traceparent": traceparent,

            # Clasa erorii, dacă a existat o excepție.
            "error_class": error_class,

            # User salvat anterior în request.state de auth.py
            # dacă tokenul a fost valid.
            "user": getattr(request.state, "user", None),

            # Rolurile salvate în request.state de auth.py.
            "roles": getattr(request.state, "roles", []),
        }

        # Scriem logul ca o singură linie JSON în stdout.
        # Asta este foarte bun pentru Kubernetes + Splunk.
        print(json.dumps(log_event))

        # Dacă există răspuns, propagăm correlation_id înapoi către client.
        if response is not None:
            response.headers["X-Correlation-Id"] = correlation_id


@app.get("/habits")
def list_habits(
    # Endpointul e permis pentru reader, writer și admin.
    payload: dict = Depends(require_roles(["reader", "writer", "admin"])),

    # Injectăm sesiunea DB.
    db: Session = Depends(get_db),
):
    # Returnăm toate habit-urile din DB.
    return db.query(Habit).all()


@app.post("/habits")
def create_habit(
    # Numele noului habit vine ca query param.
    name: str,

    # Doar writer și admin au voie să creeze.
    payload: dict = Depends(require_roles(["writer", "admin"])),

    # Injectăm sesiunea DB.
    db: Session = Depends(get_db),
):
    # Construim obiectul Habit.
    habit = Habit(name=name)

    # Îl adăugăm în sesiune.
    db.add(habit)

    # Facem commit în DB.
    db.commit()

    # Reîncărcăm obiectul ca să aibă valorile actuale.
    db.refresh(habit)

    # Îl returnăm în response.
    return habit


# Servim /static din folderul static.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    # Când intri pe /, servești index.html.
    return FileResponse("static/index.html")