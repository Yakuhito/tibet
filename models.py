# models.py
from sqlalchemy import Column, String, BigInteger, Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Pair(Base):
    __tablename__ = "pairs"

    launcher_id = Column(String(64), primary_key=True)
    asset_id = Column(String(64))
    inverse_fee = Column(BigInteger)
    liquidity_asset_id = Column(String(64))
    xch_reserve = Column(BigInteger)
    token_reserve = Column(BigInteger)
    liquidity = Column(BigInteger)
    last_coin_id_on_chain = Column(String(64))

class Token(Base):
    __tablename__ = "tokens"

    asset_id = Column(String(64), primary_key=True)
    hidden_puzzle_hash = Column(String(64), nullable=True)
    name = Column(Text)
    short_name = Column(Text)
    image_url = Column(Text)
    verified = Column(Boolean)

class Router(Base):
    __tablename__ = "router"

    launcher_id = Column(String(64), primary_key=True)
    current_id = Column(String(64))
    rcat = Column(Boolean)
