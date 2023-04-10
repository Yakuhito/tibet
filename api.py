# main.py
# special thanks to GPT-4
from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import Session
from fastapi import Depends
from typing import List
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import asyncio
import models, schemas
import os
import sys
import time

from tibet_lib import *

DATABASE_URL = "sqlite:///./database.db"

app = FastAPI(title="TibetSwap API", description="A centralized API for a decentralized AMM", version="1.0.0")

leaflet_url = None
taildatabase_tail_info_url = None
try:
    # https://kraken.fireacademy.io/[api-key]/leaflet[-testnet10]/
    leaflet_url = os.environ["FIREACADEMYIO_LEAFLET_URL"]
    taildatabase_tail_info_url = os.environ["TAILDATABASE_TAIL_INFO_URL"]
except KeyError as e:
    print(f"Error: Environment variable {e} is not set. Exiting...")
    sys.exit(1)

full_node_client = None

async def get_client():
    global full_node_client
    
    if full_node_client is None:
        full_node_client = await get_full_node_client("~/.chia/mainnet", leaflet_url)
    return full_node_client

engine = create_engine(DATABASE_URL)
models.Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    init_router(db)
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

@app.get("/router", response_model=schemas.Router, summary="Get Router", description="Fetch the current Router object.")
def get_router(db: Session = Depends(get_db)):
    router = db.query(models.Router).first()
    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")
    return router


def init_router(db: Session):
    router = db.query(models.Router).first()
    if router is None:
        try:
            launcher_id = os.environ["TIBETSWAP_LAUNCHER_ID"]
            current_id = os.environ["TIBETSWAP_CURRENT_ID"]
            network = os.environ["TIBETSWAP_NETWORK"]
        except KeyError as e:
            print(f"Error: Environment variable {e} is not set. Exiting...")
            sys.exit(1)

        router = models.Router(launcher_id=launcher_id, current_id=current_id, network=network)
        db.add(router)
        db.commit()
        db.refresh(router)

    return router


async def check_router_update(db):
    router = db.query(models.Router).first()
    if router is None:
        return None
    
    try:
        client = await get_client()
        current_router_coin, _, pairs = await sync_router(
            client, bytes.fromhex(router.current_id)
        )
        router_new_current_id = current_router_coin.name().hex()

        # pairs: array of (tail_hash.hex(), pair_launcher_id.hex())
        return (router_new_current_id, pairs)
    except:
        print("exception in check_router_update")
        return None


async def update_router_and_create_pair_token():
    while True:
        with SessionLocal() as db:
            update = await check_router_update(db) # (new_current_id, pairs_to_add)

            if update is not None:
                # Update the Router object
                router = db.query(models.Router).first()
                if router:
                    router.current_id = update[0]
                    db.commit()

                pairs = update[1]
                for pair_tail_hash, pair_launcher_id in pairs:
                    pair = db.query(models.Pair).filter(models.Pair.launcher_id == pair_launcher_id).first()
                    if pair is not None:
                        continue

                    # Create a new Pair object
                    pair = models.Pair(
                        launcher_id=pair_launcher_id,
                        asset_id=pair_tail_hash,
                        xch_reserve=0,
                        token_reserve=0,
                        liquidity=0,
                        last_coin_id_on_chain=pair_tail_hash,
                    )
                    db.add(pair)
                    db.commit()

                    # Create a new Token object
                    token = None
                    try:
                        r = requests.get(taildatabase_tail_info_url + pair_tail_hash)
                        resp = r.json()
                        token = models.Token(
                            asset_id=pair_tail_hash,
                            pair_id=pair_launcher_id,
                            name=resp["name"],
                            short_name=resp["code"],
                            image_url=resp["nft_uri"],
                            verified=False,
                        )
                    except:
                        token = models.Token(
                            asset_id=pair_tail_hash,
                            pair_id=pair_launcher_id,
                            name=f"CAT 0x{pair_tail_hash[:16]}",
                            short_name=f"UNKNWN",
                            image_url="https://icons.dexie.space/8ebf855de6eb146db5602f0456d2f0cbe750d57f821b6f91a8592ee9f1d4cf31.webp",
                            verified=False,
                        )
                    db.add(token)
                    db.commit()

        await asyncio.sleep(60)

def start_background_tasks():
    loop = asyncio.get_event_loop()
    loop.create_task(update_router_and_create_pair_token())

start_background_tasks()