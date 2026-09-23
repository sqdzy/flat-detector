"""Internal health endpoints, not an admin/public API."""
from fastapi import FastAPI,HTTPException
from sqlalchemy import text
from flat_detector.database import Session

app=FastAPI(title="flat-detector-internal",docs_url=None,redoc_url=None,openapi_url=None)

@app.get("/health/live")
def live():
    return {"status":"live"}

@app.get("/health/ready")
def ready():
    try:
        with Session() as db:db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503,detail="Database unavailable")
    return {"status":"ready"}
