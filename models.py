# models.py
from sqlalchemy import Column, String, BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Pair(Base):
    __tablename__ = "pairs"

    launcher_id = Column(String(64), primary_key=True)
    asset_id = Column(String(64), ForeignKey("tokens.asset_id"))
    xch_reserve = Column(BigInteger)
    token_reserve = Column(BigInteger)
    liquidity = Column(BigInteger)
    last_coin_id_on_chain = Column(String(64))

    token = relationship("Token", back_populates="pair")

class Token(Base):
    __tablename__ = "tokens"

    asset_id = Column(String(64), primary_key=True)
    pair_id = Column(String(64), ForeignKey("pairs.launcher_id"))
    name = Column(String)
    short_name = Column(String)
    image_url = Column(String)
    verified = Column(Boolean)

    pair = relationship("Pair", back_populates="token")
