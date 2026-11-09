
from fastapi import FastAPI

app = FastAPI(
    title="ServerPulse API",
    description="Centralized Windows Log Collection and Monitoring System",
    version="1.0.0"
)


@app.get("/")
async def root():
    return {
        "message": "Welcome to ServerPulse API",
        "status": "Running"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy"
    }
