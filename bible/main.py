from fastapi import FastAPI
from bible.common import _get_version
import uvicorn

from bible.api import (system_router)

app = FastAPI()

@app.get("/")
async def read_root():
    return {"Hello": "World"}

def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application.
    """
    app = FastAPI(title="BiBLE-Atlas", description="BiBLE-Atlas: Agent-native context DB", version=_get_version())
    
    # Include your API routes here
    # e.g., app.include_router(your_router)
    app.include_router(system_router)  # Make sure to import and include your API router

    return app

def main():
    """
    Main entry point for the BiBLE-Atlas application.
    """
    # Add your application logic here
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=5555, log_config=None)
    pass

if __name__ == "__main__":
    main()