from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def read_root():
    return {"Hello": "World"}

def main():
    """
    Main entry point for the BiBLE-Atlas application.
    """
    # Add your application logic here
    pass

if __name__ == "__main__":
    main()