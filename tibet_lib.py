import os
import sys
import asyncio
from clvm import SExp
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
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol, pay_to_singleton_puzzle, SINGLETON_MOD_HASH, SINGLETON_MOD, P2_SINGLETON_MOD, SINGLETON_LAUNCHER_HASH, SINGLETON_LAUNCHER, lineage_proof_for_coinsol, puzzle_for_singleton, solution_for_singleton, generate_launcher_coin
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, calculate_synthetic_secret_key, DEFAULT_HIDDEN_PUZZLE_HASH, puzzle_for_synthetic_public_key, solution_for_delegated_puzzle
from chia.wallet.puzzles.cat_loader import CAT_MOD_HASH, CAT_MOD
from chia.wallet.trading.offer import OFFER_MOD_HASH, OFFER_MOD
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from cdv.cmds.sim_utils import SIMULATOR_ROOT_PATH
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.util.config import load_config
from chia.util.ints import uint16, uint32
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.coin_spend import CoinSpend
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
    get_innerpuzzle_from_puzzle,
)
from chia.wallet.trading.offer import Offer
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import bech32_decode, bech32_encode, convertbits
from chia.wallet.util.puzzle_compression import (
    compress_object_with_puzzles,
    decompress_object_with_puzzles,
    lowest_best_version,
)
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions
from chia.util.hash import std_hash

ROUTER_MOD: Program = load_clvm("../../../../../../../clvm/router.clvm", recompile=False)
PAIR_MOD: Program = load_clvm("../../../../../../../clvm/pair.clvm", recompile=False)
LIQUIDITY_TAIL_MOD: Program = load_clvm("../../../../../../../clvm/liquidity_tail.clvm", recompile=False)

ROUTER_MOD_HASH = ROUTER_MOD.get_tree_hash()
PAIR_MOD_HASH = PAIR_MOD.get_tree_hash()
LIQUIDITY_TAIL_MOD_HASH = LIQUIDITY_TAIL_MOD.get_tree_hash()

P2_SINGLETON_MOD_HASH = P2_SINGLETON_MOD.get_tree_hash()

def get_router_puzzle():
    return ROUTER_MOD.curry(
        PAIR_MOD_HASH,
        SINGLETON_MOD_HASH,
        P2_SINGLETON_MOD_HASH,
        CAT_MOD_HASH,
        LIQUIDITY_TAIL_MOD_HASH,
        OFFER_MOD_HASH,
        997,
        SINGLETON_LAUNCHER_HASH,
        ROUTER_MOD_HASH
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


def pair_liquidity_tail_puzzle(pair_launcher_id):
    return LIQUIDITY_TAIL_MOD.curry(
        (SINGLETON_MOD_HASH, (pair_launcher_id, SINGLETON_LAUNCHER_HASH))
    )


async def get_full_node_client(
    chia_root: str
) -> FullNodeRpcClient:
    root_path = Path(chia_root)

    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    rpc_port = config["full_node"]["rpc_port"]
    node_client: FullNodeRpcClient = await FullNodeRpcClient.create(
        self_hostname, uint16(rpc_port), root_path, config
    )
    await node_client.healthz()

    return node_client

async def get_wallet_client(
    chia_root: str
) -> FullNodeRpcClient:
    root_path = Path(chia_root)

    config = load_config(root_path, "config.yaml")
    self_hostname = config["self_hostname"]
    rpc_port = config["wallet"]["rpc_port"]
    wallet_client: WalletRpcClient = await WalletRpcClient.create(
        self_hostname, uint16(rpc_port), root_path, config
    )
    await wallet_client.healthz()

    return wallet_client


async def launch_router_from_coin(parent_coin, parent_coin_puzzle):
    comment: List[Tuple[str, str]] = [("tibet", "v1")]
    conds, launcher_coin_spend = launch_conditions_and_coinsol(parent_coin, get_router_puzzle(), comment, 1)
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
        parent_coin_puzzle,
        solution_for_delegated_puzzle(Program.to((1, conds)), [])
    )
        
    sb = SpendBundle(
        [launcher_coin_spend, p2_coin_spend],
        AugSchemeMPL.aggregate([])
    )
    launcher_id = launcher_coin_spend.coin.name().hex()
    
    return launcher_id, sb

async def create_test_cat(token_amount, coin, coin_puzzle):
    coin_id = coin.name()

    tail = GenesisById.construct([coin_id])
    tail_hash = tail.get_tree_hash()
    cat_inner_puzzle = coin_puzzle

    cat_puzzle = construct_cat_puzzle(CAT_MOD, tail_hash, cat_inner_puzzle)
    cat_puzzle_hash = cat_puzzle.get_tree_hash()

    cat_creation_tx = CoinSpend(
        coin,
        cat_inner_puzzle, # same as this coin's puzzle
        solution_for_delegated_puzzle(Program.to((1, [
            [ConditionOpcode.CREATE_COIN, cat_puzzle_hash, token_amount * 10000],
            [ConditionOpcode.CREATE_COIN, coin.puzzle_hash, coin.amount - token_amount * 10000],
        ])), [])
    )
    
    cat_coin = Coin(
        coin.name(), # parent
        cat_puzzle_hash,
        token_amount * 10000
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
    cat_eve_spend = cat_eve_spend_bundle.coin_spends[0]
    
    sb = SpendBundle(
        [cat_creation_tx, cat_eve_spend],
        AugSchemeMPL.aggregate([])
    )
    
    return tail_hash.hex(), sb


async def create_pair_from_coin(
    coin,
    coin_puzzle,
    tail_hash,
    router_launcher_id,
    current_router_coin,
    current_router_coin_creation_spend
):
    lineage_proof = lineage_proof_for_coinsol(current_router_coin_creation_spend)
    
    router_inner_puzzle = get_router_puzzle()
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

    fund_spend = CoinSpend(
        coin,
        coin_puzzle,
        solution_for_delegated_puzzle(Program.to((1, [
            [ConditionOpcode.CREATE_COIN, coin.puzzle_hash, coin.amount - 2],
            assert_launcher_announcement
        ])), [])
    )
    
    pair_launcher_id = Coin(current_router_coin.name(), SINGLETON_LAUNCHER_HASH, 2).name().hex()
    sb = SpendBundle(
        [router_singleton_spend, pair_launcher_spend, fund_spend],
        AugSchemeMPL.aggregate([])
    )
    return pair_launcher_id, sb

async def sync_router(full_node_client, last_router_id):
    last_router_id = bytes.fromhex(last_router_id)

    new_pairs = []
    coin_record = await full_node_client.get_coin_record_by_name(last_router_id)
    if not coin_record.spent:
        # hack
        current_router_coin, creation_spend, _ = await sync_router(full_node_client, coin_record.coin.parent_coin_info.hex())
        return current_router_coin, creation_spend, []
    
    router_puzzle_hash = get_router_puzzle().get_tree_hash()

    while coin_record.spent:
        creation_spend = await full_node_client.get_puzzle_and_solution(last_router_id, coin_record.spent_block_index)
        _, conditions_dict, __ = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )

        if coin_record.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
            solution_program = creation_spend.solution.to_program()
            tail_hash = [_ for _ in solution_program.as_iter()][-1].as_python()[-1]
        
        for cwa in conditions_dict[ConditionOpcode.CREATE_COIN]:
            new_puzzle_hash = cwa.vars[0]
            new_amount = cwa.vars[1]

            if new_amount == b"\x01": # CREATE_COIN with amount=1 -> router recreated
                new_router_coin = Coin(last_router_id, new_puzzle_hash, 1)

                last_router_id = new_router_coin.name()
            elif new_amount == b"\x02": # CREATE_COIN with amount=2 -> pair launcher deployed
                assert new_puzzle_hash == SINGLETON_LAUNCHER_HASH
                
                pair_launcher_coin = Coin(creation_spend.coin.name(), new_puzzle_hash, 2)
                pair_launcher_id = pair_launcher_coin.name()
                
                new_pairs.append((tail_hash.hex(), pair_launcher_id.hex()))
            else:
                print("Someone did something extremely weird with the router - time to call the cops.")
                sys.exit(1)

        coin_record = await full_node_client.get_coin_record_by_name(last_router_id)
    
    return coin_record.coin, creation_spend, new_pairs


async def sync_pair(full_node_client, last_synced_coin_id):
    last_synced_coin_id = bytes.fromhex(last_synced_coin_id)

    state = {
        "liquidity": 0,
        "xch_reserve": 0,
        "token_reserve": 0
    }
    coin_record = await full_node_client.get_coin_record_by_name(last_synced_coin_id)
    last_synced_coin = coin_record.coin

    if coin_record.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
        creation_spend = await full_node_client.get_puzzle_and_solution(last_synced_coin_id, coin_record.spent_block_index)
        _, conditions_dict, __ = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )
        last_synced_coin = Coin(coin_record.coin.name(), conditions_dict[ConditionOpcode.CREATE_COIN][0].vars[0], 1)
        return last_synced_coin, creation_spend, state

    if not coin_record.spent:
        # hack
        current_pair_coin, creation_spend, state = await sync_pair(full_node_client, coin_record.coin.parent_coin_info.hex())
        return current_pair_coin, creation_spend, state

    creation_spend = None
    while coin_record.spent:
        creation_spend = await full_node_client.get_puzzle_and_solution(last_synced_coin_id, coin_record.spent_block_index)
        _, conditions_dict, __ = conditions_dict_for_solution(
            creation_spend.puzzle_reveal,
            creation_spend.solution,
            INFINITE_COST
        )
        
        for cwa in conditions_dict[ConditionOpcode.CREATE_COIN]:
            new_puzzle_hash = cwa.vars[0]
            new_amount = cwa.vars[1]

            if new_amount == b"\x01": # CREATE_COIN with amount=1 -> pair recreation
                last_synced_coin = Coin(last_synced_coin_id, new_puzzle_hash, 1)
                last_synced_coin_id = last_synced_coin.name()

        coin_record = await full_node_client.get_coin_record_by_name(new_pair_coin)
    
    # TODO
    # debug
    print("REACHED TODO SECTION SER LINE 370 PROB THX FOR CODING")
    input("SLEEP")
    return last_synced_coin, creation_spend, state


async def respond_to_deposit_liquidity_offer(
    pair_launcher_id,
    current_pair_coin,
    creation_spend,
    token_tail_hash,
    pair_liquidity,
    pair_xch_reserve,
    pair_token_reserve,
    offer_str
):
    # 1. Detect ephemeral coins (those created by the offer that we're allowed to use)
    offer = Offer.from_bech32(offer_str)
    offer_spend_bundle = offer.to_spend_bundle()
    offer_coin_spends = offer_spend_bundle.coin_spends

    eph_xch_coin = None
    eph_token_coin = None

    eph_token_coin_creation_spend = None # needed when spending eph_token_coin since it's a CAT
    announcement_asserts = [] # assert everything when the liquidity cat is minted

    ephemeral_token_coin_puzzle = construct_cat_puzzle(CAT_MOD, token_tail_hash, OFFER_MOD)
    ephemeral_token_coin_puzzle_hash = ephemeral_token_coin_puzzle.get_tree_hash()

    cs_from_initial_offer = [] # all valid coin spends (i.e., not 'hints' for offered assets or coins)

    for coin_spend in offer_coin_spends:
        if coin_spend.coin.parent_coin_info == b"\x00" * 32: # 'hint' for offer requested coin
            continue
        
        cs_from_initial_offer.append(coin_spend)
        _, conditions_dict, __ = conditions_dict_for_solution(
            coin_spend.puzzle_reveal,
            coin_spend.solution,
            INFINITE_COST
        )

        # is this spend creating an ephemeral coin?
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
            puzzle_hash = cwa.vars[0]
            amount = SExp.to(cwa.vars[1]).as_int()

            if puzzle_hash == OFFER_MOD_HASH:
                eph_xch_coin = Coin(coin_spend.coin.name(), puzzle_hash, amount)
            
            if puzzle_hash == ephemeral_token_coin_puzzle_hash:
                eph_token_coin = Coin(coin_spend.coin.name(), puzzle_hash, amount)
                eph_token_coin_creation_spend = coin_spend

        # is there any announcement that we'll need to assert?
        for cwa in conditions_dict.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, []): #cwa = condition with args
            announcement_asserts.append([
                ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                std_hash(coin_spend.coin.name() + cwa.vars[0])
            ])

    # 2. Math stuff
    deposited_token_amount = eph_token_coin.amount

    new_liquidity_token_amount = deposited_token_amount
    if pair_token_reserve != 0:
        new_liquidity_token_amount = deposited_token_amount * pair_liquidity // pair_token_reserve
    
    deposited_xch_amount = eph_xch_coin.amount - deposited_token_amount
    if pair_xch_reserve != 0:
        deposited_xch_amount = deposited_token_amount * pair_xch_reserve // pair_token_reserve

    fee = eph_xch_coin.amount - deposited_xch_amount - new_liquidity_token_amount
    if fee < 0:
        print(f"Uh... to few XCH coins; need {fee} more")
        sys.exit(1)


    # 3. spend the token ephemeral coin to create the token reserve coin
    # todo: for multiple spends, you knwo what to do - spend current CAT reserve
    p2_singleton_puzzle = pay_to_singleton_puzzle(pair_launcher_id)
    p2_singleton_puzzle_cat =  construct_cat_puzzle(CAT_MOD, token_tail_hash, p2_singleton_puzzle)
    
    eph_token_coin_inner_solution = Program.to([
        Program.to([
            current_pair_coin.name(),
            [p2_singleton_puzzle_cat.get_tree_hash(), deposited_token_amount + pair_xch_reserve]
        ])
    ])
    
    spendable_cats_for_token_reserve = []
    spendable_cats_for_token_reserve.append(
        SpendableCAT(
            eph_token_coin,
            token_tail_hash,
            OFFER_MOD,
            eph_token_coin_inner_solution,
            lineage_proof=LineageProof(
                eph_token_coin_creation_spend.coin.parent_coin_info,
                get_innerpuzzle_from_puzzle(eph_token_coin_creation_spend.puzzle_reveal).get_tree_hash(),
                eph_token_coin_creation_spend.coin.amount
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
    pair_singleton_inner_puzzle = get_pair_inner_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve
    )

    liquidity_cat_mint_coin_tail_solution = Program.to([pair_singleton_inner_puzzle.get_tree_hash()])
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
            [p2_singleton_puzzle.get_tree_hash(), pair_xch_reserve + deposited_xch_amount]
        ]),
        Program.to([
            current_pair_coin.name(),
            [liquidity_cat_mint_coin_puzzle_hash, new_liquidity_token_amount]
        ])
    ]
    eph_xch_coin_solution = Program.to(eph_xch_coin_settlement_things)
    eph_xch_coin_spend = CoinSpend(eph_xch_coin, OFFER_MOD, eph_xch_coin_solution)

    # 5. Re-create the pair singleton (spend it)
    pair_singleton_puzzle = get_pair_puzzle(
        pair_launcher_id,
        token_tail_hash,
        pair_liquidity,
        pair_xch_reserve,
        pair_token_reserve
    )
    pair_singleton_inner_solution = Program.to([
        Program.to([current_pair_coin.name(), b"\x00" * 32, b"\x00" * 32]),
        0,
        Program.to([
            deposited_token_amount,
            liquidity_cat_mint_coin_inner_puzzle_hash,
            eph_xch_coin.name(), # parent of liquidity cat mint coin
            deposited_xch_amount
        ])
    ])
    lineage_proof = lineage_proof_for_coinsol(creation_spend)
    pair_singleton_solution = solution_for_singleton(
        lineage_proof, current_pair_coin.amount, pair_singleton_inner_solution
    )
    pair_singleton_spend = CoinSpend(current_pair_coin, pair_singleton_puzzle, pair_singleton_solution)

    # 6. Spend liquidity cat mint coin
    liquidity_cat_mint_coin = Coin(
        eph_xch_coin.name(),
        liquidity_cat_mint_coin_puzzle_hash,
        new_liquidity_token_amount
    )

    output_conditions = announcement_asserts
    if fee > 0:
        output_conditions.append([ConditionOpcode.RESERVE_FEE, fee])

    output_conditions.append([ConditionOpcode.CREATE_COIN, OFFER_MOD_HASH, new_liquidity_token_amount])

    liquidity_cat_mint_coin_tail_puzzle = pair_liquidity_tail_puzzle(pair_launcher_id)
    output_conditions.append([
        ConditionOpcode.CREATE_COIN,
        0,
        -113,
        liquidity_cat_mint_coin_tail_puzzle,
        liquidity_cat_mint_coin_tail_solution
    ])

    # also assert the XCH ephemeral coin announcement
    # specifically, for the payment made to mint liquidity tokens
    eph_xch_settlement_announcement = eph_xch_coin_settlement_things[-1].get_tree_hash()
    output_conditions.append([
        ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
        std_hash(eph_xch_coin.puzzle_hash + eph_xch_settlement_announcement)
    ])

    liquidity_cat_mint_coin_solution = Program.to([
        output_conditions,
        [],
        liquidity_cat_mint_coin.name(),
        [liquidity_cat_mint_coin.parent_coin_info, liquidity_cat_mint_coin.puzzle_hash, new_liquidity_token_amount],
        [liquidity_cat_mint_coin.parent_coin_info, liquidity_cat_mint_coin_inner_puzzle_hash, new_liquidity_token_amount],
        [],
        []
    ])
    liquidity_cat_mint_coin_spend = CoinSpend(
        liquidity_cat_mint_coin,
        liquidity_cat_mint_coin_puzzle,
        liquidity_cat_mint_coin_solution
    )

    # 7. Ephemeral liquidity cat and we're done
    ephemeral_liquidity_cat_coin_puzzle = construct_cat_puzzle(CAT_MOD, liquidity_cat_tail_hash, OFFER_MOD)
    ephemeral_liquidity_cat_coin_puzzle_hash = ephemeral_liquidity_cat_coin_puzzle.get_tree_hash()

    ephemeral_liquidity_cat = Coin(
        liquidity_cat_mint_coin.name(),
        ephemeral_liquidity_cat_coin_puzzle_hash,
        new_liquidity_token_amount
    )

    notarized_payment = offer.get_requested_payments()[liquidity_cat_tail_hash][0]
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

    sb = SpendBundle(
        [
           eph_xch_coin_spend,
           pair_singleton_spend,
           liquidity_cat_mint_coin_spend,
           ephemeral_liquidity_cat_spend
        ] + token_reserve_creation_spends + cs_from_initial_offer,
        offer_spend_bundle.aggregated_signature
    )

    return sb