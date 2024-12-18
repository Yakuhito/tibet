# special thanks to the Goby team for this!
import aiohttp
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
import time
import json

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
        async with self.session.post(self.leaflet_url + path, json=request_json) as response:
            if 'push_tx' in path:
                print("push_tx response:", await response.text())

            response.raise_for_status()

            res_json = json.loads(await response.text())
            if not res_json["success"]:
                raise ValueError(res_json)
            return res_json

