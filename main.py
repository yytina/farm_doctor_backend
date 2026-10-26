import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from analysis_jobs import router as analysis_router
from analysis_worker import process_next_job
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()
logger = logging.getLogger(__name__)
ANALYSIS_POLL_SECONDS = float(os.getenv("ANALYSIS_POLL_SECONDS", "2"))
EMBEDDED_ANALYSIS_WORKER = os.getenv("EMBEDDED_ANALYSIS_WORKER", "true").lower() == "true"


async def run_analysis_worker() -> None:
    """Process queued analyses without blocking FastAPI request handling."""
    while True:
        try:
            claimed_job = await asyncio.to_thread(process_next_job)
        except Exception:
            logger.exception("Embedded analysis worker iteration failed")
            claimed_job = False
        await asyncio.sleep(0 if claimed_job else ANALYSIS_POLL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_task = asyncio.create_task(run_analysis_worker()) if EMBEDDED_ANALYSIS_WORKER else None
    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

# Initialize FastAPI application
app = FastAPI(
    title="Farm Doctor Backend",
    description="Backend service for Apple Fire Blight AI Detection & Reporting",
    version="1.0.0",
    lifespan=lifespan,
)

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
)

# Configure CORS (Allows communication with your React frontend)
origins = [
    "http://localhost:3000",
    "http://localhost:5173",  # Vite default local dev server
    # "https://your-frontend-domain.vercel.app" # Add your Vercel URL later
]

# Include authentication router
app.include_router(auth_router)
app.include_router(analysis_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Farm Doctor API with JWT Auth is running"}

@app.get("/health")
def health_check():
    """
    Health check endpoint used by Render or monitoring tools 
    to verify that the server and ping services are active.
    """
    return {"status": "healthy", "service": "farm-doctor-backend"}
