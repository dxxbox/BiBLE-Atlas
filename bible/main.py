from fastapi import FastAPI
from bible.common import _get_version
import uvicorn

from bible.api import knowledge_router, system_router

from bible.common.logger import get_logger

logger = get_logger(__name__)

def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application.
    """
    app = FastAPI(title="BiBLE-Atlas", description="BiBLE-Atlas: Agent-native context DB", version=_get_version())
    
    # Include your API routes here
    # e.g., app.include_router(your_router)
    app.include_router(system_router)
    app.include_router(knowledge_router)

    return app

def main():
    """
    Main entry point for the BiBLE-Atlas application.
    """
    # Add your application logic here
    app = create_app()
    logger.info("Starting BiBLE-Atlas application...")
    uvicorn.run(app, host="127.0.0.1", port=5555, log_config=None)


if __name__ == "__main__":
    main()