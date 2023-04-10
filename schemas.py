# schemas.py
from pydantic import BaseModel
from typing import Optional

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
    xch_reserve: int
    token_reserve: int
    liquidity: int
    last_coin_id_on_chain: str

class Pair(PairBase):
    class Config:
        orm_mode = True
