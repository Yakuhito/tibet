from typing import Optional
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia_rs.sized_ints import uint16

# stolen from: https://github.com/Chia-Network/chia-dev-tools/blob/8edc1e26518e5057c062a1fc97f1a16cf1de9a8b/cdv/cmds/rpc.py#L39
# Loading the client requires the standard chia root directory configuration that all of the chia commands rely on
async def get_client() -> Optional[FullNodeRpcClient]:
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        full_node_rpc_port = config["full_node"]["rpc_port"]
        full_node_client: Optional[FullNodeRpcClient] = await FullNodeRpcClient.create(
            self_hostname, uint16(full_node_rpc_port), DEFAULT_ROOT_PATH, config
        )
        return full_node_client
    except Exception as e:
        print(f"Connection error. Check if full node is running at {full_node_rpc_port}\n{e}")
        return None