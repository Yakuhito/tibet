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
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.puzzles.tails import GenesisById
from chia.wallet.puzzles.cat_loader import CAT_MOD, CAT_MOD_HASH

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

async def sign_std_coin_spends(coin_spends, synth_sk):
    async def pk_to_sk(pk):
       return synth_sk

    return await sign_coin_spends(
        coin_spends,
        pk_to_sk,
        DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
        DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
    )

    
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

    p2_coin_spend = CoinSpend(
        parent_coin,
        puzzle_for_synthetic_public_key(synth_secret_key.get_g1()),
        solution_for_delegated_puzzle(Program.to((1, conds)), [])
    )
    print(p2_coin_spend)
        
    sb = await sign_std_coin_spends(
        [launcher_coin_spend, p2_coin_spend],
        synth_secret_key
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

        return coin, synth_secret_key

    print("No coins big enough at the given address :(")

async def launch_router():
    client = await get_full_node_client()
    master_sk_hex = ""
    try:
        master_sk_hex = open("master_private_key.txt", "r").read().strip()
    except:
        master_sk_hex = input("Master Private Key: ")

    master_sk = PrivateKey.from_bytes(bytes.fromhex(master_sk_hex))
    parent_coin, synth_secret_key = await select_std_coin(client, master_sk, 3)
        
    launcher_id, sb = await launch_router_with_sk(parent_coin, synth_secret_key)

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

from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
async def launch_test_token():
    client = await get_full_node_client()
    master_sk_hex = ""
    try:
        master_sk_hex = open("master_private_key.txt", "r").read().strip()
    except:
        master_sk_hex = input("Master Private Key: ")

    master_sk = PrivateKey.from_bytes(bytes.fromhex(master_sk_hex))
    TOKEN_AMOUNT = 1000000
    coin, synth_secret_key = await select_std_coin(client, master_sk, TOKEN_AMOUNT * 10000)
    coin_id = coin.name()

    tail = GenesisById.construct([coin_id])
    tail_hash = tail.get_tree_hash()
    cat_inner_puzzle = puzzle_for_synthetic_public_key(synth_secret_key.get_g1())

    print(f"TAIL hash: {tail_hash.hex()}")
    cat_puzzle = construct_cat_puzzle(CAT_MOD, tail_hash, cat_inner_puzzle)
    cat_puzzle_hash = cat_puzzle.get_tree_hash()

    cat_creation_tx = CoinSpend(
        coin,
        cat_inner_puzzle, # same as this coin's puzzle
        solution_for_delegated_puzzle(Program.to((1, [
            [ConditionOpcode.CREATE_COIN, cat_puzzle_hash, TOKEN_AMOUNT * 10000],
            [ConditionOpcode.CREATE_COIN, coin.puzzle_hash, coin.amount - TOKEN_AMOUNT * 10000],
        ])), [])
    )
    
    cat_coin = Coin(
        coin.name(), # parent
        cat_puzzle_hash,
        TOKEN_AMOUNT * 10000
    )

    cat_inner_solution = solution_for_delegated_puzzle(
        Program.to((1, [
            [ConditionOpcode.CREATE_COIN, 0, -113, tail, []],
            [ConditionOpcode.CREATE_COIN, cat_inner_puzzle.get_tree_hash(), cat_coin.amount]
        ])), []
    )

    cat_eve_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        [
            SpendableCAT(
                cat_coin,
                tail_hash,
                cat_inner_puzzle,
                cat_inner_solution,
                limitations_program_reveal=tail,
            )
        ],
    )
    cat_eve_spends = cat_eve_spend_bundle.coin_spends
    
    sb = await sign_std_coin_spends([cat_creation_tx] + cat_eve_spends, synth_secret_key)

    print("Spend bundle: ", sb)
    check = input("Type 'liftoff' to broadcast tx: ")
    if check.strip() == 'liftoff':
        resp = await client.push_tx(sb)
        print(resp)
    else:
        print("that's another word *-*")

    client.close()
    await client.await_closed()

unspent_singletons = {} # map launcher_id (hex string) -> last_coin_id (bytes)
async def get_unspent_singleton(client, launcher_id):
    coin_id = unspent_singletons.get(launcher_id, bytes.fromhex(launcher_id))

    res = await client.get_coin_record_by_name(coin_id)
    while res.spent:
        coin_spend = await client.get_puzzle_and_solution(coin_id, res.spent_block_index)
        print(coin_spend)
        break

    unspent_singletons[launcher_id] = coin_id
    return coin_id

async def create_pair(tail_hash):
    client = await get_full_node_client()

    router_launcher_id = get_router_launcher_id()
    if router_launcher_id == "":
        print("Please set the router luncher id first.")
        return

    current_router_coin = await get_unspent_singleton(client, router_launcher_id)
    print(current_router_coin)

    client.close()
    await client.await_closed()
    
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

# TAIL ID for simulator: dd0aeaff6cd317a0e130cfbec714b0fab447b64790c036899fb809f6e3e34659