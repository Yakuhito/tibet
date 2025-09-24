# schemas.py
from pydantic import BaseModel
from typing import Optional
from enum import Enum

class TokenBase(BaseModel):
    asset_id: str
    hidden_puzzle_hash: Optional[str] = None
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
    inverse_fee: int
    liquidity_asset_id: str
    xch_reserve: int
    token_reserve: int
    liquidity: int
    last_coin_id_on_chain: str

class Pair(PairBase):
    class Config:
        orm_mode = True

class ApiPairBase(BaseModel):
    pair_id: str
    asset_id: str
    asset_name: str
    asset_short_name: str
    asset_image_url: Optional[str] = None
    asset_verified: bool
    pair_inverse_fee: int
    pair_liquidity_asset_id: str
    pair_xch_reserve: int
    pair_token_reserve: int
    pair_liquidity: int
    pair_last_coin_id_on_chain: str

class ApiPair(ApiPairBase):
    class Config:
        orm_mode = True

class RouterBase(BaseModel):
    launcher_id: str
    current_id: str
    rcat: bool

class Router(RouterBase):
    class Config:
        orm_mode = True

class Quote(BaseModel):
    amount_in: int
    amount_out: int
    price_warning: bool
    price_impact: float
    fee: Optional[int]
    asset_id: str
    input_reserve: int
    output_reserve: int

class OfferResponse(BaseModel):
    success: bool
    message: str
    offer_id: str

class CreatePairResponse(BaseModel):
    success: bool
    message: str
    coin_id: str

class ActionType(Enum):
    SWAP = "SWAP"
    ADD_LIQUIDITY = "ADD_LIQUIDITY"
    REMOVE_LIQUIDITY = "REMOVE_LIQUIDITY"
