# schemas.py
from pydantic import BaseModel
from typing import Optional
from enum import Enum

class TokenBase(BaseModel):
    asset_id: str
    pair_id: str
    name: str
    short_name: str
    image_url: Optional[str] = None
    verified: bool

class Token(TokenBase):
    class Config:
        orm_mode = True

class PairBase(BaseModel):
    launcher_id: str
    asset_id: str
    liquidity_asset_id: str
    xch_reserve: int
    token_reserve: int
    liquidity: int
    last_coin_id_on_chain: str

class Pair(PairBase):
    class Config:
        orm_mode = True

class RouterBase(BaseModel):
    launcher_id: str
    current_id: str
    network: str

class Router(RouterBase):
    class Config:
        orm_mode = True

class Quote(BaseModel):
    amount_in: int
    amount_out: int
    price_warning: bool
    fee: Optional[int]
    asset_id: str
    input_reserve: int
    output_reserve: int

class OfferResponse(BaseModel):
    success: bool
    message: str

class ActionType(Enum):
    SWAP = "SWAP"
    ADD_LIQUIDITY = "ADD_LIQUIDITY"
    REMOVE_LIQUIDITY = "REMOVE_LIQUIDITY"
