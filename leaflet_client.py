# special thanks to the Goby team for this!
import aiohttp
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
import time
import json
import random

class LeafletFullNodeRpcClient(FullNodeRpcClient):
    def __init__(self, leaflet_url):
        self.leaflet_url = leaflet_url
        super().__init__(
            url=leaflet_url,
            session=aiohttp.ClientSession(),
            ssl_context=None,
            hostname='localhost',
            port=1337,
        )
        self.closing_task = None


    async def fetch(self, path, request_json):
        leaflet_url = self.leaflet_url
        if "," in leaflet_url:
            leaflet_url = leaflet_url.split(",")[0]
            if 'push_tx' in path or 'get_fee_estimate' in path:
                random.choice(leaflet_url.split(",")[1:])
        
        async with self.session.post(leaflet_url + path, json=request_json) as response:
            if 'push_tx' in path or 'get_fee_estimate' in path:
                print(f"Using {leaflet_url} for {path}:", leaflet_url)

            response.raise_for_status()

            res_json = json.loads(await response.text())
            if not res_json["success"]:
                raise ValueError(res_json)
            return res_json

