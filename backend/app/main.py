from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import ensure_seed_data
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import admin, auth, client, webhook

settings = get_settings()
app = FastAPI(title=settings.app_name, version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
def startup_event() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_seed_data(db)
        db.commit()
    finally:
        db.close()


@app.get('/healthz')
def healthz() -> dict:
    return {'ok': True}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(webhook.router, prefix=settings.api_prefix)
app.include_router(client.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
