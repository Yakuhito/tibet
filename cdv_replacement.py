from chia.cmds.cmds_util import format_bytes
from chia.consensus.block_record import BlockRecord
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.full_block import FullBlock
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint64

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