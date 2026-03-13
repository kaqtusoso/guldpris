# api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json, glob, os

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

@app.get("/priser")
def get_priser():
    filer = sorted(glob.glob("Guldpriser/*.json"))
    with open(filer[-1], encoding="utf-8") as f:
        return json.load(f)
