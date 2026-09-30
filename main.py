"""
main.py
-------
Root server entry point. Runs the consolidated FastAPI app.
"""

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
