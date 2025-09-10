# special thanks to the Goby team for this!
import aiohttp
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
import time
import json
import random

class HttpFullNodeRpcClient(FullNodeRpcClient):
    def __init__(self, rpc_url):
        self.rpc_url = rpc_url
        super().__init__(
            url=rpc_url,
            session=aiohttp.ClientSession(),
            ssl_context=None,
            hostname='localhost',
            port=1337,
        )
        self.closing_task = None


    async def fetch(self, path, request_json):
        rpc_url = self.rpc_url
        if "," in rpc_url:
            rpc_url = rpc_url.split(",")[0]
            if 'push_tx' in path or 'get_fee_estimate' in path:
                rpc_url = random.choice(self.rpc_url.split(",")[1:])
        
        async with self.session.post(rpc_url + path, json=request_json) as response:
            if 'push_tx' in path or 'get_fee_estimate' in path:
                print(f"Using {rpc_url} for {path}:", rpc_url)
                print("Response:", await response.text())

            response.raise_for_status()

            res_json = json.loads(await response.text())
            if not res_json["success"]:
                raise ValueError(res_json)
            return res_json

