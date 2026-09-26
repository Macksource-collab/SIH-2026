import logging
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError
from .config import settings
from .database import get_db
from .auth import router as auth_router
from .admin import router as admin_router
from .inspections import router as inspections_router
from .status import system_status

logging.basicConfig(level=settings.log_level)
app = FastAPI(title="PackSure AI", description="Automated Legal Metrology Compliance System", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth_router)
app.include_router(inspections_router)
app.include_router(admin_router)
from .services.routes import router as intelligence_router
app.include_router(intelligence_router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def error_response(status, message, headers=None):
    return JSONResponse(status_code=status, headers=headers,
                        content={"success": False, "detail": message, "error": {"code": status, "message": message}})


@app.exception_handler(StarletteHTTPException)
async def http_error(request, error):
    return error_response(error.status_code, str(error.detail), error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Never return submitted values (which could include a password).
    return error_response(422, "Invalid request. Check the required fields, email, password length, and UUID values.")


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    logging.getLogger("packsure").error("Database request failed (%s)", type(error).__name__)
    return error_response(503, "Database unavailable. Please try again later.")


@app.exception_handler(OSError)
async def storage_error(request, error):
    logging.getLogger("packsure").error("Storage request failed (%s)", type(error).__name__)
    return error_response(503, "Storage unavailable. Please try again later.")


@app.exception_handler(Exception)
async def unexpected_error(request, error):
    logging.getLogger("packsure").error("Unexpected request failure (%s)", type(error).__name__)
    return error_response(500, "An unexpected server error occurred.")


@app.get("/")
def home():
    return {"message": "PackSure AI backend is running"}


@app.get("/health")
def health(db=Depends(get_db)):
    service_status = system_status(db)
    components = service_status["components"]
    if any(components[name]["status"] == "OFFLINE" for name in ("database", "upload_storage", "report_storage")):
        return error_response(503, "A required service is unavailable.")
    return {"status": "healthy", "api": "online",
            "database": components["database"]["status"].lower(),
            "storage": "available" if components["upload_storage"]["status"] == "ONLINE" else "unavailable",
            **service_status}
