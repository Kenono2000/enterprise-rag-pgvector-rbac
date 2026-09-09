import uvicorn
from sdlc_harness_main import app

# This file is now a redirect to the modular sdlc_harness_main.py 
# to maintain compatibility with existing deployment configurations (e.g., Render).

if __name__ == "__main__":
    uvicorn.run("sdlc_harness_main:app", host="0.0.0.0", port=8000, reload=True)

