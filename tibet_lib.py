import asyncio
import os
import sys
import time
import requests
from pathlib import Path
from secrets import token_bytes
from typing import List
import inspect
from chia.consensus.condition_tools import pkm_pairs_for_conditions_dict
from chia.util.keychain import bytes_to_mnemonic, mnemonic_to_seed
from chia_rs import AugSchemeMPL, PrivateKey, Coin, SpendBundle
from cdv_replacement import get_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.wallet.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_full_node_rpc_client import \
    SimulatorFullNodeRpcClient
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.blockchain_format.program import Program
from chia_rs.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.bech32m import bech32_decode
from chia.util.bech32m import bech32_encode
from chia.util.bech32m import convertbits
from chia.util.bech32m import decode_puzzle_hash
from chia.util.bech32m import encode_puzzle_hash
from chia.consensus.condition_tools import conditions_dict_for_solution
from chia.consensus.condition_tools import conditions_for_solution
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia_rs.sized_ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_utils import SpendableCAT
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.cat_wallet.cat_utils import get_innerpuzzle_from_puzzle as actual_get_innerpuzzle_from_puzzle
from chia.wallet.cat_wallet.cat_utils import \
    unsigned_spend_bundle_for_spendable_cats
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, CAT_MOD_HASH
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import \
    DEFAULT_HIDDEN_PUZZLE_HASH
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import \
    calculate_synthetic_secret_key
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import \
    puzzle_for_pk
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import \
    puzzle_for_synthetic_public_key
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import \
    solution_for_delegated_puzzle
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER
from chia.wallet.puzzles.singleton_top_layer_v1_1 import \
    SINGLETON_LAUNCHER_HASH
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_MOD
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_MOD_HASH
from chia.wallet.puzzles.singleton_top_layer_v1_1 import generate_launcher_coin
from chia.wallet.puzzles.singleton_top_layer_v1_1 import \
    launch_conditions_and_coinsol
from chia.wallet.puzzles.singleton_top_layer_v1_1 import \
    lineage_proof_for_coinsol
from chia.wallet.puzzles.singleton_top_layer_v1_1 import puzzle_for_singleton
from chia.wallet.puzzles.singleton_top_layer_v1_1 import solution_for_singleton
from chia.wallet.puzzles.tails import GenesisById
from chia.wallet.trading.offer import OFFER_MOD
from chia.wallet.trading.offer import OFFER_MOD_HASH
from chia.wallet.trading.offer import Offer
from chia.wallet.util.puzzle_compression import compress_object_with_puzzles
from chia.wallet.util.puzzle_compression import decompress_object_with_puzzles
from chia.wallet.util.puzzle_compression import lowest_best_version
from chia_rs import run_chia_program
from clvm.casts import int_to_bytes

from clvm import SExp

from leaflet_client import LeafletFullNodeRpcClient
from cic_replacement import build_merkle_tree
from chia.full_node.bundle_tools import simple_solution_generator
from chia._tests.util.get_name_puzzle_conditions import get_name_puzzle_conditions
from private_key_things import sign_spend_bundle_with_specific_sk

from chia.wallet.vc_wallet.vc_drivers import REVOCATION_LAYER_HASH

MEMPOOL_MIN_FEE_INCREASE = uint64(10000000)
ROUTER_MIN_FEE = 42000000000
DEV_DEPLOYMENT_FEE = 420000000000


def program_from_hex(h: str) -> Program:
    return Program.from_bytes(bytes.fromhex(h))


def load_clvm_hex(
    filename
) -> Program:
    clvm_hex = open(filename, "r").read().strip()
    assert len(clvm_hex) != 0

    return program_from_hex(clvm_hex)


ROUTER_MOD: Program = load_clvm_hex("clvm/router.clvm.hex")
LIQUIDITY_TAIL_MOD: Program = load_clvm_hex("clvm/liquidity_tail.clvm.hex")

P2_SINGLETON_FLASHLOAN_MOD: Program = load_clvm_hex(
    "clvm/p2_singleton_flashloan.clvm.hex")
P2_MERKLE_TREE_MODIFIED_MOD: Program = load_clvm_hex(
    "clvm/p2_merkle_tree_modified.clvm.hex")

PAIR_INNER_PUZZLE_MOD: Program = load_clvm_hex(
    "clvm/pair_inner_puzzle.clvm.hex")
ADD_LIQUIDITY_MOD: Program = load_clvm_hex("clvm/add_liquidity.clvm.hex")
REMOVE_LIQUIDITY_MOD: Program = load_clvm_hex("clvm/remove_liquidity.clvm.hex")
SWAP_MOD: Program = load_clvm_hex("clvm/swap.clvm.hex")

ROUTER_MOD_HASH = ROUTER_MOD.get_tree_hash()
LIQUIDITY_TAIL_MOD_HASH: Program = LIQUIDITY_TAIL_MOD.get_tree_hash()
P2_SINGLETON_FLASHLOAN_MOD_HASH: Program = P2_SINGLETON_FLASHLOAN_MOD.get_tree_hash()
P2_MERKLE_TREE_MODIFIED_MOD_HASH: Program = P2_MERKLE_TREE_MODIFIED_MOD.get_tree_hash()
PAIR_INNER_PUZZLE_MOD_HASH: Program = PAIR_INNER_PUZZLE_MOD.get_tree_hash()

ADD_LIQUIDITY_PUZZLE = ADD_LIQUIDITY_MOD.curry(
    CAT_MOD_HASH,
    LIQUIDITY_TAIL_MOD_HASH
)
ADD_LIQUIDITY_PUZZLE_HASH = ADD_LIQUIDITY_PUZZLE.get_tree_hash()

REMOVE_LIQUIDITY_PUZZLE = REMOVE_LIQUIDITY_MOD.curry(
    CAT_MOD_HASH,
    LIQUIDITY_TAIL_MOD_HASH
)
REMOVE_LIQUIDITY_PUZZLE_HASH = REMOVE_LIQUIDITY_PUZZLE.get_tree_hash()

SWAP_PUZZLE = SWAP_MOD.curry(993)
SWAP_PUZZLE_HASH = SWAP_PUZZLE.get_tree_hash()

# DEFAULT_HIDDEN_PUZZLE is (=) instead of (x)
# so yes, I will use this opportunity to put my signature on the blockchain
# verify this is harmless with:
# brun -x 01 ff08ffff018879616b756869746f80
# (should output '(x (q . "yakuhito"))' - a program that always fails with the message 'yakuhito')
SECRET_PUZZLE = program_from_hex("ff08ffff018879616b756869746f80")
SECRET_PUZZLE_HASH = SECRET_PUZZLE.get_tree_hash()

MERKLE_ROOT, MERKLE_PROOFS = build_merkle_tree([
    ADD_LIQUIDITY_PUZZLE_HASH,
    REMOVE_LIQUIDITY_PUZZLE_HASH,
    SWAP_PUZZLE_HASH,
    SECRET_PUZZLE_HASH
])

# XCH-rCAT puzzles
RCAT_ROUTER_MOD: Program = load_clvm_hex("clvm/v2r_router.clvm.hex")
RCAT_PAIR_INNER_PUZZLE_MOD: Program = load_clvm_hex(
    "clvm/v2r_pair_inner_puzzle.clvm.hex")

RCAT_SWAP_PUZZLE = SWAP_MOD.curry(999)
RCAT_SWAP_PUZZLE_HASH = RCAT_SWAP_PUZZLE.get_tree_hash()

RCAT_MERKLE_ROOT, RCAT_MERKLE_PROOFS = build_merkle_tree([
    ADD_LIQUIDITY_PUZZLE_HASH,
    REMOVE_LIQUIDITY_PUZZLE_HASH,
    RCAT_SWAP_PUZZLE_HASH,
    SECRET_PUZZLE_HASH
])
# end XCH-rCAT puzzles


def get_router_puzzle(rcat):
    if rcat:
        return RCAT_ROUTER_MOD.curry(
            RCAT_PAIR_INNER_PUZZLE_MOD_HASH,
            SINGLETON_MOD_HASH,
            P2_MERKLE_TREE_MODIFIED_MOD_HASH,
            P2_SINGLETON_FLASHLOAN_MOD_HASH,
            CAT_MOD_HASH,
            REVOCATION_LAYER_HASH,
            OFFER_MOD_HASH,
            RCAT_MERKLE_ROOT,
            SINGLETON_LAUNCHER_HASH,
            RCAT_ROUTER_MOD_HASH
        )
    
    return ROUTER_MOD.curry(
        PAIR_INNER_PUZZLE_MOD_HASH,
        SINGLETON_MOD_HASH,
        P2_MERKLE_TREE_MODIFIED_MOD_HASH,
        P2_SINGLETON_FLASHLOAN_MOD_HASH,
        CAT_MOD_HASH,
        OFFER_MOD_HASH,
        MERKLE_ROOT,
        SINGLETON_LAUNCHER_HASH,
        ROUTER_MOD_HASH
    )


def get_pair_inner_inner_puzzle(
    singleton_launcher_id,
    tail_hash,
    hidden_puzzle_hash
):
    if hidden_puzzle_hash is not None:
        return RCAT_PAIR_INNER_PUZZLE_MOD.curry(
            P2_MERKLE_TREE_MODIFIED_MOD_HASH,
            (SINGLETON_MOD_HASH, (singleton_launcher_id, SINGLETON_LAUNCHER_HASH)),
            P2_SINGLETON_FLASHLOAN_MOD_HASH,
            CAT_MOD_HASH,
            REVOCATION_LAYER_HASH,
            hidden_puzzle_hash,
            OFFER_MOD_HASH,
            tail_hash
        )

    return PAIR_INNER_PUZZLE_MOD.curry(
        P2_MERKLE_TREE_MODIFIED_MOD_HASH,
        (SINGLETON_MOD_HASH, (singleton_launcher_id, SINGLETON_LAUNCHER_HASH)),
        P2_SINGLETON_FLASHLOAN_MOD_HASH,
        CAT_MOD_HASH,
        OFFER_MOD_HASH,
        tail_hash
    )


def get_pair_inner_puzzle(
    singleton_launcher_id,
    tail_hash,
    liquidity,
    xch_reserve,
    token_reserve,
    hidden_puzzle_hash
):
    if hidden_puzzle_hash is not None:
        return P2_MERKLE_TREE_MODIFIED_MOD.curry(
            get_pair_inner_inner_puzzle(singleton_launcher_id, tail_hash, hidden_puzzle_hash),
            RCAT_MERKLE_ROOT,
            (liquidity, (xch_reserve, token_reserve))
        )

    return P2_MERKLE_TREE_MODIFIED_MOD.curry(
        get_pair_inner_inner_puzzle(singleton_launcher_id, tail_hash),
        MERKLE_ROOT,
        (liquidity, (xch_reserve, token_reserve))
    )


def get_pair_puzzle(
    singleton_launcher_id,
    tail_hash,
    liquidity,
    xch_reserve,
    token_reserve,
    hidden_puzzle_hash
):
    return puzzle_for_singleton(
        singleton_launcher_id,
        get_pair_inner_puzzle(
            singleton_launcher_id,
            tail_hash,
            liquidity,
            xch_reserve,
            token_reserve,
            hidden_puzzle_hash
        )
    )


def pair_liquidity_tail_puzzle(pair_launcher_id):
    return LIQUIDITY_TAIL_MOD.curry(
        (SINGLETON_MOD_HASH, (pair_launcher_id, SINGLETON_LAUNCHER_HASH))
    )

# https://github.com/Chia-Network/chia-blockchain/blob/main/chia/wallet/puzzles/singleton_top_layer_v1_1.py


def pay_to_singleton_flashloan_puzzle(launcher_id: bytes32) -> Program:
    return P2_SINGLETON_FLASHLOAN_MOD.curry(SINGLETON_MOD_HASH, launcher_id, SINGLETON_LAUNCHER_HASH)

# https://github.com/Chia-Network/chia-blockchain/blob/main/chia/wallet/puzzles/singleton_top_layer_v1_1.py


def solution_for_p2_singleton_flashloan(
    p2_singleton_coin: Coin,
    singleton_inner_puzhash: bytes32,
    extra_conditions=[]
) -> Program:
    solution: Program = Program.to(
        [singleton_inner_puzhash, p2_singleton_coin.name(), extra_conditions])
    return solution


async def get_full_node_client(
    chia_root,
    leaflet_url
) -> FullNodeRpcClient:
    node_client = None

    if leaflet_url is not None:
        # use leaflet by default
        node_client = LeafletFullNodeRpcClient(leaflet_url)
    else:
        root_path = Path(chia_root)

        config = load_config(root_path, "config.yaml")
        self_hostname = config["self_hostname"]
        rpc_port = config["full_node"]["rpc_port"]
        node_client: FullNodeRpcClient = await FullNodeRpcClient.create(
            self_hostname, uint16(rpc_port), root_path, config
        )

    await node_client.healthz()

    return node_client


async def get_sim_full_node_client(
    chia_root: str
) -> SimulatorFullNodeRpcClient:
    root_path = Path(chia_root)

    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    rpc_port = config["full_node"]["rpc_port"]
    node_client: SimulatorFullNodeRpcClient = await SimulatorFullNodeRpcClient.create(
        self_hostname, uint16(rpc_port), root_path, config
    )
    await node_client.healthz()

    return node_client


async def get_wallet_client(
    chia_root: str
) -> WalletRpcClient:
    root_path = Path(chia_root)

    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    rpc_port = config["wallet"]["rpc_port"]
    wallet_client: WalletRpcClient = await WalletRpcClient.create(
        self_hostname, uint16(rpc_port), root_path, config
    )
    await wallet_client.healthz()

    return wallet_client


async def launch_router_from_coin(parent_coin, parent_coin_puzzle, rcat, fee=0):
    comment: List[Tuple[str, str]] = [("tibet", "v2")]
    if rcat:
        comment = [("tibet", "v2r")]
    conds, launcher_coin_spend = launch_conditions_and_coinsol(
        parent_coin, get_router_puzzle(rcat), comment, 1)
    if parent_coin.amount > fee + 1:
        conds.append(
            [
                ConditionOpcode.CREATE_COIN,
                parent_coin.puzzle_hash,
                parent_coin.amount - 1 - fee,
                [parent_coin.puzzle_hash]
            ]
        )
    if fee > 0:
        conds.append([
            ConditionOpcode.RESERVE_FEE,
            fee
        ])

    p2_coin_spend = make_spend(
        parent_coin,
        parent_coin_puzzle,
        solution_for_delegated_puzzle(Program.to((1, conds)), [])
    )

    sb = SpendBundle(
        [launcher_coin_spend, p2_coin_spend],
        AugSchemeMPL.aggregate([])
    )
    launcher_id = launcher_coin_spend.coin.name().hex()

    return launcher_id, sb


async def create_test_cat(hidden_puzzle_hash, token_amount, coin, coin_puzzle):
    coin_id = coin.name()

    tail = GenesisById.construct([coin_id])
    tail_hash = tail.get_tree_hash()
    cat_inner_puzzle = get_cat_inner_puzzle(hidden_puzzle_hash, coin_puzzle)

    cat_puzzle = get_cat_puzzle(tail_hash, hidden_puzzle_hash, coin_puzzle)
    cat_puzzle_hash = cat_puzzle.get_tree_hash()

    cat_creation_tx = make_spend(
        coin,
        coin_puzzle,
        solution_for_delegated_puzzle(Program.to((1, [
            [ConditionOpcode.CREATE_COIN, cat_puzzle_hash, token_amount * 1000, [coin.puzzle_hash]],
            [ConditionOpcode.CREATE_COIN, coin.puzzle_hash,
                coin.amount - token_amount * 1000,
                [coin.puzzle_hash]
            ],
        ])), [])
    )

    cat_coin = Coin(
        coin.name(),  # parent
        cat_puzzle_hash,
        token_amount * 1000
    )

    cat_inner_solution = get_cat_inner_solution(
        hidden_puzzle_hash is not None,
        coin_puzzle,
        solution_for_delegated_puzzle(
            Program.to((1, [
                [ConditionOpcode.CREATE_COIN, 0, -113, tail, []],
                [ConditionOpcode.CREATE_COIN, coin_puzzle.get_tree_hash(),
                cat_coin.amount, [coin_puzzle.get_tree_hash()]]
            ])), []
        )
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
    cat_eve_spend = cat_eve_spend_bundle.coin_spends[0]

    sb = SpendBundle(
        [cat_creation_tx, cat_eve_spend],
        AugSchemeMPL.aggregate([])
    )

    return tail_hash.hex(), sb


# https://github.com/Chia-Network/chia-dev-tools/blob/main/cdv/cmds/chia_inspect.py#L312
def get_spend_bundle_cost_and_fees(sb: SpendBundle):
    agg_sig = sb.aggregated_signature
    coin_spends = []
    for cs in sb.coin_spends:
        if cs.coin.parent_coin_info == b"\x00" * 32:  # offer *-*
            continue
        coin_spends.append(cs)

    program: BlockGenerator = simple_solution_generator(
        SpendBundle(coin_spends, agg_sig))
    npc_result: NPCResult = get_name_puzzle_conditions(
        program,
        INFINITE_COST,
        mempool_mode=True,
        constants=DEFAULT_CONSTANTS,
    )
    return int(npc_result.conds.cost), int(npc_result.conds.reserve_fee)

# my_solution = program_from_hex("80") # ()
# # run '(mod () (include condition_codes.clvm) (list (list CREATE_COIN 0x0000000000000000000000000000000000000000000000000000000000000001 1)))' -i include/ -d
# my_puzzle = program_from_hex("ff02ffff01ff04ffff04ff02ffff01ffa00000000000000000000000000000000000000000000000000000000000000001ff018080ff8080ffff04ffff0133ff018080")
# my_coin = Coin(b"\x00" * 32, my_puzzle.get_tree_hash(), 1)
# my_cs = make_spend(my_coin, my_puzzle, my_solution)
# sb = SpendBundle(
#     [my_cs],
#     AugSchemeMPL.aggregate([])
# )
# print(get_spend_bundle_cost(sb))


async def create_pair_from_coin(
    coin,
    coin_puzzle,
    tail_hash,
    hidden_puzzle_hash,
    router_launcher_id,
    current_router_coin,
    current_router_coin_creation_spend,
    fee=ROUTER_MIN_FEE,
):
    if fee < ROUTER_MIN_FEE:
        raise Exception(
            f"The router requires a minimum fee of {ROUTER_MIN_FEE} to be spent.")

    lineage_proof = lineage_proof_for_coinsol(
        current_router_coin_creation_spend)

    router_inner_puzzle = get_router_puzzle(hidden_puzzle_hash is not None)
    router_singleton_puzzle = puzzle_for_singleton(
        router_launcher_id, router_inner_puzzle)

    router_inner_solution = Program.to([
        current_router_coin.name(),
        tail_hash
    ])
    if hidden_puzzle_hash is not None:
        router_inner_solution = Program.to([
            current_router_coin.name(),
            tail_hash,
            hidden_puzzle_hash
        ])

    router_singleton_solution = solution_for_singleton(
        lineage_proof, current_router_coin.amount, router_inner_solution)
    router_singleton_spend = make_spend(
        current_router_coin, router_singleton_puzzle, router_singleton_solution)

    pair_launcher_coin = Coin(
        current_router_coin.name(), SINGLETON_LAUNCHER_HASH, 2)
    pair_puzzle = get_pair_puzzle(
        pair_launcher_coin.name(),
        tail_hash,
        0, 0, 0,
        hidden_puzzle_hash
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
        std_hash(pair_launcher_coin.name() +
                 pair_launcher_solution.get_tree_hash()),
    ]
    pair_launcher_spend = make_spend(
        pair_launcher_coin,
        SINGLETON_LAUNCHER,
        pair_launcher_solution,
    )

    # first condition is CREATE_COIN, which we took care of
    # important to note: router also takes care of assert_launcher_announcement, but we need it to link the fund spend to the bundle
    conds = []
    if coin.amount > fee + 1:
        conds.append([ConditionOpcode.CREATE_COIN,
                      coin.puzzle_hash, coin.amount - fee - 1])
    # RESERVE_FEE ROUTER_MIN_FEE is already created by the router
    # 1 comes from the pair launcher coin being spent (amount=2; only CREATE_COIN uses 1)
    # conds.append([ConditionOpcode.RESERVE_FEE, 1 + fee - ROUTER_MIN_FEE])
    conds.append(assert_launcher_announcement)
    fund_spend = make_spend(
        coin,
        coin_puzzle,
        solution_for_delegated_puzzle(Program.to((1, conds)), [])
    )

    pair_launcher_id = Coin(current_router_coin.name(),
                            SINGLETON_LAUNCHER_HASH, 2).name()
    sb = SpendBundle(
        [router_singleton_spend, pair_launcher_spend, fund_spend],
        AugSchemeMPL.aggregate([])
    )
    current_pair_coin = Coin(pair_launcher_id, pair_puzzle.get_tree_hash(), 1)
    return pair_launcher_id.hex(), sb, current_pair_coin, pair_launcher_spend


async def sync_router(full_node_client, last_router_id, rcat):
    new_pairs = []
    coin_record = await full_node_client.get_coin_record_by_name(last_router_id)
    if not coin_record.spent:
        # hack
        current_router_coin, creation_spend, _ = await sync_router(full_node_client, coin_record.coin.parent_coin_info, rcat)
        return current_router_coin, creation_spend, []

    router_puzzle_hash = get_router_puzzle(rcat).get_tree_hash()

    while coin_record.spent:
        tail_hash, hidden_puzzle_hash = None, None

        creation_spend = await full_node_client.get_puzzle_and_solution(last_router_id, coin_record.spent_block_index)
        conditions_dict = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )

        if coin_record.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
            solution_program = None
            try:
                solution_program = creation_spend.solution.to_program()
            except:
                solution_program = Program.from_bytes(creation_spend.solution.to_bytes())

            if rcat:
                tail_hash = [_ for _ in solution_program.as_iter()
                             ][-1].as_python()[-2]
                hidden_puzzle_hash = [_ for _ in solution_program.as_iter()
                             ][-1].as_python()[-1]
            else:
                tail_hash = [_ for _ in solution_program.as_iter()
                             ][-1].as_python()[-1]

        for cwa in conditions_dict[ConditionOpcode.CREATE_COIN]:
            new_puzzle_hash = cwa.vars[0]
            new_amount = cwa.vars[1]

            if new_amount == b"\x01":  # CREATE_COIN with amount=1 -> router recreated
                new_router_coin = Coin(last_router_id, new_puzzle_hash, 1)

                last_router_id = new_router_coin.name()
            elif new_amount == b"\x02":  # CREATE_COIN with amount=2 -> pair launcher deployed
                assert new_puzzle_hash == SINGLETON_LAUNCHER_HASH

                pair_launcher_coin = Coin(
                    creation_spend.coin.name(), new_puzzle_hash, 2)
                pair_launcher_id = pair_launcher_coin.name()

                if hidden_puzzle_hash:
                    new_pairs.append((tail_hash.hex(), hidden_puzzle_hash.hex(), pair_launcher_id.hex()))
                else:
                    new_pairs.append((tail_hash.hex(), pair_launcher_id.hex()))
            else:
                print(
                    "Someone did something extremely weird with the router - time to call the cops.")
                sys.exit(1)

        coin_record = await full_node_client.get_coin_record_by_name(last_router_id)

    return coin_record.coin, creation_spend, new_pairs


async def get_spend_bundle_in_mempool(full_node_client, coin):
    items = await full_node_client.fetch("get_mempool_items_by_coin_name", {"coin_name": coin_id.hex()})

    for sb_json in items["mempool_items"]:
        sb = SpendBundle.from_json_dict(sb_json["spend_bundle"])
        for cs in sb.coin_spends:
            if cs.coin.name() == coin_id:
                return sb

    return None


def get_coin_spend_from_sb(sb, coin_name):
    if sb is None:
        return None

    for cs in sb.coin_spends:
        if cs.coin.name() == coin_name:
            return cs

    return None


async def sync_pair(full_node_client, last_synced_coin_id):
    state = {
        "liquidity": 0,
        "xch_reserve": 0,
        "token_reserve": 0
    }
    coin_record = await full_node_client.get_coin_record_by_name(last_synced_coin_id)
    last_synced_coin = coin_record.coin
    creation_spend = None

    if coin_record.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
        creation_spend = await full_node_client.get_puzzle_and_solution(last_synced_coin_id, coin_record.spent_block_index)
        conditions_dict = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )
        last_synced_coin = Coin(coin_record.coin.name(
        ), conditions_dict[ConditionOpcode.CREATE_COIN][0].vars[0], 1)

    if not coin_record.spent:
        # hack
        current_pair_coin, creation_spend, state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(full_node_client, coin_record.coin.parent_coin_info)
        return current_pair_coin, creation_spend, state, sb_to_aggregate, last_synced_pair_id_on_blockchain

    creation_spend = None
    while coin_record.spent:
        creation_spend = await full_node_client.get_puzzle_and_solution(last_synced_coin_id, coin_record.spent_block_index)
        conditions_dict = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )

        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            new_puzzle_hash = cwa.vars[0]
            new_amount = cwa.vars[1]

            if new_amount == b"\x01":  # CREATE_COIN with amount=1 -> pair recreation
                last_synced_coin = Coin(
                    last_synced_coin_id, new_puzzle_hash, 1)
                last_synced_coin_id = last_synced_coin.name()

        coin_record = await full_node_client.get_coin_record_by_name(last_synced_coin_id)

    last_synced_pair_id_on_blockchain = last_synced_coin_id
    # mempool - watch this aggregation!
    last_coin_on_chain = coin_record.coin
    last_coin_on_chain_id = last_coin_on_chain.name()
    sb = await get_spend_bundle_in_mempool(full_node_client, last_coin_on_chain)
    sb_to_aggregate = sb

    coin_spend = get_coin_spend_from_sb(sb, last_coin_on_chain_id)
    while coin_spend != None:
        creation_spend = coin_spend
        conditions_dict = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )

        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            new_puzzle_hash = cwa.vars[0]
            new_amount = cwa.vars[1]

            if new_amount == b"\x01":  # CREATE_COIN with amount=1 -> pair recreation
                last_synced_coin = Coin(
                    last_synced_coin_id, new_puzzle_hash, 1)
                last_synced_coin_id = last_synced_coin.name()

        coin_spend = get_coin_spend_from_sb(sb, last_synced_coin_id)

    if creation_spend.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
        return last_synced_coin, creation_spend, state, None, last_synced_coin.name()

    old_state = None
    try:
        old_state = creation_spend.puzzle_reveal.uncurry()[1].at("rf").uncurry()[
            1].at("rrf")
    except:
        old_state = Program.from_bytes(creation_spend.puzzle_reveal.to_bytes()).uncurry()[1].at("rf").uncurry()[
            1].at("rrf")
        
    p2_merkle_solution = None
    try:
        p2_merkle_solution = creation_spend.solution.to_program().at("rrf")
    except:
        p2_merkle_solution = Program.from_bytes(creation_spend.solution.to_bytes()).at("rrf")

    # p2_merkle_tree_modified -> parameters (which is a puzzle)
    new_state_puzzle = p2_merkle_solution.at("f")
    params = p2_merkle_solution.at("rrf").at("r")

    # SINGLETON_STRUCT and my_coin_id are only used to create extra conditions
    # in inner inner puzzle
    dummy_singleton_struct = (b"\x00" * 32, (b"\x00" * 32, b"\x00" * 32))
    dummy_coin_id = b"\x00" * 32

    new_state_puzzle_sol = Program.to([
        old_state,
        params,
        dummy_singleton_struct,
        dummy_coin_id
    ])

    new_state_puzzle_output = new_state_puzzle.run(new_state_puzzle_sol)
    new_state = new_state_puzzle_output.at("f")

    state = {
        "liquidity": new_state.at("f").as_int(),
        "xch_reserve": new_state.at("rf").as_int(),
        "token_reserve": new_state.at("rr").as_int()
    }

    return last_synced_coin, creation_spend, state, sb_to_aggregate, last_synced_pair_id_on_blockchain

def get_cat_inner_puzzle(
    hidden_puzzle_hash,
    custody_puzzle,
):
    if hidden_puzzle_hash is not None:
        return create_revocation_layer(hidden_puzzle_hash, custody_puzzle.get_tree_hash())

    return custody_puzzle

def get_cat_puzzle(
    tail_hash,
    hidden_puzzle_hash,
    custody_puzzle,
):
    return construct_cat_puzzle(
        CAT_MOD,
        tail_hash,
        get_cat_inner_puzzle(
            hidden_puzzle_hash,
            custody_puzzle
        )
    )

def get_cat_inner_solution(
    is_rcat,
    custody_puzzle,
    custody_solution,
):
    if is_rcat:
        return Program.to(
            [
                False,
                custody_puzzle,
                custody_solution,
            ]
        )
    
    return custody_solution

async def get_pair_reserve_info(
    full_node_client,
    pair_launcher_id,
    pair_coin,
    token_tail_hash,
    token_hidden_puzzle_hash,
    creation_spend,
    cached_sb,
):
    puzzle_announcements_asserts = []
    conditions_dict = conditions_dict_for_solution(
        creation_spend.puzzle_reveal,
        creation_spend.solution,
        INFINITE_COST
    )
    for cwa in conditions_dict.get(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, []):
        puzzle_announcements_asserts.append(cwa.vars[0])

    if len(puzzle_announcements_asserts) == 0:
        return None, None, None  # new pair

    p2_singleton_puzzle = pay_to_singleton_flashloan_puzzle(pair_launcher_id)
    p2_singleton_puzzle_hash = p2_singleton_puzzle.get_tree_hash()
    p2_singleton_cat_puzzle = get_cat_puzzle(
        token_tail_hash,
        token_hidden_puzzle_hash,
        p2_singleton_puzzle
    )
    p2_singleton_cat_puzzle_hash = p2_singleton_cat_puzzle.get_tree_hash()

    spends = []

    if cached_sb is None:
        coin_record = await full_node_client.get_coin_record_by_name(pair_coin.name())
        block_record = await full_node_client.get_block_record_by_height(coin_record.confirmed_block_index)
        spends = await full_node_client.get_block_spends(block_record.header_hash)
    else:
        spends = cached_sb.coin_spends

    xch_reserve_coin = None
    token_reserve_coin = None
    token_reserve_lineage_proof = []
    for spend in spends:
        conditions_dict = conditions_dict_for_solution(
            spend.puzzle_reveal,
            spend.solution,
            INFINITE_COST
        )

        for cwa in conditions_dict.get(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, []):
            ann_hash = std_hash(spend.coin.puzzle_hash + cwa.vars[0])
            if ann_hash in puzzle_announcements_asserts:
                amount = 0
                for cwa2 in conditions_dict[ConditionOpcode.CREATE_COIN]:
                    if cwa2.vars[0] in [p2_singleton_puzzle_hash, p2_singleton_cat_puzzle_hash]:
                        amount = SExp.to(cwa2.vars[1]).as_int()
                if spend.coin.puzzle_hash == OFFER_MOD_HASH:
                    xch_reserve_coin = Coin(
                        spend.coin.name(), p2_singleton_puzzle_hash, amount)
                else:  # OFFER_MOD_HASH but wrapped in CAT puzzle
                    token_reserve_coin = Coin(
                        spend.coin.name(), p2_singleton_cat_puzzle_hash, amount)
                    token_reserve_lineage_proof = [
                        spend.coin.parent_coin_info,
                        get_cat_inner_puzzle(token_hidden_puzzle_hash, OFFER_MOD).get_tree_hash(),
                        spend.coin.amount
                    ]
                break

    return xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof


# Yak fix
def get_innerpuzzle_from_puzzle(puzzle):
    try:
        return actual_get_innerpuzzle_from_puzzle(puzzle)
    except:
        return actual_get_innerpuzzle_from_puzzle(Program.from_bytes(puzzle.to_bytes()))


async def respond_to_deposit_liquidity_offer(
    pair_launcher_id,
    current_pair_coin,
    creation_spend,
    token_tail_hash,
    token_hidden_puzzle_hash,
    pair_liquidity,
    pair_xch_reserve,
    pair_token_reserve,
    offer_str,
    last_xch_reserve_coin,
    last_token_reserve_coin,
    # coin_parent_coin_info, inner_puzzle_hash, amount
    last_token_reserve_lineage_proof,
):
    # 1. Detect ephemeral coins (those created by the offer that we're allowed to use)
    offer = Offer.from_bech32(offer_str)
    offer_spend_bundle = offer.to_spend_bundle()
    offer_coin_spends = offer_spend_bundle.coin_spends

    eph_xch_coin = None
    eph_token_coin = None

    # needed when spending eph_token_coin since it's a CAT
    eph_token_coin_creation_spend = None
    announcement_asserts = []  # assert everything when the liquidity cat is minted

    ephemeral_token_coin_puzzle = get_cat_puzzle(
        token_tail_hash,
        token_hidden_puzzle_hash,
        OFFER_MOD
    )
    ephemeral_token_coin_puzzle_hash = ephemeral_token_coin_puzzle.get_tree_hash()

    # all valid coin spends (i.e., not 'hints' for offered assets or coins)
    cs_from_initial_offer = []

    for coin_spend in offer_coin_spends:
        # 'hint' for offer requested coin (liquidity CAT)
        if coin_spend.coin.parent_coin_info == b"\x00" * 32:
            continue

        cs_from_initial_offer.append(coin_spend)
        conditions_dict = conditions_dict_for_solution(
            coin_spend.puzzle_reveal,
            coin_spend.solution,
            INFINITE_COST
        )

        # is this spend creating an ephemeral coin?
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            puzzle_hash = cwa.vars[0]
            amount = SExp.to(cwa.vars[1]).as_int()

            if puzzle_hash == OFFER_MOD_HASH:
                eph_xch_coin = Coin(coin_spend.coin.name(),
                                    puzzle_hash, amount)

            if puzzle_hash == ephemeral_token_coin_puzzle_hash:
                eph_token_coin = Coin(
                    coin_spend.coin.name(), puzzle_hash, amount)
                eph_token_coin_creation_spend = coin_spend

        # is there any announcement that we'll need to assert?
        # cwa = condition with args
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []):
            announcement_asserts.append([
                ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                std_hash(coin_spend.coin.name() + cwa.vars[0])
            ])

    # 2. Math stuff
    deposited_token_amount = eph_token_coin.amount

    new_liquidity_token_amount = 0
    for k, v in offer.get_requested_amounts().items():
        new_liquidity_token_amount = v

    target_liquidity_tokens = deposited_token_amount
    if pair_liquidity > 0:
        target_liquidity_tokens = deposited_token_amount * \
            pair_liquidity // pair_token_reserve

    deposited_xch_amount = eph_xch_coin.amount - new_liquidity_token_amount
    if pair_token_reserve != 0:
        deposited_xch_amount = pair_xch_reserve * \
            deposited_token_amount // pair_token_reserve

    if target_liquidity_tokens > new_liquidity_token_amount:
        raise Exception(
            f"Your offer is asking for too much liquidity ({new_liquidity_token_amount}; should be {target_liquidity_tokens}) - you need to offer at least {deposited_xch_amount} mojos and {deposited_token_amount} token mojos (/1000 to find out the number of tokens).")

    if eph_xch_coin.amount - new_liquidity_token_amount != deposited_xch_amount:
        raise Exception(
            f"For {new_liquidity_token_amount} liquidity, you should be asking for {deposited_xch_amount + new_liquidity_token_amount} mojos, not ({eph_xch_coin.amount})")

    # 3. spend the token ephemeral coin to create the token reserve coin
    p2_singleton_puzzle = pay_to_singleton_flashloan_puzzle(pair_launcher_id)
    p2_singleton_puzzle_cat = get_cat_puzzle(
        token_tail_hash,
        token_hidden_puzzle_hash,
        p2_singleton_puzzle
    )

    eph_token_coin_notarized_payments = []
    eph_token_coin_notarized_payments.append(
        Program.to([
            current_pair_coin.name(),
            [p2_singleton_puzzle.get_tree_hash(), deposited_token_amount +
             pair_token_reserve]
        ])
    )

    # send extra tokens to return address
    if eph_token_coin.amount > deposited_token_amount:
        raise Exception(
            f"You provided {eph_token_coin.amount - deposited_token_amount} too many token mojos.")
        
    eph_token_coin_inner_solution = get_cat_inner_solution(
        token_hidden_puzzle_hash is not None,
        OFFER_MOD,
        Program.to(eph_token_coin_notarized_payments)
    )

    spendable_cats_for_token_reserve = []
    spendable_cats_for_token_reserve.append(
        SpendableCAT(
            eph_token_coin,
            token_tail_hash,
            get_cat_inner_puzzle(token_hidden_puzzle_hash, OFFER_MOD),
            eph_token_coin_inner_solution,
            lineage_proof=LineageProof(
                eph_token_coin_creation_spend.coin.parent_coin_info,
                get_innerpuzzle_from_puzzle(eph_token_coin_creation_spend.puzzle_reveal).get_tree_hash(),
                eph_token_coin_creation_spend.coin.amount
            )
        )
    )

    pair_singleton_inner_puzzle = get_pair_inner_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )
    if last_token_reserve_coin is not None:
        spendable_cats_for_token_reserve.append(
            SpendableCAT(
                last_token_reserve_coin,
                token_tail_hash,
                get_cat_inner_puzzle(token_hidden_puzzle_hash, p2_singleton_puzzle),
                get_cat_inner_solution(
                    token_hidden_puzzle_hash is not None,
                    p2_singleton_puzzle,
                    solution_for_p2_singleton_flashloan(
                        last_token_reserve_coin, pair_singleton_inner_puzzle.get_tree_hash()
                    )
                ),
                lineage_proof=LineageProof(
                    last_token_reserve_lineage_proof[0],
                    last_token_reserve_lineage_proof[1],
                    last_token_reserve_lineage_proof[2]
                )
            )
        )

    token_reserve_creation_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD, spendable_cats_for_token_reserve
    )
    token_reserve_creation_spends = token_reserve_creation_spend_bundle.coin_spends

    # 4. spend the xch ephemeral coin
    liquidity_cat_tail = pair_liquidity_tail_puzzle(pair_launcher_id)
    liquidity_cat_tail_hash = liquidity_cat_tail.get_tree_hash()

    liquidity_cat_mint_coin_tail_solution = Program.to(
        [pair_singleton_inner_puzzle.get_tree_hash(), current_pair_coin.parent_coin_info])
    # output everything from solution
    # this is usually not safe to use, but in this case we don't really care since we are accepting an offer
    # that is asking for liquidity tokens - it's kind of circular; if we don't get out tokens,
    # the transaction doesn't go through because a puzzle announcemet from the parents of eph coins would fail
    liquidity_cat_mint_coin_inner_puzzle = Program.from_bytes(b"\x01")
    liquidity_cat_mint_coin_inner_puzzle_hash = liquidity_cat_mint_coin_inner_puzzle.get_tree_hash()
    liquidity_cat_mint_coin_puzzle = construct_cat_puzzle(
        CAT_MOD, liquidity_cat_tail_hash, liquidity_cat_mint_coin_inner_puzzle
    )
    liquidity_cat_mint_coin_puzzle_hash = liquidity_cat_mint_coin_puzzle.get_tree_hash()

    eph_xch_coin_settlement_things = [
        Program.to([
            current_pair_coin.name(),
            [p2_singleton_puzzle.get_tree_hash(), pair_xch_reserve +
             deposited_xch_amount]
        ]),
        Program.to([
            current_pair_coin.name(),
            [liquidity_cat_mint_coin_puzzle_hash, new_liquidity_token_amount]
        ])
    ]
    # send extra XCH to return address
    if eph_xch_coin.amount > deposited_xch_amount + new_liquidity_token_amount:
        raise Exception(
            f"You provided {eph_xch_coin.amount - deposited_xch_amount - new_liquidity_token_amount} too many mojos.")
        
    eph_xch_coin_solution = Program.to(eph_xch_coin_settlement_things)
    eph_xch_coin_spend = make_spend(
        eph_xch_coin, OFFER_MOD, eph_xch_coin_solution)

    # 5. Re-create the pair singleton (spend it)
    pair_singleton_puzzle = get_pair_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )
    inner_inner_sol = Program.to((
        (
            current_pair_coin.name(),
            (
                b"\x00" * 32 if last_xch_reserve_coin is None else last_xch_reserve_coin.name(),
                b"\x00" * 32 if last_token_reserve_coin is None else last_token_reserve_coin.name()
            )
        ),
        [
            deposited_token_amount,
            liquidity_cat_mint_coin_inner_puzzle_hash,
            eph_xch_coin.name(),  # parent of liquidity cat mint coin
            deposited_xch_amount
        ]
    ))
    pair_singleton_inner_solution = Program.to([
        ADD_LIQUIDITY_PUZZLE,
        Program.to(
            MERKLE_PROOFS[ADD_LIQUIDITY_PUZZLE_HASH] if token_hidden_puzzle_hash is None else RCAT_MERKLE_PROOFS[ADD_LIQUIDITY_PUZZLE_HASH]
        ),
        inner_inner_sol
    ])

    lineage_proof = lineage_proof_for_coinsol(creation_spend)
    pair_singleton_solution = solution_for_singleton(
        lineage_proof, current_pair_coin.amount, pair_singleton_inner_solution
    )
    pair_singleton_spend = make_spend(
        current_pair_coin, pair_singleton_puzzle, pair_singleton_solution)

    # 6. Spend liquidity cat mint coin
    liquidity_cat_mint_coin = Coin(
        eph_xch_coin.name(),
        liquidity_cat_mint_coin_puzzle_hash,
        new_liquidity_token_amount
    )

    output_conditions = announcement_asserts
    output_conditions.append(
        [ConditionOpcode.CREATE_COIN, OFFER_MOD_HASH, new_liquidity_token_amount])

    liquidity_cat_mint_coin_tail_puzzle = pair_liquidity_tail_puzzle(
        pair_launcher_id)
    output_conditions.append([
        ConditionOpcode.CREATE_COIN,
        0,
        -113,
        liquidity_cat_mint_coin_tail_puzzle,
        liquidity_cat_mint_coin_tail_solution
    ])

    # also assert the XCH ephemeral coin announcement
    # specifically, for the payment made to mint liquidity tokens
    eph_xch_settlement_announcement = eph_xch_coin_settlement_things[1].get_tree_hash()
    output_conditions.append([
        ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
        std_hash(eph_xch_coin.puzzle_hash + eph_xch_settlement_announcement)
    ])

    liquidity_cat_mint_coin_solution = Program.to([
        output_conditions,
        [],
        liquidity_cat_mint_coin.name(),
        [liquidity_cat_mint_coin.parent_coin_info,
            liquidity_cat_mint_coin.puzzle_hash, new_liquidity_token_amount],
        [liquidity_cat_mint_coin.parent_coin_info,
            liquidity_cat_mint_coin_inner_puzzle_hash, new_liquidity_token_amount],
        [],
        []
    ])
    liquidity_cat_mint_coin_spend = make_spend(
        liquidity_cat_mint_coin,
        liquidity_cat_mint_coin_puzzle,
        liquidity_cat_mint_coin_solution
    )

    # 7. Ephemeral liquidity cat
    ephemeral_liquidity_cat_coin_puzzle = construct_cat_puzzle(
        CAT_MOD, liquidity_cat_tail_hash, OFFER_MOD)
    ephemeral_liquidity_cat_coin_puzzle_hash = ephemeral_liquidity_cat_coin_puzzle.get_tree_hash()

    ephemeral_liquidity_cat = Coin(
        liquidity_cat_mint_coin.name(),
        ephemeral_liquidity_cat_coin_puzzle_hash,
        new_liquidity_token_amount
    )

    notarized_payment = offer.get_requested_payments()[
        liquidity_cat_tail_hash][0]
    nonce = notarized_payment.nonce
    memos = notarized_payment.memos
    ephemeral_liquidity_cat_inner_solution = Program.to([
        Program.to([
            nonce,
            [memos[0], new_liquidity_token_amount, memos]
        ])
    ])
    ephemeral_liquidity_cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        [
            SpendableCAT(
                ephemeral_liquidity_cat,
                liquidity_cat_tail_hash,
                OFFER_MOD,
                ephemeral_liquidity_cat_inner_solution,
                lineage_proof=LineageProof(
                    liquidity_cat_mint_coin.parent_coin_info,
                    liquidity_cat_mint_coin_inner_puzzle_hash,
                    new_liquidity_token_amount
                )
            )
        ],
    )
    ephemeral_liquidity_cat_spend = ephemeral_liquidity_cat_spend_bundle.coin_spends[0]

    # 8. Right now, the tx is valid, but the fee is negative - spend the last (previous) xch reserve coin and we're done!
    last_xch_reserve_spend_maybe = []

    if last_xch_reserve_coin != None:
        last_xch_reserve_coin_puzzle = p2_singleton_puzzle
        last_xch_reserve_coin_solution = solution_for_p2_singleton_flashloan(
            last_xch_reserve_coin, pair_singleton_inner_puzzle.get_tree_hash()
        )
        last_xch_reserve_spend_maybe.append(
            make_spend(last_xch_reserve_coin, last_xch_reserve_coin_puzzle,
                      last_xch_reserve_coin_solution)
        )

    sb = SpendBundle(
        [
            eph_xch_coin_spend,
            pair_singleton_spend,
            liquidity_cat_mint_coin_spend,
            ephemeral_liquidity_cat_spend
        ] + token_reserve_creation_spends + cs_from_initial_offer + last_xch_reserve_spend_maybe,
        offer_spend_bundle.aggregated_signature
    )

    return sb


async def respond_to_remove_liquidity_offer(
    pair_launcher_id,
    current_pair_coin,
    creation_spend,
    token_tail_hash,
    token_hidden_puzzle_hash,
    pair_liquidity,
    pair_xch_reserve,
    pair_token_reserve,
    offer_str,
    last_xch_reserve_coin,
    last_token_reserve_coin,
    # coin_parent_coin_info, inner_puzzle_hash, amount
    last_token_reserve_lineage_proof,
):
    # 1. detect offered ephemeral coin (ephemeral liquidity coin, created the offer so we can use it)
    offer = Offer.from_bech32(offer_str)
    offer_spend_bundle = offer.to_spend_bundle()
    offer_coin_spends = offer_spend_bundle.coin_spends

    eph_liquidity_coin = None

    # needed when spending eph_liquidity_coin since it's a CAT
    eph_liquidity_coin_creation_spend = None
    announcement_asserts = []  # assert everything when the old  XCH reserve is spent

    liquidity_cat_tail = pair_liquidity_tail_puzzle(pair_launcher_id)
    liquidity_cat_tail_hash = liquidity_cat_tail.get_tree_hash()
    eph_liquidity_coin_puzzle = construct_cat_puzzle(
        CAT_MOD, liquidity_cat_tail_hash, OFFER_MOD)
    eph_liquidity_coin_puzzle_hash = eph_liquidity_coin_puzzle.get_tree_hash()

    # all valid coin spends (i.e., not 'hints' for offered assets or coins)
    cs_from_initial_offer = []

    for coin_spend in offer_coin_spends:
        if coin_spend.coin.parent_coin_info == b"\x00" * 32:  # 'hint' for offer requested coin
            continue

        cs_from_initial_offer.append(coin_spend)
        conditions_dict = conditions_dict_for_solution(
            coin_spend.puzzle_reveal,
            coin_spend.solution,
            INFINITE_COST
        )

        # is this spend creating an ephemeral coin?
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            puzzle_hash = cwa.vars[0]
            amount = SExp.to(cwa.vars[1]).as_int()

            if puzzle_hash == eph_liquidity_coin_puzzle_hash:
                eph_liquidity_coin = Coin(
                    coin_spend.coin.name(), puzzle_hash, amount)
                eph_liquidity_coin_creation_spend = coin_spend

        # is there any announcement that we'll need to assert?
        # cwa = condition with args
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []):
            announcement_asserts.append([
                ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                std_hash(coin_spend.coin.name() + cwa.vars[0])
            ])

    # 2. math stuff
    burned_liquidity_amount = eph_liquidity_coin.amount

    removed_token_amount = pair_token_reserve * \
        burned_liquidity_amount // pair_liquidity
    removed_xch_amount = pair_xch_reserve * \
        burned_liquidity_amount // pair_liquidity

    new_token_reserve_amount = last_token_reserve_coin.amount - removed_token_amount
    new_xch_reserve_amount = last_xch_reserve_coin.amount - removed_xch_amount

    # 3. spend ephemeral liquidity coin
    pair_singleton_puzzle = get_pair_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )
    pair_singleton_puzzle_hash = pair_singleton_puzzle.get_tree_hash()
    pair_singleton_inner_puzzle = get_pair_inner_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )
    pair_singleton_inner_puzzle_hash = pair_singleton_inner_puzzle.get_tree_hash()

    liquidity_cat_tail_puzzle = pair_liquidity_tail_puzzle(pair_launcher_id)
    liquidity_cat_tail_hash = liquidity_cat_tail_puzzle.get_tree_hash()
    liquidity_cat_burn_coin_tail_solution = Program.to(
        [pair_singleton_inner_puzzle_hash, current_pair_coin.parent_coin_info])
    liquidity_burn_coin_inner_puzzle = Program.to((
        1,
        [[ConditionOpcode.CREATE_COIN, 0, -113, liquidity_cat_tail_puzzle,
            liquidity_cat_burn_coin_tail_solution]]
    ))
    liquidity_burn_coin_inner_puzzle_hash = liquidity_burn_coin_inner_puzzle.get_tree_hash()

    create_burn_coin_notarized_payment = Program.to([
        current_pair_coin.name(),
        [liquidity_burn_coin_inner_puzzle_hash, burned_liquidity_amount]
    ])
    offer_liquidity_cat_puzzle = construct_cat_puzzle(
        CAT_MOD, liquidity_cat_tail_hash, OFFER_MOD)
    announcement_asserts.append([
        ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
        std_hash(offer_liquidity_cat_puzzle.get_tree_hash() +
                 create_burn_coin_notarized_payment.get_tree_hash())
    ])

    eph_liquidity_coin_inner_solution = Program.to([
        create_burn_coin_notarized_payment
    ])
    eph_liquidity_coin_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        [
            SpendableCAT(
                eph_liquidity_coin,
                liquidity_cat_tail_hash,
                OFFER_MOD,
                eph_liquidity_coin_inner_solution,
                lineage_proof=LineageProof(
                    eph_liquidity_coin_creation_spend.coin.parent_coin_info,
                    get_innerpuzzle_from_puzzle(
                        eph_liquidity_coin_creation_spend.puzzle_reveal).get_tree_hash(),
                    eph_liquidity_coin_creation_spend.coin.amount
                )
            )
        ]
    )
    eph_liquidity_coin_spend = eph_liquidity_coin_spend_bundle.coin_spends[0]

    # 4. spend liquidity burn coin
    liquidity_burn_coin_puzzle = construct_cat_puzzle(
        CAT_MOD, liquidity_cat_tail_hash, liquidity_burn_coin_inner_puzzle)
    liquidity_burn_coin = Coin(
        eph_liquidity_coin.name(),
        liquidity_burn_coin_puzzle.get_tree_hash(),
        burned_liquidity_amount
    )

    liquidity_burn_coin_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        [
            SpendableCAT(
                liquidity_burn_coin,
                liquidity_cat_tail_hash,
                liquidity_burn_coin_inner_puzzle,
                Program.to([]),
                lineage_proof=LineageProof(
                    eph_liquidity_coin_spend.coin.parent_coin_info,
                    OFFER_MOD_HASH,
                    eph_liquidity_coin_spend.coin.amount
                ),
                limitations_program_reveal=liquidity_cat_tail_puzzle,
                limitations_solution=liquidity_cat_burn_coin_tail_solution,
                extra_delta=-burned_liquidity_amount,
            )
        ]
    )

    liquidity_burn_coin_spend = liquidity_burn_coin_spend_bundle.coin_spends[0]

    # 5. re-create the pair singleton (spend it)
    pair_singleton_puzzle = get_pair_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )
    inner_inner_sol = Program.to((
        (
            current_pair_coin.name(),
            (
                last_xch_reserve_coin.name(),
                last_token_reserve_coin.name()
            )
        ),
        [
            burned_liquidity_amount,
            liquidity_burn_coin_inner_puzzle_hash,
            liquidity_burn_coin.parent_coin_info
        ]
    ))
    pair_singleton_inner_solution = Program.to([
        REMOVE_LIQUIDITY_PUZZLE,
        Program.to(
            MERKLE_PROOFS[REMOVE_LIQUIDITY_PUZZLE_HASH] if token_hidden_puzzle_hash is None else RCAT_MERKLE_PROOFS[REMOVE_LIQUIDITY_PUZZLE_HASH]
        ),
        inner_inner_sol
    ])

    lineage_proof = lineage_proof_for_coinsol(creation_spend)
    pair_singleton_solution = solution_for_singleton(
        lineage_proof, current_pair_coin.amount, pair_singleton_inner_solution
    )
    pair_singleton_spend = make_spend(
        current_pair_coin, pair_singleton_puzzle, pair_singleton_solution)

    # 6. spend token reserve
    p2_singleton_puzzle = pay_to_singleton_flashloan_puzzle(pair_launcher_id)
    p2_singleton_puzzle_hash = p2_singleton_puzzle.get_tree_hash()

    last_token_reserve_coin_extra_conditions = [
        [
            ConditionOpcode.CREATE_COIN,
            OFFER_MOD_HASH,
            last_token_reserve_coin.amount
        ]
    ]

    last_token_reserve_coin_inner_solution = get_cat_inner_solution(
        token_hidden_puzzle_hash is not None,
        p2_singleton_puzzle,
        solution_for_p2_singleton_flashloan(
            last_token_reserve_coin,
            pair_singleton_inner_puzzle.get_tree_hash(),
            extra_conditions=last_token_reserve_coin_extra_conditions
        )
    )
    last_token_reserve_coin_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        [
            SpendableCAT(
                last_token_reserve_coin,
                token_tail_hash,
                get_cat_inner_puzzle(
                    token_hidden_puzzle_hash,
                    p2_singleton_puzzle
                ),
                last_token_reserve_coin_inner_solution,
                lineage_proof=LineageProof(
                    last_token_reserve_lineage_proof[0],
                    last_token_reserve_lineage_proof[1],
                    last_token_reserve_lineage_proof[2]
                )
            )
        ]
    )
    last_token_reserve_coin_spend = last_token_reserve_coin_spend_bundle.coin_spends[0]

    # 7. spend ephemeral token coin to create new token reserve, resp. to offer
    eph_token_coin = Coin(
        last_token_reserve_coin.name(),
        get_cat_puzzle(
            token_tail_hash,
            token_hidden_puzzle_hash,
            OFFER_MOD
        ).get_tree_hash(),
        last_token_reserve_coin.amount
    )
    notarized_payments = offer.get_requested_payments()
    token_notarized_payment = notarized_payments[token_tail_hash][0]

    eph_token_coin_notarized_payments = []
    eph_token_coin_notarized_payments.append([
        token_notarized_payment.nonce,
        [token_notarized_payment.memos[0],
            removed_token_amount, token_notarized_payment.memos]
    ])
    if new_token_reserve_amount > 0:
        eph_token_coin_notarized_payments.append([
            current_pair_coin.name(),
            [p2_singleton_puzzle_hash, new_token_reserve_amount]
        ])
    if last_token_reserve_coin.amount > removed_token_amount + new_token_reserve_amount:
        raise Exception(
            f"You asked for too few tokens - your offer is {token_reserve_coin.amount - removed_token_amount - new_token_reserve_amount} token mojos short.")
        
    eph_token_coin_inner_solution = get_cat_inner_solution(
        token_hidden_puzzle_hash is not None,
        OFFER_MOD,
        Program.to(
            eph_token_coin_notarized_payments
        )
    )
    eph_token_coin_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        [
            SpendableCAT(
                eph_token_coin,
                token_tail_hash,
                get_cat_inner_puzzle(
                    token_hidden_puzzle_hash,
                    OFFER_MOD
                ),
                eph_token_coin_inner_solution,
                lineage_proof=LineageProof(
                    last_token_reserve_coin.parent_coin_info,
                    get_cat_inner_puzzle(
                        token_hidden_puzzle_hash,
                        OFFER_MOD
                    ).get_tree_hash(),
                    last_token_reserve_coin.amount
                )
            )
        ]
    )
    eph_token_coin_spend = eph_token_coin_spend_bundle.coin_spends[0]

    # 8. Spend XCH reserve
    xch_eph_coin_extra_payment = None
    if last_xch_reserve_coin.amount > removed_xch_amount + new_xch_reserve_amount:
        raise Exception(
            f"Your offer asks for too few XCH - you're {xch_reserve_coin.amount - removed_xch_amount - new_xch_reserve_amount} mojos short.")
        
    last_xch_reserve_coin_extra_conditions = [
        [
            ConditionOpcode.CREATE_COIN,
            OFFER_MOD_HASH,
            last_xch_reserve_coin.amount
        ]
    ] + announcement_asserts

    last_xch_reserve_coin_solution = solution_for_p2_singleton_flashloan(
        last_xch_reserve_coin,
        pair_singleton_inner_puzzle.get_tree_hash(),
        extra_conditions=last_xch_reserve_coin_extra_conditions
    )
    last_xch_reserve_coin_spend = make_spend(
        last_xch_reserve_coin,
        p2_singleton_puzzle,
        last_xch_reserve_coin_solution
    )

    # 9. spend ephemeral XCH coin to create new XCH reserve, respond to offer
    eph_xch_coin = Coin(
        last_xch_reserve_coin.name(),
        OFFER_MOD_HASH,
        last_xch_reserve_coin.amount
    )
    xch_notarized_payment = notarized_payments.get(None)[0]

    eph_xch_coin_notarized_payments = []
    eph_xch_coin_notarized_payments.append(
        [
            xch_notarized_payment.nonce,
            [
                xch_notarized_payment.puzzle_hash,
                removed_xch_amount + burned_liquidity_amount,
                xch_notarized_payment.memos
            ]
        ]
    )
    if new_xch_reserve_amount > 0:
        eph_xch_coin_notarized_payments.append([
            current_pair_coin.name(),
            [p2_singleton_puzzle_hash, new_xch_reserve_amount]
        ])
    if xch_eph_coin_extra_payment is not None:
        eph_xch_coin_notarized_payments.append(xch_eph_coin_extra_payment)

    eph_xch_coin_solution = Program.to(eph_xch_coin_notarized_payments)
    eph_xch_coin_spend = make_spend(
        eph_xch_coin, OFFER_MOD, eph_xch_coin_solution)

    sb = SpendBundle(
        cs_from_initial_offer + [
            eph_liquidity_coin_spend,
            liquidity_burn_coin_spend,
            pair_singleton_spend,
            last_token_reserve_coin_spend,
            eph_token_coin_spend,
            last_xch_reserve_coin_spend,
            eph_xch_coin_spend
        ],
        offer_spend_bundle.aggregated_signature
    )

    return sb


async def respond_to_swap_offer(
    pair_launcher_id,
    current_pair_coin,
    creation_spend,
    token_tail_hash,
    token_hidden_puzzle_hash,
    pair_liquidity,
    pair_xch_reserve,
    pair_token_reserve,
    offer_str,
    last_xch_reserve_coin,
    last_token_reserve_coin,
    # coin_parent_coin_info, inner_puzzle_hash, amount
    last_token_reserve_lineage_proof,
    total_donation_amount=0,
    donation_addresses=[],
    donation_weights=[]
):
    coin_spends = []  # all spends that will get included in the returned spend bundle

    # 1. detect offered ephemeral coin (XCH or token)
    offer = Offer.from_bech32(offer_str)
    offer_spend_bundle = offer.to_spend_bundle()
    offer_coin_spends = offer_spend_bundle.coin_spends

    eph_coin = None
    eph_coin_is_cat = False  # true if token is offered, false if XCH is offered
    # needed when spending eph_liquidity_coin since it's a CAT
    eph_coin_creation_spend = None

    announcement_asserts = []  # assert everything when the old  XCH reserve is spent

    eph_token_coin_puzzle = get_cat_puzzle(
        token_tail_hash,
        token_hidden_puzzle_hash,
        OFFER_MOD
    )
    eph_token_coin_puzzle_hash = eph_token_coin_puzzle.get_tree_hash()

    asked_for_amount = 0
    for k, v in offer.get_requested_amounts().items():
        asked_for_amount = v

    for coin_spend in offer_coin_spends:
        if coin_spend.coin.parent_coin_info == b"\x00" * 32:  # 'hint' for offer requested coin
            continue

        coin_spends.append(coin_spend)
        conditions_dict = conditions_dict_for_solution(
            coin_spend.puzzle_reveal,
            coin_spend.solution,
            INFINITE_COST
        )

        # is this spend creating an ephemeral coin?
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            puzzle_hash = cwa.vars[0]
            amount = SExp.to(cwa.vars[1]).as_int()

            if puzzle_hash in [OFFER_MOD_HASH, eph_token_coin_puzzle_hash]:
                eph_coin = Coin(coin_spend.coin.name(), puzzle_hash, amount)
                eph_coin_creation_spend = coin_spend
                eph_coin_is_cat = puzzle_hash == eph_token_coin_puzzle_hash

        # is there any announcement that we'll need to assert?
        # cwa = condition with args
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []):
            announcement_asserts.append([
                ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                std_hash(coin_spend.coin.name() + cwa.vars[0])
            ])

    # 2. math stuff

    new_xch_reserve_amount = pair_xch_reserve
    new_token_reserve_amount = pair_token_reserve

    inverse_fee = 993 if token_hidden_puzzle_hash is None else 999
    if eph_coin_is_cat:  # token offered, so swap is token -> XCH
        token_amount = eph_coin.amount
        new_xch_reserve_amount -= inverse_fee * token_amount * \
            pair_xch_reserve // (1000 * pair_token_reserve +
                                 inverse_fee * token_amount)
        new_token_reserve_amount += token_amount
    else:
        xch_amount = eph_coin.amount - total_donation_amount
        new_token_reserve_amount -= inverse_fee * xch_amount * \
            pair_token_reserve // (1000 * pair_xch_reserve + inverse_fee * xch_amount)
        new_xch_reserve_amount += xch_amount

    # 3. spend singleton
    pair_singleton_puzzle = get_pair_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )
    pair_singleton_inner_puzzle = get_pair_inner_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve,
        token_hidden_puzzle_hash
    )

    inner_inner_sol = Program.to((
        (
            current_pair_coin.name(),
            (
                last_xch_reserve_coin.name(),
                last_token_reserve_coin.name()
            )
        ),
        [
            eph_coin.amount if eph_coin_is_cat else eph_coin.amount - total_donation_amount,
            0 if eph_coin_is_cat else 1,
        ]
    ))
    pair_singleton_inner_solution = Program.to([
        SWAP_PUZZLE if token_hidden_puzzle_hash is None else RCAT_SWAP_PUZZLE,
        Program.to(
            MERKLE_PROOFS[SWAP_PUZZLE_HASH] if token_hidden_puzzle_hash is None else RCAT_MERKLE_PROOFS[RCAT_SWAP_PUZZLE_HASH]
        ),
        inner_inner_sol
    ])

    lineage_proof = lineage_proof_for_coinsol(creation_spend)
    pair_singleton_solution = solution_for_singleton(
        lineage_proof, current_pair_coin.amount, pair_singleton_inner_solution
    )

    pair_singleton_spend = make_spend(
        current_pair_coin, pair_singleton_puzzle, pair_singleton_solution)
    coin_spends.append(pair_singleton_spend)

    # 4. spend token reserve
    p2_singleton_puzzle = pay_to_singleton_flashloan_puzzle(pair_launcher_id)
    p2_singleton_puzzle_hash = p2_singleton_puzzle.get_tree_hash()

    last_token_reserve_coin_extra_conditions = [
        [
            ConditionOpcode.CREATE_COIN,
            OFFER_MOD_HASH,
            new_token_reserve_amount if eph_coin_is_cat else pair_token_reserve
        ]
    ]
    total_token_amount = last_token_reserve_coin.amount
    if eph_coin_is_cat:
        total_token_amount += eph_coin.amount
    else:
        total_token_amount -= total_token_amount

    if total_token_amount > new_token_reserve_amount:
        raise Exception(
            f"You offered an extra {total_token_amount - new_token_reserve_amount} tokens - please use the exact amounts shown.")


    last_token_reserve_coin_inner_solution = get_cat_inner_solution(
        token_hidden_puzzle_hash is not None,
        p2_singleton_puzzle,
        solution_for_p2_singleton_flashloan(
            last_token_reserve_coin,
            pair_singleton_inner_puzzle.get_tree_hash(),
            extra_conditions=last_token_reserve_coin_extra_conditions
        )
    )
    reserve_spendable_cats = [
        SpendableCAT(
            last_token_reserve_coin,
            token_tail_hash,
            get_cat_inner_puzzle(
                token_hidden_puzzle_hash,
                p2_singleton_puzzle
            ),
            last_token_reserve_coin_inner_solution,
            lineage_proof=LineageProof(
                last_token_reserve_lineage_proof[0],
                last_token_reserve_lineage_proof[1],
                last_token_reserve_lineage_proof[2]
            )
        )
    ]

    if eph_coin_is_cat:
        reserve_spendable_cats.append(
            SpendableCAT(
                eph_coin,
                token_tail_hash,
                get_cat_inner_puzzle(
                    token_hidden_puzzle_hash,
                    OFFER_MOD
                ),
                get_cat_inner_solution(
                    token_hidden_puzzle_hash is not None,
                    OFFER_MOD,
                    Program.to([])
                ),
                lineage_proof=LineageProof(
                    eph_coin_creation_spend.coin.parent_coin_info,
                    get_innerpuzzle_from_puzzle(
                        eph_coin_creation_spend.puzzle_reveal).get_tree_hash(),
                    eph_coin_creation_spend.coin.amount
                )
            )
        )

    for cs in unsigned_spend_bundle_for_spendable_cats(CAT_MOD, reserve_spendable_cats).coin_spends:
        coin_spends.append(cs)

    # 5. Spend intermediary token reserve coin
    intermediary_token_reserve_coin_amount = new_token_reserve_amount if eph_coin_is_cat else pair_token_reserve
    intermediary_token_reserve_coin = Coin(
        last_token_reserve_coin.name(),
        get_cat_puzzle(
            token_tail_hash,
            token_hidden_puzzle_hash,
            OFFER_MOD
        ).get_tree_hash(),
        intermediary_token_reserve_coin_amount
    )

    p2_singleton_puzzle = pay_to_singleton_flashloan_puzzle(pair_launcher_id)
    p2_singleton_puzzle_hash = p2_singleton_puzzle.get_tree_hash()
    p2_singleton_cat_puzzle = get_cat_puzzle(
        token_tail_hash,
        token_hidden_puzzle_hash,
        p2_singleton_puzzle
    )
    p2_singleton_cat_puzzle_hash = p2_singleton_cat_puzzle.get_tree_hash()

    intermediary_token_reserve_notarized_payments = [
        [
            current_pair_coin.name(),
            [p2_singleton_puzzle_hash, new_token_reserve_amount]
        ]
    ]
    if not eph_coin_is_cat:
        notarized_payment = offer.get_requested_payments()[token_tail_hash][0]
        intermediary_token_reserve_notarized_payments.append(
            [
                notarized_payment.nonce,
                [notarized_payment.puzzle_hash, pair_token_reserve -
                    new_token_reserve_amount, notarized_payment.memos]
            ]
        )

    intermediary_token_reserve_coin_inner_solution = get_cat_inner_solution(
        token_hidden_puzzle_hash is not None,
        OFFER_MOD,
        Program.to(
            intermediary_token_reserve_notarized_payments
        )
    )

    intermediary_token_spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, [
        SpendableCAT(
            intermediary_token_reserve_coin,
            token_tail_hash,
            get_cat_inner_puzzle(
                token_hidden_puzzle_hash,
                OFFER_MOD
            ),
            intermediary_token_reserve_coin_inner_solution,
            lineage_proof=LineageProof(
                last_token_reserve_coin.parent_coin_info,
                get_cat_puzzle(
                    token_tail_hash,
                    token_hidden_puzzle_hash,
                    p2_singleton_puzzle
                ).get_tree_hash(),
                last_token_reserve_coin.amount
            )
        )
    ])

    coin_spends.append(intermediary_token_spend_bundle.coin_spends[0])

    # 6. spend eph coin if it is xch
    if not eph_coin_is_cat:
        # just destroy the XCH; they'll be used to create the new reserve
        coin_spends.append(make_spend(eph_coin, OFFER_MOD, Program.to([])))

    # 7. Spend last xch reserve to create intermediary coin
    last_xch_reserve_coin_extra_conditions = [
        [
            ConditionOpcode.CREATE_COIN,
            OFFER_MOD_HASH,
            new_xch_reserve_amount
        ]
    ] + announcement_asserts

    total_xch_amount = last_xch_reserve_coin.amount
    if not eph_coin_is_cat:
        total_xch_amount += eph_coin.amount
    else:
        total_xch_amount -= asked_for_amount + total_donation_amount

    if total_donation_amount > 0:
        extra_xch_amount = total_xch_amount - new_xch_reserve_amount
        # only donate if donation addresses were provided
        # and the correct total_donation_amount was requested
        # this way, we know this is not an error
        if len(donation_weights) == 0 or (extra_xch_amount != total_donation_amount and extra_xch_amount != 0):
            raise Exception(
                f"You offered an excess of {extra_xch_amount} mojos.")

        total_weights = sum(donation_weights)
        total_distributed = 0
        donation_conds = []
        for i, donation_address in enumerate(donation_addresses[1:]):
            donation_amount = total_donation_amount * \
                donation_weights[i + 1] // total_weights

            if donation_address != "FEE":
                donation_conds.append([
                    ConditionOpcode.CREATE_COIN,
                    decode_puzzle_hash(donation_address),
                    donation_amount
                ])
            else:
                donation_conds.append([
                    ConditionOpcode.RESERVE_FEE,
                    donation_amount
                ])
            total_distributed += donation_amount

        # make sure no moo remains unaccounted for by sending
        # everything left to the first donation address
        if donation_addresses[0] != "FEE":
            donation_conds.append([
                ConditionOpcode.CREATE_COIN,
                decode_puzzle_hash(donation_addresses[0]),
                total_donation_amount - total_distributed
            ])
        else:
            donation_conds.append([
                ConditionOpcode.RESERVE_FEE,
                total_donation_amount - total_distributed
            ])

        # convert the donations to a coin that it spent
        # the superset rule provides some protection in the mempool
        donation_coin_puzzle = Program.to((1, donation_conds))
        donation_coin_puzzle_hash = donation_coin_puzzle.get_tree_hash()
        donation_coin = Coin(last_xch_reserve_coin.name(),
                             donation_coin_puzzle_hash, total_donation_amount)
        donation_coin_spend = make_spend(
            donation_coin, donation_coin_puzzle, Program.to([]))
        coin_spends.append(donation_coin_spend)

        # lastly, make sure this coin is created :)
        last_xch_reserve_coin_extra_conditions.append([
            ConditionOpcode.CREATE_COIN,
            donation_coin_puzzle_hash,
            total_donation_amount
        ])

    last_xch_reserve_coin_solution = solution_for_p2_singleton_flashloan(
        last_xch_reserve_coin,
        pair_singleton_inner_puzzle.get_tree_hash(),
        extra_conditions=last_xch_reserve_coin_extra_conditions
    )

    last_xch_reserve_coin_spend = make_spend(
        last_xch_reserve_coin,
        p2_singleton_puzzle,
        last_xch_reserve_coin_solution
    )
    coin_spends.append(last_xch_reserve_coin_spend)

    # 8. Spend intermediary xch reserve coin
    intermediary_xch_reserve_coin = Coin(
        last_xch_reserve_coin.name(),
        OFFER_MOD_HASH,
        new_xch_reserve_amount
    )

    intermediary_xch_reserve_coin_notarized_payments = [
        [
            current_pair_coin.name(),
            [p2_singleton_puzzle_hash, new_xch_reserve_amount]
        ]
    ]
    if eph_coin_is_cat:
        notarized_payment = offer.get_requested_payments().get(None)[0]
        intermediary_xch_reserve_coin_notarized_payments.append(
            [
                notarized_payment.nonce,
                [notarized_payment.puzzle_hash,
                    asked_for_amount, notarized_payment.memos]
            ]
        )
    intermediary_xch_reserve_coin_solution = Program.to(
        intermediary_xch_reserve_coin_notarized_payments)

    intermediary_token_reserve_coin_spend = make_spend(
        intermediary_xch_reserve_coin,
        OFFER_MOD,
        intermediary_xch_reserve_coin_solution
    )
    coin_spends.append(intermediary_token_reserve_coin_spend)

    return SpendBundle(
        coin_spends, offer_spend_bundle.aggregated_signature
    )


async def get_fee_estimate(mempool_sb, full_node_client: FullNodeRpcClient):
    # upper bound (exaggerated so the tx doesn't fail)
    cost_of_operation = 700000000
    # from benchmarks:
    #   - add/remove liquidity -> ~250,000,000
    #   - add/remove liquidity -> ~250,000,000
    #   - xch to token -> ~150,000,000
    #   - token to xch -> ~200,000,000
    if mempool_sb is None:
        try:
            fee_per_cost_resp = await full_node_client.get_fee_estimate(target_times=[0], cost=cost_of_operation)
        except:
            fee_per_cost_resp = {'estimates': [0]}
        fee = int(fee_per_cost_resp['estimates'][0]) + 1
        # logic for the thing below: if there is no fee, as is currently the case on mainnet,
        # this branch would still return 1 mojo as suggested fee
        # we don't want to teach users to ignore the minimum fee, do we?
        return fee if fee != 1 else 0

    cost_of_mempool_sb, fee_of_mempool_sb = get_spend_bundle_cost_and_fees(mempool_sb)
    mempool_fee_per_cost: float = fee_of_mempool_sb / cost_of_mempool_sb

    fee = int(max(5, mempool_fee_per_cost) * (cost_of_operation +
              cost_of_mempool_sb)) - fee_of_mempool_sb + MEMPOOL_MIN_FEE_INCREASE
    return fee

"""
XCH coin breakdown:
initial_xch_liquidity - provided as XCH liquidity
initial_cat_liquidity - used to mint LP tokens
ROUTER_MIN_FEE - tx fee
DEV_DEPLOYMENT_FEE - sent to tibetswap dev
1 - amount locked in pair singleton
"""
async def create_pair_with_liquidity(
    tail_hash, # bytes
    hidden_puzzle_hash, # bytes
    offer_str, # str
    initial_xch_liquidity,
    initial_cat_liquidity,
    liquidity_destination_address,
    router_launcher_id,
    current_router_coin,
    current_router_coin_creation_spend,
):
    # 1. Detect ephemeral coins (those created by the offer that we're allowed to use)
    offer = Offer.from_bech32(offer_str)
    offer_spend_bundle = offer.to_spend_bundle()
    offer_coin_spends = offer_spend_bundle.coin_spends

    eph_xch_coin = None
    eph_token_coin = None

    # needed when spending eph_token_coin since it's a CAT
    eph_token_coin_creation_spend = None
    announcement_asserts = []  # assert everything when the liquidity cat is minted

    ephemeral_token_coin_puzzle = get_cat_puzzle(
        tail_hash,
        hidden_puzzle_hash,
        OFFER_MOD
    )
    ephemeral_token_coin_puzzle_hash = ephemeral_token_coin_puzzle.get_tree_hash()

    # all valid coin spends (i.e., not 'hints' for offered assets or coins)
    #cs_from_initial_offer = []
    cs_to_aggregate = []
    cs_for_second_offer = []

    for coin_spend in offer_coin_spends:
        # cs_from_initial_offer.append(coin_spend)
        conditions_dict = conditions_dict_for_solution(
            coin_spend.puzzle_reveal,
            coin_spend.solution,
            INFINITE_COST
        )

        # is this spend creating an ephemeral coin?
        ephemeral = False
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            puzzle_hash = cwa.vars[0]
            amount = SExp.to(cwa.vars[1]).as_int()

            if puzzle_hash == OFFER_MOD_HASH:
                eph_xch_coin = Coin(coin_spend.coin.name(),
                                    puzzle_hash, amount)
                ephemeral = True
                cs_to_aggregate.append(coin_spend)
                if amount != initial_xch_liquidity + initial_cat_liquidity + ROUTER_MIN_FEE + DEV_DEPLOYMENT_FEE + 1:
                    raise Exception(f"Invalid XCH offer amount; should be {initial_xch_liquidity + ROUTER_MIN_FEE + DEV_DEPLOYMENT_FEE + 1} mojos")

            if puzzle_hash == ephemeral_token_coin_puzzle_hash:
                eph_token_coin = Coin(
                    coin_spend.coin.name(), puzzle_hash, amount)
                if amount != initial_cat_liquidity:
                    raise Exception(f"Invalid CAT offer amount; should be {initial_cat_liquidity} mojos")
                eph_token_coin_creation_spend = coin_spend
                ephemeral = True
                cs_for_second_offer.append(coin_spend)

        if not ephemeral:
            cs_for_second_offer.append(coin_spend)

        # is there any announcement that we'll need to assert?
        # cwa = condition with args
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []):
            announcement_asserts.append([
                ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                std_hash(coin_spend.coin.name() + cwa.vars[0])
            ])

    # 2. Spend ephemeral XCH coin to create a standard coin - this will be used
    #   to launch the router and request liquidity tokens for the 'add liquidity' part
    rand_bytes = token_bytes(nbytes=32)
    temp_sk = AugSchemeMPL.key_gen(mnemonic_to_seed(bytes_to_mnemonic(rand_bytes)))
    temp_pk = temp_sk.get_g1()

    temp_custody_puzzle = puzzle_for_synthetic_public_key(temp_pk)
    temp_custody_puzzle_hash = temp_custody_puzzle.get_tree_hash()

    eph_xch_coin_solution = Program.to([
        Program.to([
            eph_xch_coin.name(),
            [temp_custody_puzzle_hash, eph_xch_coin.amount]
        ]),
    ])
    eph_xch_coin_spend = make_spend(
        eph_xch_coin, OFFER_MOD, eph_xch_coin_solution)
    cs_to_aggregate.append(eph_xch_coin_spend)

    temp_custody_coin = Coin(eph_xch_coin.name(), temp_custody_puzzle_hash, eph_xch_coin.amount)
    router_launcher_coin = Coin(temp_custody_coin.name(), temp_custody_puzzle_hash, ROUTER_MIN_FEE + 1)
    new_ephemeral_xch_coin = Coin(temp_custody_coin.name(), temp_custody_puzzle_hash, initial_xch_liquidity + initial_cat_liquidity)
    temp_custody_conditions = [
        [ConditionOpcode.CREATE_COIN, temp_custody_puzzle_hash, ROUTER_MIN_FEE + 1],
        [ConditionOpcode.CREATE_COIN, decode_puzzle_hash(os.environ.get("TIBETSWAP_FEE_ADDRESS", "")), DEV_DEPLOYMENT_FEE],
        [ConditionOpcode.CREATE_COIN, temp_custody_puzzle_hash, initial_xch_liquidity + initial_cat_liquidity],
        [ConditionOpcode.ASSERT_CONCURRENT_SPEND, router_launcher_coin.name()]
    ]

    # 3. Create deposit liquidity offer

    new_ephemeral_xch_coin_spend = make_spend(
        new_ephemeral_xch_coin,
        temp_custody_puzzle,
        solution_for_delegated_puzzle(Program.to((1, [
            [ConditionOpcode.CREATE_COIN, OFFER_MOD_HASH, initial_xch_liquidity + initial_cat_liquidity]
        ])), [])
    )
    cs_for_second_offer.append(new_ephemeral_xch_coin_spend)

    # this requires that liq tokens are paid to the right recipients
    payment_req_coin = Coin(b'\x00' * 32, OFFER_MOD_HASH, initial_xch_liquidity + initial_cat_liquidity)
    liq_token_notarized_payments = Program.to([
        Program.to([
            new_ephemeral_xch_coin.name(),
            [decode_puzzle_hash(liquidity_destination_address), initial_cat_liquidity, [decode_puzzle_hash(liquidity_destination_address)]]
        ])
    ])

    pair_launcher_id_hex, router_launch_sb, current_pair_coin, pair_launcher_spend = await create_pair_from_coin(router_launcher_coin, temp_custody_puzzle, tail_hash, hidden_puzzle_hash, router_launcher_id, current_router_coin, current_router_coin_creation_spend)
    for cs in router_launch_sb.coin_spends:
        cs_to_aggregate.append(cs)

    liquidity_tail_hash = pair_liquidity_tail_puzzle(bytes.fromhex(pair_launcher_id_hex)).get_tree_hash()
    cs_for_second_offer.append(make_spend(
        payment_req_coin,
        construct_cat_puzzle(CAT_MOD, liquidity_tail_hash, OFFER_MOD),
        liq_token_notarized_payments
    ))

    liquidity_offer_sb = SpendBundle(
        cs_for_second_offer,
        AugSchemeMPL.aggregate([])
    )
    liquidity_offer = Offer.from_spend_bundle(liquidity_offer_sb)
    liquidity_offer_str = liquidity_offer.to_bech32()

    # 4. Spend temp custody coin

    temp_custody_spend = make_spend(
        temp_custody_coin,
        temp_custody_puzzle,
        solution_for_delegated_puzzle(Program.to((1, temp_custody_conditions)), [])
    )
    cs_to_aggregate.append(temp_custody_spend)

    # 5. Deposit liquidity using function

    liquidity_sb = await respond_to_deposit_liquidity_offer(
        bytes.fromhex(pair_launcher_id_hex),
        current_pair_coin,
        pair_launcher_spend,
        tail_hash,
        hidden_puzzle_hash,
        0, 0, 0, # no liquidity
        liquidity_offer_str,
        None, None, None # no previous reserves since pool was just added
    )

    # 6. Assmeble final spend bundle and isgn it
    coin_spends = liquidity_sb.coin_spends
    for cs in cs_to_aggregate:
        coin_spends.append(cs)

    cs_to_sign = [cs for cs in coin_spends if cs.coin.puzzle_hash == temp_custody_puzzle_hash]
    assert len(cs_to_sign) == 3
    temp_custody_sb = await sign_spend_bundle_with_specific_sk(cs_to_sign, temp_sk)

    return SpendBundle(
        coin_spends,
        AugSchemeMPL.aggregate([offer_spend_bundle.aggregated_signature, temp_custody_sb.aggregated_signature])
    )
