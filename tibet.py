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
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol, SINGLETON_MOD_HASH, SINGLETON_MOD, P2_SINGLETON_MOD, SINGLETON_LAUNCHER_HASH, SINGLETON_LAUNCHER, lineage_proof_for_coinsol, puzzle_for_singleton, solution_for_singleton, generate_launcher_coin
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
from chia_rs import run_chia_program
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)

ROUTER_MOD: Program = load_clvm("../../../../../../../clvm/router.clvm", recompile=False)
PAIR_MOD: Program = load_clvm("../../../../../../../clvm/pair.clvm", recompile=False)
LIQUIDITY_TAIL_MOD: Program = load_clvm("../../../../../../../clvm/liquidity_tail.clvm", recompile=False)

ROUTER_MOD_HASH = ROUTER_MOD.get_tree_hash()
PAIR_MOD_HASH = PAIR_MOD.get_tree_hash()
LIQUIDITY_TAIL_MOD_HASH = LIQUIDITY_TAIL_MOD.get_tree_hash()

P2_SINGLETON_MOD_HASH = P2_SINGLETON_MOD.get_tree_hash()

def get_router_puzzle(pairs):
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
        Program.to(pairs)
    )

def get_pair_inner_puzzle(singleton_launcher_id, tail_hash, liquidity, xch_reserve, token_reserve):
    return PAIR_MOD.curry(
        PAIR_MOD_HASH,
        (SINGLETON_MOD_HASH, (singleton_launcher_id, SINGLETON_LAUNCHER_HASH)),
        P2_SINGLETON_MOD_HASH,
        CAT_MOD_HASH,
        LIQUIDITY_TAIL_MOD_HASH,
        OFFER_MOD_HASH,
        tail_hash,
        997,
        liquidity,
        xch_reserve,
        token_reserve
    )

def get_pair_puzzle(singleton_launcher_id, tail_hash, liquidity, xch_reserve, token_reserve):
    return puzzle_for_singleton(
        singleton_launcher_id,
        get_pair_inner_puzzle(singleton_launcher_id, tail_hash, liquidity, xch_reserve, token_reserve)
    )

def deploy_router_conditions_and_coinspend(parent_coin):
    comment: List[Tuple[str, str]] = [("tibet", "v1")]
    return launch_conditions_and_coinsol(parent_coin, get_router_puzzle(0), comment, 1)


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

unspent_singletons = {} # map launcher_id (hex string) -> [coin, creation_spend]
async def get_unspent_singleton_info(client, launcher_id):
    coin_id, creation_spend = unspent_singletons.get(launcher_id, [bytes.fromhex(launcher_id), None])

    res = await client.get_coin_record_by_name(coin_id)
    while res.spent:
        coin_spend = await client.get_puzzle_and_solution(coin_id, res.spent_block_index)
        _, conditions_dict, __ = conditions_dict_for_solution(coin_spend.puzzle_reveal, coin_spend.solution, INFINITE_COST)
        for cwa in conditions_dict[ConditionOpcode.CREATE_COIN]: #cwa = condition with args
            if len(cwa.vars) >= 2 and cwa.vars[1] == b"\x01":
                creation_spend = coin_spend
                new_coin = Coin(
                    coin_id,
                    cwa.vars[0],
                    1
                )
                coin_id = new_coin.name()
                break
        res = await client.get_coin_record_by_name(coin_id)

    unspent_singletons[launcher_id] = [res.coin, creation_spend]
    return unspent_singletons[launcher_id]

def get_pairs(last_router_coin_spend):
    pairs = []
    if last_router_coin_spend.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
        creation_inner_puzzle_hash = Program.from_bytes(bytes(last_router_coin_spend.puzzle_reveal)).uncurry()[1]
        pair_launcher_id = Coin(last_router_coin_spend.coin.name(), SINGLETON_LAUNCHER_HASH, 2).name()

        arr = Program.from_bytes(bytes(last_router_coin_spend.solution)).as_python()[-1]
        pairs = Program.from_bytes(bytes([_ for _ in creation_inner_puzzle_hash.as_iter()][-1])).uncurry()[-1]
        pairs = [_ for _ in pairs.as_iter()][-1].as_python()
        pairs.append((arr[1], pair_launcher_id))
    return pairs

async def create_pair(tail_hash):
    client = await get_full_node_client()
    master_sk_hex = ""
    try:
        master_sk_hex = open("master_private_key.txt", "r").read().strip()
    except:
        master_sk_hex = input("Master Private Key: ")
    master_sk = PrivateKey.from_bytes(bytes.fromhex(master_sk_hex))
    router_launcher_id = get_router_launcher_id()
    if router_launcher_id == "":
        print("Please set the router luncher id first.")
        return

    current_router_coin, creation_spend = await get_unspent_singleton_info(client, router_launcher_id)

    
    lineage_proof = lineage_proof_for_coinsol(creation_spend)
    pairs = get_pairs(creation_spend)
        
    router_inner_puzzle = get_router_puzzle(pairs)
    router_inner_solution = Program.to([
        current_router_coin.name(),
        bytes.fromhex(tail_hash)
    ])

    router_singleton_puzzle = puzzle_for_singleton(bytes.fromhex(router_launcher_id), router_inner_puzzle)
    router_singleton_solution = solution_for_singleton(lineage_proof, current_router_coin.amount, router_inner_solution)
    router_singleton_spend = CoinSpend(current_router_coin, router_singleton_puzzle, router_singleton_solution)

    pair_launcher_coin = Coin(current_router_coin.name(), SINGLETON_LAUNCHER_HASH, 2)
    pair_puzzle = get_pair_puzzle(
        pair_launcher_coin.name(),
        bytes.fromhex(tail_hash),
        0, 0, 0
    )

    comment: List[Tuple[str, str]] = []

    # launch_conditions_and_coinsol would not work here since we spend a coin with amount 2
    # and the solution says the amount is 1 *-*
    pair_launcher_solution = Program.to(
        [
            pair_puzzle.get_tree_hash(),
            1,
            comment,
        ]
    )
    assert_launcher_announcement = [
        ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
        std_hash(pair_launcher_coin.name() + pair_launcher_solution.get_tree_hash()),
    ]
    pair_launcher_spend = CoinSpend(
        pair_launcher_coin,
        SINGLETON_LAUNCHER,
        pair_launcher_solution,
    )

    # first condition is CREATE_COIN, which we took care of
    # important to note: router also takes care of assert_launcher_announcement, but we need it to link the fund spend to the bundle
    
    coin, synth_secret_key = await select_std_coin(client, master_sk, 2)
    fund_spend = CoinSpend(
        coin,
        puzzle_for_synthetic_public_key(synth_secret_key.get_g1()),
        solution_for_delegated_puzzle(Program.to((1, [
            [ConditionOpcode.CREATE_COIN, coin.puzzle_hash, coin.amount - 2],
            assert_launcher_announcement
        ])), [])
    )
    
    sb = await sign_std_coin_spends([router_singleton_spend, pair_launcher_spend, fund_spend], synth_secret_key)
    
    print("Pair ready to be created.")
    check = input("Type 'magic' to broadcast tx: ")

    if check.strip() == 'magic':
        resp = await client.push_tx(sb)
        print(resp)
    else:
        print("that's another word *-*")

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
    else:
        print("Unknown command.")

if __name__ == "__main__":
    asyncio.run(main())

# TAIL ID for simulator: dd0aeaff6cd317a0e130cfbec714b0fab447b64790c036899fb809f6e3e34659
# TAIL ID 2: 835adf775240dcc4bcd8c1359ecc81a6aa6c0a6ae3503e164a8576997ed404b9
# TAIL ID 3: 61833ebe885a61e8f70a39543afecb0202d9f8baaa9978cc7425dd5718076fa7
# 4: c132584ee1a9b4f3f9ed022175c588ee7cae7e552379598bb5f49cbf2815b364