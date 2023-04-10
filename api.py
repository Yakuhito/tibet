# main.py
# special thanks to GPT-4
from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import Session
from fastapi import Depends
from typing import List
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import models, schemas

DATABASE_URL = "sqlite:///./database.db"

app = FastAPI(title="TibetSwap API", description="A centralized API for a decentralized AMM", version="1.0.0")

engine = create_engine(DATABASE_URL)
models.Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/tokens", response_model=List[schemas.Token])
def get_tokens(db: Session = Depends(get_db)):
    return db.query(models.Token).all()

@app.get("/pairs", response_model=List[schemas.Pair])
def get_pairs(db: Session = Depends(get_db)):
    return db.query(models.Pair).all()

@app.get("/token/{asset_id}", response_model=schemas.Token)
def get_token(asset_id: str, db: Session = Depends(get_db)):
    token = db.query(models.Token).get(asset_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return token

@app.get("/pair/{launcher_id}", response_model=schemas.Pair)
def get_pair(launcher_id: str, db: Session = Depends(get_db)):
    pair = db.query(models.Pair).get(launcher_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="Pair not found")
    return pair
