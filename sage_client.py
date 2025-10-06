import requests
from pathlib import Path
from typing import Optional, List, Dict, Any
from chia_rs.sized_bytes import bytes32
from chia_rs import SpendBundle, CoinSpend, AugSchemeMPL
from enum import Enum


class CoinSortMode(str, Enum):
    AMOUNT = "amount"
    NAME = "name"


class CoinFilterMode(str, Enum):
    ALL = "all"
    SPENDABLE = "spendable"
    LOCKED = "locked"


class SageClient:
    def __init__(self):
        data_dir = Path.home() / ".local" / "share"
        
        cert_file = data_dir / "com.rigidnetwork.sage" / "ssl" / "wallet.crt"
        key_file = data_dir / "com.rigidnetwork.sage" / "ssl" / "wallet.key"
        
        self.session = requests.Session()
        self.session.cert = (str(cert_file), str(key_file))
        self.session.verify = False
        
        self.base_url = "https://localhost:9257"
    
    def sign_coin_spends(
        self,
        coin_spends: List[CoinSpend],
        auto_submit: bool,
        partial: bool,
    ) -> SpendBundle:
        url = f"{self.base_url}/sign_coin_spends"
        
        response = self.session.post(
            url,
            json=json.loads(SpendBundle(coin_spends, AugSchemeMPL.aggregate([])).to_json_dict()),
        )
        return SpendBundle.from_json_dict(response.json()['spend_bundle'])
    
    def make_offer(
        self,
        requested_assets: List[[Optional[bytes32], Optional[bytes32], int]],
        offered_assets: List[[Optional[bytes32], Optional[bytes32], int]],
        fee: int,
        auto_import: bool = False,
    ) -> str:
        url = f"{self.base_url}/make_offer"

        ra = []
        for rai in requested_assets:
            ra.append({
                'asset_id': rai[0].hex() if rai[0] is not None else None,
                'hidden_puzzle_hash': rai[1].hex() if rai[1] is not None else None,
                'amount': rai[2],
            })

        oa = []
        for oai in offered_assets:
            oa.append({
                'asset_id': oai[0].hex() if oai[0] is not None else None,
                'hidden_puzzle_hash': oai[1].hex() if oai[1] is not None else None,
                'amount': oai[2],
            })

        response = self.session.post(
            url,
            json={
                "requested_assets": ra,
                "offered_assets": oa,
                "fee": fee,
                "auto_import": auto_import,
            },
        )
        return response.json()['offer']