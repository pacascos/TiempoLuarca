#!/usr/bin/env python3
"""Punto de entrada para TiempoLuarca."""

import uvicorn
from backend.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host=HOST, port=PORT, reload=True)
