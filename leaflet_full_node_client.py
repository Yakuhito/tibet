# special thanks to the Goby team for this!
import aiohttp
from chia.rpc.full_node_rpc_client import FullNodeRpcClient

class FullNodeRpcClient(FullNodeRpcClient):
    def __init__(self, leaflet_url):
        self.leaflet_url = leaflet_url
        super().__init__()
        self.session = aiohttp.ClientSession()
        self.closing_task = None


    async def fetch(self, path, request_json):
        async with self.session.post(self.url + path, json=request_json) as response:
            response.raise_for_status()
            res_json = await response.json()
            if not res_json["success"]:
                raise ValueError(res_json)
            return res_json

