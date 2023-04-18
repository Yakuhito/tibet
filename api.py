# main.py
# special thanks to GPT-4
from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi import Query
from typing import List
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from typing import Optional
from cachetools import cached, TTLCache

from sentry_sdk import capture_exception, capture_message
import sentry_sdk

import asyncio
import models, schemas
import os
import sys
import time
import json
import traceback

from tibet_lib import *

DATABASE_URL = "sqlite:///./database.db"

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production,
    traces_sample_rate=1.0,
)


app = FastAPI(title="TibetSwap API", description="A centralized API for a decentralized AMM", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cache = TTLCache(maxsize=100, ttl=3)

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

# Add these two global variables
last_check_router_update_call = datetime.now() - timedelta(minutes=1)
router_instance = None
last_pair_update = {}

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

@cached(cache)
@app.get("/tokens", response_model=List[schemas.Token])
def get_tokens(db: Session = Depends(get_db)):
    return db.query(models.Token).all()


@cached(cache)
@app.get("/pairs", response_model=List[schemas.Pair])
async def read_pairs(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    pairs = await get_all_pairs(db)
    return pairs[skip : skip + limit]


@cached(cache)
@app.get("/token/{asset_id}", response_model=schemas.Token)
def get_token(asset_id: str, db: Session = Depends(get_db)):
    token = db.query(models.Token).get(asset_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return token

@cached(cache)
@app.get("/pair/{launcher_id}", response_model=schemas.Pair)
async def read_pair(launcher_id: str, db: Session = Depends(get_db)):
    pair = await get_pair(db, launcher_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="Pair not found")
    return pair

@cached(cache)
@app.get("/router", response_model=schemas.Router, summary="Get Router", description="Fetch the current Router object.")
async def get_router(db: Session = Depends(get_db)):
    return await get_router()


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


async def get_router():
    global last_check_router_update_call
    global router_instance

    now = datetime.now()

    if router_instance is None:
        with SessionLocal() as db:
            router_instance = init_router(db)

    # Check if check_router_update was called in the last minute
    if now - last_check_router_update_call >= timedelta(minutes=1):
        last_check_router_update_call = now
        update = None
        with SessionLocal() as db:
            update = await check_router_update(db)
        if update is not None:
            router_instance.current_id = update[0]
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
                    liquidity_asset_id=pair_liquidity_tail_puzzle(bytes.fromhex(pair_launcher_id)).get_tree_hash().hex(),
                    xch_reserve=0,
                    token_reserve=0,
                    liquidity=0,
                    last_coin_id_on_chain=pair_launcher_id,
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
                        name=f"CAT 0x{pair_tail_hash[:8]}",
                        short_name=f"???",
                        image_url="https://bafybeigzcazxeu7epmm4vtkuadrvysv74lbzzbl2evphtae6k57yhgynp4.ipfs.dweb.link/9098.gif",
                        verified=False,
                    )
                db.add(token)
                db.commit()

    return router_instance

async def get_pair(db: Session, pair_id: str, force_refresh: bool = False) -> models.Pair:
    global last_pair_update
    
    pair = db.query(models.Pair).filter(models.Pair.launcher_id == pair_id).first()
    now = datetime.now()
    
    if pair is not None:
        last_update = last_pair_update.get(pair_id)
        if force_refresh or last_update is None or now - last_update >= timedelta(seconds=5):
            last_pair_update[pair_id] = now
            pair, _ = await check_pair_update(db, pair)
    
    return pair


async def get_all_pairs(db: Session, force_refresh: bool = False) -> List[models.Pair]:
    pairs = db.query(models.Pair).all()

    for pair in pairs:
        pair_id = pair.launcher_id
        last_update = last_pair_update.get(pair_id)

        now = datetime.now()
        if force_refresh or last_update is None or now - last_update >= timedelta(seconds=5):
            last_pair_update[pair_id] = now
            pair, _ = await check_pair_update(db, pair)

    return pairs


async def check_pair_update(db: Session, pair: models.Pair) -> models.Pair:
    client = await get_client()

    _, _, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        client, bytes.fromhex(pair.last_coin_id_on_chain), bytes.fromhex(pair.asset_id)
    )

    pair.xch_reserve = pair_state['xch_reserve'] 
    pair.token_reserve = pair_state['token_reserve']
    pair.liquidity = pair_state['liquidity']
    pair.last_coin_id_on_chain = last_synced_pair_id_on_blockchain.hex()
    
    # Commit the update to the database
    db.add(pair)
    db.commit()
    db.refresh(pair)
    
    return pair, sb_to_aggregate

def get_input_price(input_amount, input_reserve, output_reserve):
    input_amount_with_fee = input_amount * 993
    numerator = input_amount_with_fee * output_reserve
    denominator = (input_reserve * 1000) + input_amount_with_fee
    return numerator / denominator

def get_output_price(output_amount, input_reserve, output_reserve):
    numerator: uint256 = input_reserve * output_amount * 1000
    denominator: uint256 = (output_reserve - output_amount) * 993
    return numerator / denominator + 1

async def get_quote(db: Session, pair_id: str, amount_in: Optional[int], amount_out: Optional[int], xch_is_input: bool, estimate_fee: bool = False) -> schemas.Quote:
    # Fetch the pair with the given launcher_id
    pair = await get_pair(db, pair_id)
    if pair is None:
        raise HTTPException(status_code=400, detail="Unknown pair id (launcher id)")

    mempool_sb = None
    if estimate_fee:
        pair, mempool_sb = await check_pair_update(db, pair)

    xch_reserve = pair.xch_reserve
    token_reserve = pair.token_reserve

    input_reserve, output_reserve = pair.token_reserve, pair.xch_reserve
    if xch_is_input:
        input_reserve, output_reserve = pair.xch_reserve, pair.token_reserve

    if amount_in is None: 
        # amount_out given
        amount_in = get_output_price(amount_out, input_reserve, output_reserve)
    else:
        # amount_in given
        amount_out = get_input_price(amount_in, input_reserve, output_reserve)

    # warn price change when traded amount > 2% of reserves
    price_warning = amount_in > input_reserve / 50 or amount_out > output_reserve / 50

    recommended_fee = None
    if estimate_fee:
        recommended_fee = await get_fee_estimate(mempool_sb, await get_client())

    quote = schemas.Quote(
        amount_in=amount_in,
        amount_out=amount_out,
        price_warning=price_warning,
        fee=recommended_fee,
        asset_id=pair.asset_id,
        input_reserve=input_reserve,
        output_reserve=output_reserve
    )

    return quote

@app.get("/quote/{pair_id}", response_model=schemas.Quote)
async def read_quote(pair_id: str, amount_in: Optional[int] = Query(None), amount_out: Optional[int] = Query(None), xch_is_input: bool = True, estimate_fee: bool = False, db: Session = Depends(get_db)):
    # Ensure that either amount_in or amount_out is provided, but not both
    if (amount_in is not None) == (amount_out is not None):
        raise HTTPException(status_code=400, detail="Provide either amount_in or amount_out, but not both")

    quote = await get_quote(db, pair_id, amount_in, amount_out, xch_is_input, estimate_fee)
    return quote


async def create_offer(db: Session, pair_id: str, offer: str, action: schemas.ActionType, return_address: str = DEFAULT_RETURN_ADDRESS) -> schemas.OfferResponse:
    pair = await get_pair(db, pair_id)
    if pair is None:
        raise HTTPException(status_code=400, detail="Unknown pair id (launcher id)")
    
    try:
        client = await get_client()

        current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
            client, bytes.fromhex(pair.last_coin_id_on_chain), bytes.fromhex(pair.asset_id)
        )
        current_pair_coin_id = current_pair_coin.name().hex()

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            client,
            bytes.fromhex(pair.launcher_id),
            current_pair_coin,
            bytes.fromhex(pair.asset_id),
            creation_spend,
            sb_to_aggregate
        )

        sb = None

        if action == schemas.ActionType.SWAP:
            sb = await respond_to_swap_offer(
                bytes.fromhex(pair.launcher_id),
                current_pair_coin,
                creation_spend,
                bytes.fromhex(pair.asset_id),
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof,
                return_address=return_address
            )
        elif action == schemas.ActionType.ADD_LIQUIDITY:
            sb = await respond_to_deposit_liquidity_offer(
                bytes.fromhex(pair.launcher_id),
                current_pair_coin,
                creation_spend,
                bytes.fromhex(pair.asset_id),
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof,
                return_address=return_address
            )
        elif action == schemas.ActionType.REMOVE_LIQUIDITY:
            sb = await respond_to_remove_liquidity_offer(
                bytes.fromhex(pair.launcher_id),
                current_pair_coin,
                creation_spend,
                bytes.fromhex(pair.asset_id),
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof,
                return_address=return_address
            )

        try:
            resp = await client.push_tx(sb)
        except:
            import time

            resp = {}
            resp['status'] = 'FAILED'
            resp['message'] = "Failed pushing tx :("
            t = int(time.time())
            open(f"spend_bundle.{t}.json", "w").write(json.dumps(sb.to_json_dict(), sort_keys=True, indent=4))
            open(f"offer.{t}.json", "w").write(offer)
            capture_message(f"{t} - Failed to push spend bundle; data written in files spend_bundle.{t}.json and offer.{t}.json")
        success = resp['status'] == 'SUCCESS'

        response = schemas.OfferResponse(
            success=success,
            message=json.dumps(resp)
        )

        return response
    except Exception as e:
        traceback_message = traceback.format_exc()
        msg=json.dumps({
                "traceback": traceback_message,
                "pair_id": pair_id,
                "action": str(action),
                "return_address": return_address,
                "offer": offer
            })
        response = schemas.OfferResponse(
            success=False,
            message=msg
        )
        import time
        open(f"offer.{time.time()}.txt", "w").write(offer)
        capture_exception(e)
        
        return response
        

@app.post("/offer/{pair_id}", response_model=schemas.OfferResponse)
async def create_offer_endpoint(pair_id: str,
                                offer: str = Body(...),
                                action: schemas.ActionType = Body(...),
                                return_address: str = Body(DEFAULT_RETURN_ADDRESS),
                                db: Session = Depends(get_db)):
    response = await create_offer(db, pair_id, offer, action, return_address)
    return response


@app.get("/")
async def root():
    return {"message": "TibetSwap API is running"}
