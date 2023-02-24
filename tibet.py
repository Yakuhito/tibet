import os
import sys
import asyncio
from pathlib import Path
from typing import List

from chia.wallet.sign_coin_spends import sign_coin_spends
from blspy import PrivateKey, AugSchemeMPL
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint64
from clvm.casts import int_to_bytes
from cdv.cmds.rpc import get_client
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol, SINGLETON_MOD_HASH, P2_SINGLETON_MOD, SINGLETON_LAUNCHER_HASH
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, calculate_synthetic_secret_key, DEFAULT_HIDDEN_PUZZLE_HASH, puzzle_for_synthetic_public_key, solution_for_delegated_puzzle
from chia.wallet.puzzles.cat_loader import CAT_MOD_HASH
from chia.wallet.trading.offer import OFFER_MOD_HASH
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from cdv.cmds.sim_utils import SIMULATOR_ROOT_PATH
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.util.config import load_config
from chia.util.ints import uint16, uint32
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.coin_spend import CoinSpend

ROUTER_MOD: Program = load_clvm("../../../../../../../clvm/router.clvm", recompile=False)
PAIR_MOD: Program = load_clvm("../../../../../../../clvm/pair.clvm", recompile=False)
LIQUIDITY_TAIL_MOD: Program = load_clvm("../../../../../../../clvm/liquidity_tail.clvm", recompile=False)

ROUTER_MOD_HASH = ROUTER_MOD.get_tree_hash()
PAIR_MOD_HASH = PAIR_MOD.get_tree_hash()
LIQUIDITY_TAIL_MOD_HASH = LIQUIDITY_TAIL_MOD.get_tree_hash()

P2_SINGLETON_MOD_HASH = P2_SINGLETON_MOD.get_tree_hash()

def get_router_puzzle_hash(pairs):
    return ROUTER_MOD.curry(
        PAIR_MOD_HASH,
        SINGLETON_MOD_HASH,
        P2_SINGLETON_MOD_HASH,
        CAT_MOD_HASH,
        LIQUIDITY_TAIL_MOD_HASH,
        OFFER_MOD_HASH,
        997,
        SINGLETON_LAUNCHER_HASH,
        ROUTER_MOD_HASH,
        pairs
    )

def get_pair_puzzle_hash(singleton_launcher_id, tail_hash, liquidity, xch_reserve, token_reserve):
    return PAIR_MOD.curry(
        PAIR_MOD_HASH,
        (SINGLETON_MOD_HASH, (singleton_launcher_id, SINGLETON_LAUNCHER_HASH)),
        CAT_MOD_HASH,
        LIQUIDITY_TAIL_MOD_HASH,
        OFFER_MOD_HASH,
        tail_hash,
        997,
        liquidity,
        xch_reserve,
        token_reserve
    )

def deploy_router_conditions_and_coinspend(parent_coin):
    comment: List[Tuple[str, str]] = [("tibet", "v1")]
    return launch_conditions_and_coinsol(parent_coin, get_router_puzzle_hash(0), comment, 1)


async def get_full_node_client() -> FullNodeRpcClient:
    try:
        client: FullNodeRpcClient = await get_client()
        await client.get_blockchain_state()
        return client
    except:
        client.close()
        await client.await_closed()
        pass
    
    root_path = SIMULATOR_ROOT_PATH / "main"
    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    rpc_port = config["full_node"]["rpc_port"]
    node_client: SimulatorFullNodeRpcClient = await SimulatorFullNodeRpcClient.create(
        self_hostname, uint16(rpc_port), root_path, config
    )
    await node_client.get_blockchain_state()

    return node_client


async def launch_router_with_sk(parent_coin, synth_secret_key):
    conds, launcher_coin_spend = deploy_router_conditions_and_coinspend(parent_coin)
    if parent_coin.amount > 1:
        conds.append(Program.to(
            [
                ConditionOpcode.CREATE_COIN,
                parent_coin.puzzle_hash,
                parent_coin.amount - 1,
            ],
        ))


    async def pk_to_sk(pk):
       return synth_secret_key

    p2_coin_spend = CoinSpend(
        parent_coin,
        puzzle_for_synthetic_public_key(synth_secret_key.get_g1()),
        solution_for_delegated_puzzle(Program.to((1, conds)), [])
    )
        
    sb = await sign_coin_spends(
        [launcher_coin_spend, p2_coin_spend],
        pk_to_sk,
        DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
        DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
    )

    launcher_id = launcher_coin_spend.coin.name().hex()
    
    return launcher_id, sb

def set_router_launcher_id(launcher_id):
    open("router_launcher_id.txt", "w").write(launcher_id)

def get_router_launcher_id():
    try:
        return open("router_launcher_id.txt", "r").read().strip()
    except:
        return ""

async def select_std_coin(client, master_sk, min_amount):
    ph_to_wallet_sk = {}
    for i in range(100):
        wallet_sk = master_sk_to_wallet_sk_unhardened(master_sk, i)
        synth_secret_key = calculate_synthetic_secret_key(wallet_sk, DEFAULT_HIDDEN_PUZZLE_HASH)
        synth_key = synth_secret_key.get_g1()
        puzzle = puzzle_for_synthetic_public_key(synth_key)
        puzzle_hash = puzzle.get_tree_hash()            
        ph_to_wallet_sk[puzzle_hash] = synth_secret_key

    res = await client.get_coin_records_by_puzzle_hashes(ph_to_wallet_sk.keys(), include_spent_coins=False)
    if len(res) == 0:
        if isinstance(client, SimulatorFullNodeRpcClient):
            await client.farm_block([_ for _ in ph_to_wallet_sk.keys()][0])
            return select_std_coin(client, master_sk, min_amount)
        else:
            print("No coins at the given address :(")
            sys.exit(1)
    
    for coin_record in res:
        if coin_record.coin.amount < min_amount:
            continue

        coin = coin_record.coin
        synth_secret_key = ph_to_wallet_sk[coin.puzzle_hash]

        return coin, synt_secret_key

    print("No coins big enough at the given address :(")

async def launch_router():
    client = await get_full_node_client()
    master_sk_hex = ""
    try:
        master_sk_hex = open("master_private_key.txt", "r").read().strip()
    except:
        master_sk_hex = input("Master Private Key: ")

    master_sk = PrivateKey.from_bytes(bytes.fromhex(master_sk_hex))
    parent_coin_record, synt_secret_key = await select_std_coin(client, master_sk, 2)
        
    launcher_id, sb = await launch_router_with_sk(client, parent_coin, synth_secret_key, interactive=True)

    print(f"Router launcher coin id: {launcher_id}")
    print("Spend bundle: ", sb)
    check = input("Type 'liftoff' to broadcast tx: ")

    if check.strip() == 'liftoff':
        resp = await client.push_tx(sb)
        print(resp)
        set_router_launcher_id(launcher_id)
        print("Router launcher id saved.")
    else:
        print("that's another word *-*")

    client.close()
    await client.await_closed()

def launch_test_token():

async def create_pair(tail_hash):
    router_launcher_id = get_router_launcher_id()
    if router_launcher_id == "":
        print("Please set the router luncher id first.")
        return
    
async def main():
    if len(sys.argv) < 2:
        print("Possible commands: launch_router, set_router, launch_test_token, create_pair")
    elif sys.argv[1] == "launch_router":
        await launch_router()
    elif sys.argv[1] == "set_router":
        if len(sys.argv) == 3:
            set_router_launcher_id(sys.argv[2])
        else:
            print("Usage: set_router [launcher_id]")
    elif sys.argv[1] == "launch_test_token":
        await launch_test_token()
    elif sys.argv[1] == "create_pair":
        if len(sys.argv) == 3:
            await create_pair(sys.argv[2])
        else:
            print("Usage: create_pair [tail_hash_of_asset]")

if __name__ == "__main__":
    asyncio.run(main())