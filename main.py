from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

# Initialize FastAPI application
app = FastAPI(
    title="Farm Doctor Backend",
    description="Backend service for Apple Fire Blight AI Detection & Reporting",
    version="1.0.0"
)

supabase: Client = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")
)

# Configure CORS (Allows communication with your React frontend)
origins = [
    "http://localhost:3000",
    "http://localhost:5173",  # Vite default local dev server
    # "https://your-frontend-domain.vercel.app" # Add your Vercel URL later
]

# Include authentication router
app.include_router(auth_router)

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