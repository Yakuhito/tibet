import pytest
import pytest_asyncio

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, calculate_synthetic_secret_key, DEFAULT_HIDDEN_PUZZLE_HASH
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol, SINGLETON_MOD_HASH, SINGLETON_MOD, SINGLETON_LAUNCHER_HASH, SINGLETON_LAUNCHER, lineage_proof_for_coinsol, puzzle_for_singleton, solution_for_singleton, generate_launcher_coin
from cdv.test import setup as setup_test
from tibet_lib import *
from private_key_things import *
from clvm import SExp

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
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol, SINGLETON_MOD_HASH, SINGLETON_MOD, SINGLETON_LAUNCHER_HASH, SINGLETON_LAUNCHER, lineage_proof_for_coinsol, puzzle_for_singleton, solution_for_singleton, generate_launcher_coin
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
from chia.types.blockchain_format.program import SerializedProgram
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
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient

class TestTibetSwap:
    @pytest_asyncio.fixture(scope="function")
    async def setup(self):
        alice_fingerprint = os.environ.get("ALICE_FINGERPRINT")
        bob_fingerprint = os.environ.get("BOB_FINGERPRINT")
        charlie_fingerprint = os.environ.get("CHARLIE_FINGERPRINT")

        chia_root = os.path.expanduser("~/.chia/simulator/main")
        
        # Get full node client and reset simulator if there are any tx blocks
        full_node_client = await get_sim_full_node_client(chia_root)
        blockchain_state = await full_node_client.get_blockchain_state()
        peak = blockchain_state["peak"]
        if peak.height > 1:
            await full_node_client.revert_blocks(delete_all_blocks=True)

        # Get wallet client and give 2 XCH to each address
        wallet_client = await get_wallet_client(chia_root)

        async def switch_to_fingerprint(fingerprint):
            await wallet_client.log_in(fingerprint)

        async def switch_to_alice():
            await switch_to_fingerprint(alice_fingerprint)

        async def switch_to_bob():
            await switch_to_fingerprint(bob_fingerprint)

        async def switch_to_charlie():
            await switch_to_fingerprint(charlie_fingerprint)

        await switch_to_charlie()
        address = await wallet_client.get_next_address(1, False) # wallet id = 1, new address = false
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)

        await switch_to_bob()
        address = await wallet_client.get_next_address(1, False) # wallet id = 1, new address = false
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)

        await switch_to_alice()
        address = await wallet_client.get_next_address(1, False) # wallet id = 1, new address = false
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)

        yield full_node_client, wallet_client, switch_to_alice, switch_to_bob, switch_to_charlie

    @pytest.mark.asyncio
    async def test_healthz(self, setup):
        full_node_client, wallet_client, switch_to_alice, switch_to_bob, switch_to_charlie = setup
        try:
            full_node_resp = await full_node_client.healthz()
            assert full_node_resp['success']

            wallet_resp = await wallet_client.healthz()
            assert wallet_resp['success']
        finally:
            full_node_client.close()
            wallet_client.close()
            await full_node_client.await_closed()
            await wallet_client.await_closed()

    # def get_created_coins_from_coin_spend(self, cs):
    #     coins = []

    #     _, conditions_dict, __ = conditions_dict_for_solution(
    #         cs.puzzle_reveal,
    #         cs.solution,
    #         INFINITE_COST
    #     )

    #     for cwa in conditions_dict[ConditionOpcode.CREATE_COIN]:
    #         coins.append(Coin(
    #             cs.coin.name(),
    #             cwa.vars[0], # puzzle hash of created coin
    #             SExp.to(cwa.vars[1]).as_int()
    #         ))

    #     return coins

    # async def launch_router(self, network, alice):
    #     coin = await alice.choose_coin(2)
    #     coin = coin.coin # we want a Coin, not a CoinWrapper

    #     alice_sk = alice.pk_to_sk(alice.pk())
    #     synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)

    #     coin_puzzle = puzzle_for_pk(alice.pk())

    #     launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle)

    #     signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)
    #     await network.push_tx(signed_sb)

    #     router_launch_coin_spend = None
    #     router_current_coin = None
    #     for cs in signed_sb.coin_spends:
    #         if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
    #             router_launch_coin_spend = cs
    #             router_current_coin = self.get_created_coins_from_coin_spend(cs)[0]

    #     return bytes.fromhex(launcher_id), router_current_coin, router_launch_coin_spend


    # async def create_test_cat(self, network, alice, token_amount=1000000000): # token_amount = 1000 * 1000000 = 1,000,000 tokens
    #     coin = await alice.choose_coin(token_amount)
    #     coin = coin.coin # we want a Coin, not a CoinWrapper

    #     alice_sk = alice.pk_to_sk(alice.pk())
    #     synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)

    #     coin_puzzle = puzzle_for_pk(alice.pk())

    #     tail_hash, sb = await create_test_cat(token_amount, coin, coin_puzzle)
        
    #     signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)
    #     await network.push_tx(signed_sb)

    #     return bytes.fromhex(tail_hash)

    # async def create_pair(
    #     self,
    #     network,
    #     alice,
    #     router_launcher_id,
    #     tail_hash,
    #     current_router_coin,
    #     current_router_coin_creation_spend
    # ):
    #     coin = await alice.choose_coin(2)
    #     coin = coin.coin # we want a Coin, not a CoinWrapper

    #     alice_sk = alice.pk_to_sk(alice.pk())
    #     synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)

    #     coin_puzzle = puzzle_for_pk(alice.pk())

    #     pair_launcher_id, sb = await create_pair_from_coin(
    #         coin,
    #         coin_puzzle,
    #         tail_hash,
    #         router_launcher_id,
    #         current_router_coin,
    #         current_router_coin_creation_spend
    #     )

    #     signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)
    #     await network.push_tx(signed_sb)

    #     pair_coin = None
    #     pair_coin_creation_spend = None
    #     router_new_coin = None
    #     router_new_coin_creation_spend = None

    #     for cs in sb.coin_spends:
    #         if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
    #             pair_coin_creation_spend = cs
    #             pair_coin = self.get_created_coins_from_coin_spend(cs)[0]
    #         elif cs.coin.amount == 1:
    #             possible_coins = self.get_created_coins_from_coin_spend(cs)
    #             if len(possible_coins) == 2 and possible_coins[0].amount + possible_coins[1].amount == 3:
    #                 router_new_coin_creation_spend = cs
    #                 for pc in possible_coins:
    #                     if pc.amount == 1:
    #                         router_new_coin = pc

    #     return bytes.fromhex(pair_launcher_id), pair_coin, pair_coin_creation_spend, router_new_coin, router_new_coin_creation_spend

    # @pytest.mark.asyncio
    # async def test_router_launch(self, setup):
    #     network, alice, bob = setup
    #     try:
    #         launcher_id, current_router_coin, router_launch_coin_spend = await self.launch_router(network, alice)

    #         cr = await network.get_coin_record_by_name(launcher_id)

    #         assert cr is not None
    #         assert cr.confirmed_block_index is not None
    #         assert cr.spent_block_index is not None
    #     finally:
    #         await network.close()

    # @pytest.mark.asyncio
    # async def test_pair_creation(self, setup):
    #     network, alice, bob = setup
    #     try:
    #         launcher_id, current_router_coin, router_creation_spend  = await self.launch_router(network, alice)

    #         tail_hash = await self.create_test_cat(network, alice)
    #         pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
    #             network, alice, launcher_id, tail_hash, current_router_coin, router_creation_spend
    #         )
    #         assert current_pair_coin is not None
    #         assert pair_creation_spend is not None
    #         assert current_router_coin is not None
    #         assert router_creation_spend is not None

    #         cr = await network.get_coin_record_by_name(pair_launcher_id)
    #         assert cr is not None
    #         assert cr.spent

    #         # Create another pair, just to be sure...
    #         tail_hash = await self.create_test_cat(network, alice)
    #         pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
    #             network, alice, launcher_id, tail_hash, current_router_coin, router_creation_spend
    #         )
    #         assert current_pair_coin is not None
    #         assert pair_creation_spend is not None
    #         assert current_router_coin is not None
    #         assert router_creation_spend is not None

    #         cr = await network.get_coin_record_by_name(pair_launcher_id)
    #         assert cr is not None
    #         assert cr.spent
    #     finally:
    #         await network.close()

    # @pytest.mark.asyncio
    # async def test_pair_liquidity_deposit(self, setup):
    #     network, alice, bob = setup
    #     try:
    #         launcher_id, current_router_coin, router_creation_spend  = await self.launch_router(network, alice)

    #         tail_hash = await self.create_test_cat(network, alice)
    #         pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
    #             network, alice, launcher_id, tail_hash, current_router_coin, router_creation_spend
    #         )
    #         assert current_pair_coin is not None
    #         assert pair_creation_spend is not None
    #         assert current_router_coin is not None
    #         assert router_creation_spend is not None

    #         cr = await network.get_coin_record_by_name(pair_launcher_id)
    #         assert cr is not None
    #         assert cr.spent

    #         liquidity_tail = pair_liquidity_tail_puzzle(pair_launcher_id)
    #         liquidity_tail_hash = liquidity_tail.get_tree_hash()

    #         # todo: sign offer here?
    #     finally:
    #         await network.close()