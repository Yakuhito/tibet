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

import asyncio
import models, schemas
import os
import sys
import time
import json
import traceback
import requests

from tibet_lib import *

DATABASE_URL = "sqlite:///./database.db"

app = FastAPI(title="TibetSwap API", description="A centralized API for a decentralized AMM", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

coinset_url = None
dexie_token_url = None
spacescan_token_url = None
try:
    coinset_url = os.environ["COINSET_URL"]
    dexie_token_url = os.environ["DEXIE_TOKEN_URL"]
    dexie_offer_url = os.environ["DEXIE_OFFER_URL"]
    spacescan_token_url = os.environ["SPACESCAN_TOKEN_URL"]
    router_launcher_id = os.environ["TIBETSWAP_LAUNCHER_ID"]
    rcat_router_launcher_id = os.environ["TIBETSWAP_RCAT_LAUNCHER_ID"]
except KeyError as e:
    print(f"Error: Environment variable {e} is not set. Exiting...")
    sys.exit(1)

full_node_client = None

async def get_client():
    global full_node_client
    
    if full_node_client is None:
        full_node_client = await get_full_node_client("~/.chia/mainnet", coinset_url)
    return full_node_client

engine = create_engine(DATABASE_URL, pool_size=50, max_overflow=0)
models.Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    init_router(db)
    try:
        yield db
    finally:
        db.close()

def create_api_pair(pair: models.Pair, token: models.Token) -> schemas.ApiPair:
    """Utility function to convert a DB pair and token to an ApiPair schema"""
    return schemas.ApiPair(
        pair_id=pair.launcher_id,
        asset_id=pair.asset_id,
        asset_name=token.name,
        asset_short_name=token.short_name,
        asset_image_url=token.image_url,
        asset_verified=token.verified,
        pair_inverse_fee=pair.inverse_fee,
        pair_liquidity_asset_id=pair.liquidity_asset_id,
        pair_xch_reserve=pair.xch_reserve,
        pair_token_reserve=pair.token_reserve,
        pair_liquidity=pair.liquidity,
        pair_last_coin_id_on_chain=pair.last_coin_id_on_chain
    )

@app.get("/tokens", response_model=List[schemas.Token])
def get_tokens(db: Session = Depends(get_db)):
    return db.query(models.Token).all()

@app.get("/pairs", response_model=List[schemas.ApiPair])
def read_pairs(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    # Get all pairs and tokens in one query each to minimize DB calls
    pairs = db.query(models.Pair).order_by(models.Pair.xch_reserve.desc()).all()
    tokens = db.query(models.Token).all()
    
    # Create a map of asset_id to token for quick lookup
    token_map = {token.asset_id: token for token in tokens}
    
    # Convert pairs to ApiPair objects
    api_pairs = []
    for pair in pairs:
        token = token_map.get(pair.asset_id)
        if token:  # Only include pairs that have corresponding tokens
            api_pairs.append(create_api_pair(pair, token))
    
    return api_pairs[skip : skip + limit]

@app.get("/token/{asset_id}", response_model=schemas.Token)
def get_token(asset_id: str, db: Session = Depends(get_db)):
    token = db.query(models.Token).get(asset_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return token

@app.get("/pair/{launcher_id}", response_model=schemas.Pair)
async def read_pair(launcher_id: str, db: Session = Depends(get_db)):
    pair = await get_pair(db, launcher_id, force_refresh=True)
    if pair is None:
        raise HTTPException(status_code=404, detail="Pair not found")
    return pair

@app.get("/router", response_model=schemas.Router, summary="Get Router", description="Fetch the current Router object.")
async def get_router_endpoint(rcat: bool = Query(False, description="Whether to fetch the rCAT router"), db: Session = Depends(get_db)):
    router = db.query(models.Router).filter(models.Router.rcat == rcat).first()
    if router is None:
        raise HTTPException(status_code=404, detail="Router not found")
    return router

def init_router(db: Session):
    global router_launcher_id, rcat_router_launcher_id
    # Check if routers already exist
    existing_routers = db.query(models.Router).all()
    if len(existing_routers) >= 2:
        return existing_routers[0]  # Return any existing router

    # Create regular router if it doesn't exist
    regular_router = db.query(models.Router).filter(models.Router.rcat == False).first()
    if regular_router is None:
        regular_router = models.Router(
            launcher_id=router_launcher_id,
            current_id=router_launcher_id,
            rcat=False
        )
        db.add(regular_router)

    # Create rCAT router if it doesn't exist
    rcat_router = db.query(models.Router).filter(models.Router.rcat == True).first()
    if rcat_router is None:
        rcat_router = models.Router(
            launcher_id=rcat_router_launcher_id,
            current_id=rcat_router_launcher_id,
            rcat=True
        )
        db.add(rcat_router)

    db.commit()
    db.refresh(regular_router)
    return regular_router

async def get_pair(db: Session, pair_id: str, force_refresh: bool = False) -> models.Pair:
    pair = db.query(models.Pair).filter(models.Pair.launcher_id == pair_id).first()
    
    if pair is not None and force_refresh:
        pair, _ = await check_pair_update(db, pair)
    
    return pair

async def check_pair_update(db: Session, pair: models.Pair) -> models.Pair:
    client = await get_client()

    _, _, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        client, bytes.fromhex(pair.last_coin_id_on_chain)
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

def get_input_price(input_amount, input_reserve, output_reserve) -> int:
    input_amount_with_fee = input_amount * 993
    numerator = input_amount_with_fee * output_reserve
    denominator = (input_reserve * 1000) + input_amount_with_fee
    return numerator // denominator

def get_output_price(output_amount, input_reserve, output_reserve) -> int:
    numerator: uint256 = input_reserve * output_amount * 1000
    denominator: uint256 = (output_reserve - output_amount) * 993
    return numerator // denominator + 1

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

    # https://docs.mimo.finance/the-formulas#price-impact
    price_impact = 1 - (output_reserve - amount_out) ** 2 / output_reserve ** 2

    # warn price change when price impact > 5%
    price_warning = price_impact > 0.05

    recommended_fee = None
    if estimate_fee:
        recommended_fee = await get_fee_estimate(mempool_sb, await get_client())

    quote = schemas.Quote(
        amount_in=amount_in,
        amount_out=amount_out,
        price_warning=price_warning,
        price_impact=price_impact,
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

async def create_offer(
    db: Session,
    pair_id: str,
    offer: str,
    action: schemas.ActionType,
    total_donation_amount: float,
    donation_addresses: List[str],
    donation_weights: List[int]
) -> schemas.OfferResponse:
    total_donation_amount: int = int(total_donation_amount)
    if total_donation_amount < 0:
        raise HTTPException(status_code=400, detail="total_donation_amount negative")

    fee_share_address = os.environ.get("TIBETSWAP_FEE_ADDRESS", "")
    if len(donation_addresses) > 0 and len(fee_share_address) > 0:
        given_shares = 0
        for i, address in enumerate(donation_addresses):
            if address == fee_share_address:
                given_shares += donation_weights[i]
        if given_shares / sum(donation_weights) < 0.5:
            raise HTTPException(status_code=400, detail=f"To use this endpoint, please provide at least 50% of fees to our address: {fee_share_address}")

    pair = await get_pair(db, pair_id)
    if pair is None:
        raise HTTPException(status_code=400, detail="Unknown pair id (launcher id)")
    
    sb = None
    offerId = "" # will be set outside function
    try:
        client = await get_client()

        current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
            client, bytes.fromhex(pair.last_coin_id_on_chain)
        )
        current_pair_coin_id = current_pair_coin.name().hex()

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            client,
            bytes.fromhex(pair.launcher_id),
            current_pair_coin,
            bytes.fromhex(pair.asset_id),
            None,  # token_hidden_puzzle_hash - assume None for now
            creation_spend,
            sb_to_aggregate
        )

        if action == schemas.ActionType.SWAP:
            sb = await respond_to_swap_offer(
                bytes.fromhex(pair.launcher_id),
                current_pair_coin,
                creation_spend,
                bytes.fromhex(pair.asset_id),
                None,  # token_hidden_puzzle_hash - assume None for now
                993,   # inverse_fee - default for regular pairs
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof,
                total_donation_amount=total_donation_amount,
                donation_addresses=donation_addresses,
                donation_weights=donation_weights
            )
        elif action == schemas.ActionType.ADD_LIQUIDITY:
            sb = await respond_to_deposit_liquidity_offer(
                bytes.fromhex(pair.launcher_id),
                current_pair_coin,
                creation_spend,
                bytes.fromhex(pair.asset_id),
                None,  # token_hidden_puzzle_hash - assume None for now
                993,   # inverse_fee - default for regular pairs
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof
            )
        elif action == schemas.ActionType.REMOVE_LIQUIDITY:
            sb = await respond_to_remove_liquidity_offer(
                bytes.fromhex(pair.launcher_id),
                current_pair_coin,
                creation_spend,
                bytes.fromhex(pair.asset_id),
                None,  # token_hidden_puzzle_hash - assume None for now
                993,   # inverse_fee - default for regular pairs
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof
            )

        if sb_to_aggregate is not None:
            sb = SpendBundle.aggregate([sb, sb_to_aggregate])

        try:
            resp = await client.push_tx(sb)
        except Exception as e:
            resp = {}
            resp['status'] = 'FAILED'
            resp['message'] = json.dumps({
                "traceback": traceback.format_exc(),
                "pair_id": pair_id,
                "action": str(action)
            })
            t = int(time.time())
            
        success = resp['status'] == 'SUCCESS'
        response = schemas.OfferResponse(
            success=success,
            message=json.dumps(resp),
            offer_id=offerId
        )

        return response
    except Exception as e:
        traceback_message = traceback.format_exc()
        msg=json.dumps({
                "traceback": traceback_message,
                "pair_id": pair_id,
                "action": str(action)
            })
        response = schemas.OfferResponse(
            success=False,
            message=msg,
            offer_id=offerId
        )
        t = int(time.time())
        
        return response
        

@app.post("/offer/{pair_id}", response_model=schemas.OfferResponse)
async def create_offer_endpoint(pair_id: str,
                                offer: str = Body(...),
                                action: schemas.ActionType = Body(...),
                                total_donation_amount: float = Body(0.0),
                                donation_addresses: List[str] = Body([]),
                                donation_weights: List[int] = Body([]),
                                db: Session = Depends(get_db)):
    global dexie_offer_url
    
    total_donation_amount: int = int(total_donation_amount)
    response = await create_offer(
        db,
        pair_id,
        offer,
        action,
        total_donation_amount,
        donation_addresses,
        donation_weights
    )

    try:
        if response.success:
            # this is a very important print statement
            # do not remove under any circumstance 
            r = requests.post(dexie_offer_url, json={"offer": offer, "drop_only": True}, headers={"User-Agent": "TibetSwap v2 fren"})
            # edit: I had to separate the original print statement in two parts
            # but I did not remove it!
            print(r.text)

            resp = r.json()
            if resp["success"]:
                response.offer_id = resp["id"]
    except:
        pass
    return response

@app.post("/pair/{asset_id}", response_model=schemas.CreatePairResponse)
async def create_pair_endpoint(asset_id: str,
                                offer: str = Body(...),
                                xch_liquidity: int = Body(1),
                                token_liquidity: int = Body(1),
                                liquidity_destination_address: str = Body(""),
                                db: Session = Depends(get_db)):

    # For now, assume hidden_puzzle_hash=None as requested
    hidden_puzzle_hash = None
    
    # Get the appropriate router (regular router for now)
    router = db.query(models.Router).filter(models.Router.rcat == False).first()
    if router is None:
        raise HTTPException(status_code=500, detail="Router not found")
    
    pair = await get_pair(db, asset_id)
    if pair is not None:
        return schemas.CreatePairResponse(success=False, message="Pair for asset already exists", coin_id="")

    try:
        client = await get_client()

        current_router_coin, latest_creation_spend, pairs = await sync_router(
            client, bytes.fromhex(router.current_id), False  # rcat=False for regular router
        )

        sb = await create_pair_with_liquidity(
            bytes.fromhex(asset_id),
            hidden_puzzle_hash,
            993,  # default inverse_fee for regular pairs
            offer,
            int(xch_liquidity),
            int(token_liquidity),
            liquidity_destination_address,
            bytes.fromhex(router.launcher_id),
            current_router_coin,
            latest_creation_spend,
            additional_data=bytes.fromhex(os.environ.get("AGG_SIG_ME_ADDITIONAL_DATA", DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA.hex()))
        )

        try:
            resp = await client.push_tx(sb)
        except Exception as e:
            resp = {}
            resp['status'] = 'FAILED'
            resp['message'] = json.dumps({
                "traceback": traceback.format_exc(),
            })
        
        return schemas.CreatePairResponse(
            success=resp['status'] == 'SUCCESS',
            message=json.dumps(resp),
            coin_id=sb.coin_spends[-1].name().hex()
        )
    except Exception as e:
        traceback_message = traceback.format_exc()
        
        return schemas.CreatePairResponse(
            success=False,
            message=json.dumps({
                "traceback": traceback_message
            }),
            coin_id=""
        )

@app.get("/")
async def root():
    return {"message": "TibetSwap API is running"}
