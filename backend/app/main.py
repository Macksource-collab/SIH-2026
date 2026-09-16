from fastapi import FastAPI


app = FastAPI(
    title="PackSure AI",
    description="Automated Legal Metrology Compliance System",
    version="1.0.0",
)


@app.get("/")
def home():
    return {
        "message": "PackSure AI backend is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }