from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Initialize FastAPI application
app = FastAPI(
    title="Farm Doctor Backend",
    description="Backend service for Apple Fire Blight AI Detection & Reporting",
    version="1.0.0"
)

# Configure CORS (Allows communication with your React frontend)
origins = [
    "http://localhost:3000",
    "http://localhost:5173",  # Vite default local dev server
    # "https://your-frontend-domain.vercel.app" # Add your Vercel URL later
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "message": "Welcome to Farm Doctor API",
        "status": "online",
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    """
    Health check endpoint used by Render or monitoring tools 
    to verify that the server and ping services are active.
    """
    return {"status": "healthy", "service": "farm-doctor-backend"}