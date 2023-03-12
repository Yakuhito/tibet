import pytest
import pytest_asyncio

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_pk,
    calculate_synthetic_secret_key,
    DEFAULT_HIDDEN_PUZZLE_HASH,
)
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    launch_conditions_and_coinsol,
    SINGLETON_MOD_HASH,
    SINGLETON_MOD,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_LAUNCHER,
    lineage_proof_for_coinsol,
    puzzle_for_singleton,
    solution_for_singleton,
    generate_launcher_coin,
)
from cdv.test import setup as setup_test
from tibet_lib import *
from private_key_things import *
from clvm import SExp
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
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    launch_conditions_and_coinsol,
    SINGLETON_MOD_HASH,
    SINGLETON_MOD,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_LAUNCHER,
    lineage_proof_for_coinsol,
    puzzle_for_singleton,
    solution_for_singleton,
    generate_launcher_coin,
)
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_pk,
    calculate_synthetic_secret_key,
    DEFAULT_HIDDEN_PUZZLE_HASH,
    puzzle_for_synthetic_public_key,
    solution_for_delegated_puzzle,
)
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
from chia.wallet.util.wallet_types import WalletType

class TestTibetSwap:
    async def wait_for_wallet_sync(self, wallet_client):
        synced = await wallet_client.get_synced()
        while not synced:
            time.sleep(0.5)
            synced = await wallet_client.get_synced()
    

    async def wait_for_full_node_sync(self, full_node_client):
        blockchain_state = await full_node_client.get_blockchain_state()
        while not blockchain_state['sync']['synced']:
            time.sleep(0.5)
            blockchain_state = await full_node_client.get_blockchain_state()


    @pytest_asyncio.fixture(autouse=True)
    async def setup(self):
        alice_fingerprint = os.environ.get("ALICE_FINGERPRINT")
        bob_fingerprint = os.environ.get("BOB_FINGERPRINT")
        charlie_fingerprint = os.environ.get("CHARLIE_FINGERPRINT")

        chia_root = None
        if os.environ.get("GITHUB") == "yes":
            chia_root = "/home/runner/.chia/simulator/main"
        else:
            chia_root = os.path.expanduser("~/.chia/simulator/main")
        
        # Get full node client and reset simulator if there are any tx blocks
        full_node_client = await get_sim_full_node_client(chia_root)
        blockchain_state = await full_node_client.get_blockchain_state()
        peak = blockchain_state["peak"]
        if peak.height > 1: # also reset wallet
            os.system("chia stop wallet > /dev/null")
            os.system(f"rm -r {chia_root}/wallet")

            await full_node_client.revert_blocks(delete_all_blocks=True)

            os.system("chia start wallet -r > /dev/null")

            await self.wait_for_full_node_sync(full_node_client)
            
        # Get wallet client and give 2 XCH to each address
        wallet_client = None
        while wallet_client is None:
            try:
                wallet_client = await get_wallet_client(chia_root)
                await self.wait_for_wallet_sync(wallet_client)
            except:
               time.sleep(1)

        async def switch_to_fingerprint(wallet_client, fingerprint):
            await wallet_client.log_in(int(fingerprint))
            await self.wait_for_wallet_sync(wallet_client)

        async def switch_to_alice(wallet_client):
            await switch_to_fingerprint(wallet_client, alice_fingerprint)

        async def switch_to_bob(wallet_client):
            await switch_to_fingerprint(wallet_client, bob_fingerprint)

        async def switch_to_charlie(wallet_client):
            await switch_to_fingerprint(wallet_client, charlie_fingerprint)

        await switch_to_charlie(wallet_client)
        address = await wallet_client.get_next_address(1, True) # wallet id = 1, new address = true
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)
        
        await switch_to_bob(wallet_client)
        address = await wallet_client.get_next_address(1, True) # wallet id = 1, new address = true
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)
        
        await switch_to_alice(wallet_client)
        address = await wallet_client.get_next_address(1, True) # wallet id = 1, new address = true
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)
        
        await switch_to_alice(wallet_client)
        address = await wallet_client.get_next_address(1, True) # wallet id = 1, new address = true
        await full_node_client.farm_block(decode_puzzle_hash(address), number_of_blocks=1)
        
        await self.wait_for_wallet_sync(wallet_client)
        await self.wait_for_full_node_sync(full_node_client)

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


    def get_created_coins_from_coin_spend(self, cs):
        coins = []

        _, conditions_dict, __ = conditions_dict_for_solution(
            cs.puzzle_reveal,
            cs.solution,
            INFINITE_COST
        )

        for cwa in conditions_dict[ConditionOpcode.CREATE_COIN]:
            coins.append(Coin(
                cs.coin.name(),
                cwa.vars[0], # puzzle hash of created coin
                SExp.to(cwa.vars[1]).as_int()
            ))

        return coins


    async def select_standard_coin_and_puzzle(self, wallet_client, amount):
        spendable_coins = await wallet_client.get_spendable_coins(1, min_coin_amount=amount) # wallet id 1, amount amount
        
        coin_puzzle = None
        index = 0
        
        while coin_puzzle is None:
            coin = spendable_coins[0][index].coin
            coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)
            index += 1
       
        return coin, coin_puzzle


    async def launch_router(self, wallet_client, full_node_client):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, 2)

        launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle)

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        resp = await full_node_client.push_tx(signed_sb)

        assert resp["success"]
        await self.wait_for_full_node_sync(full_node_client)

        router_launch_coin_spend = None
        router_current_coin = None

        for cs in signed_sb.coin_spends:
            if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                router_launch_coin_spend = cs
                router_current_coin = self.get_created_coins_from_coin_spend(cs)[0]

        return bytes.fromhex(launcher_id), router_current_coin, router_launch_coin_spend


    async def create_test_cat(self, wallet_client, full_node_client, token_amount=1000000):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, token_amount)
        
        tail_hash, sb = await create_test_cat(token_amount, coin, coin_puzzle)

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        resp = await full_node_client.push_tx(signed_sb)

        assert resp["success"]
        await self.wait_for_full_node_sync(full_node_client)

        return bytes.fromhex(tail_hash)


    async def create_pair(
        self,
        wallet_client,
        full_node_client,
        router_launcher_id,
        tail_hash,
        current_router_coin,
        current_router_coin_creation_spend
    ):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, 2)

        pair_launcher_id, sb = await create_pair_from_coin(
            coin,
            coin_puzzle,
            tail_hash,
            router_launcher_id,
            current_router_coin,
            current_router_coin_creation_spend
        )

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        resp = await full_node_client.push_tx(signed_sb)

        assert resp["success"]
        await self.wait_for_full_node_sync(full_node_client)

        pair_coin = None
        pair_coin_creation_spend = None
        router_new_coin = None
        router_new_coin_creation_spend = None

        for cs in sb.coin_spends:
            if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                pair_coin_creation_spend = cs
                pair_coin = self.get_created_coins_from_coin_spend(cs)[0]
            elif cs.coin.amount == 1:
                possible_coins = self.get_created_coins_from_coin_spend(cs)
                if len(possible_coins) == 2 and possible_coins[0].amount + possible_coins[1].amount == 3:
                    router_new_coin_creation_spend = cs
                    for pc in possible_coins:
                        if pc.amount == 1:
                            router_new_coin = pc

        return bytes.fromhex(pair_launcher_id), pair_coin, pair_coin_creation_spend, router_new_coin, router_new_coin_creation_spend


    async def get_wallet_id_for_cat(self, wallet_client, tail_hash):
        wallets = await wallet_client.get_wallets(wallet_type = WalletType.CAT)
        wallet_id = next((_['id'] for _ in wallets if _['data'].startswith(tail_hash.hex())), None)

        if wallet_id is None:
            await wallet_client.create_wallet_for_existing_cat(tail_hash) # create wallet
            time.sleep(10) # I don't have any other solution, ok?!
            await self.wait_for_wallet_sync(wallet_client)
            return await self.get_wallet_id_for_cat(wallet_client, tail_hash)

        return int(wallet_id)
            

    async def get_balance(self, wallet_client, tail_hash_or_none = None):
        await self.wait_for_wallet_sync(wallet_client)

        wallet_id = 1 # XCH
        if tail_hash_or_none is not None:
            wallet_id = await self.get_wallet_id_for_cat(wallet_client, tail_hash_or_none)

        resp = await wallet_client.get_wallet_balance(wallet_id)
        return resp["spendable_balance"]


    @pytest.mark.asyncio
    async def test_router_launch(self, setup):
        full_node_client, wallet_client, switch_to_alice, switch_to_bob, switch_to_charlie = setup
        try:
            launcher_id, _, __ = await self.launch_router(wallet_client, full_node_client)

            cr = await full_node_client.get_coin_record_by_name(launcher_id)
            assert cr is not None
            assert cr.spent
        finally:
            full_node_client.close()
            wallet_client.close()
            await full_node_client.await_closed()
            await wallet_client.await_closed()


    @pytest.mark.asyncio
    async def test_pair_creation(self, setup):
        full_node_client, wallet_client, switch_to_alice, switch_to_bob, switch_to_charlie = setup
        try:
            router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
                wallet_client, full_node_client
            )
            
            tail_hash = await self.create_test_cat(wallet_client, full_node_client)

            pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
                wallet_client,
                full_node_client,
                router_launcher_id,
                tail_hash,
                current_router_coin,
                router_creation_spend
            )
            cr = await full_node_client.get_coin_record_by_name(pair_launcher_id)
            assert cr is not None
            assert cr.spent

            # another pair, just to be sure
            tail_hash2 = await self.create_test_cat(wallet_client, full_node_client)

            pair2_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
                wallet_client,
                full_node_client,
                router_launcher_id,
                tail_hash2,
                current_router_coin,
                router_creation_spend
            )
            cr = await full_node_client.get_coin_record_by_name(pair2_launcher_id)
            assert cr is not None
            assert cr.spent
        finally:
            full_node_client.close()
            wallet_client.close()
            await full_node_client.await_closed()
            await wallet_client.await_closed()


    @pytest.mark.asyncio
    async def test_pair_operations(self, setup):
        full_node_client, wallet_client, switch_to_alice, switch_to_bob, switch_to_charlie = setup
        try:
            router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
                wallet_client, full_node_client
            )
            
            token_amount = 1000000 # in CATs, not mojos
            token_tail_hash = await self.create_test_cat(wallet_client, full_node_client, token_amount=token_amount)
            
            pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
                wallet_client,
                full_node_client,
                router_launcher_id,
                token_tail_hash,
                current_router_coin,
                router_creation_spend
            )
            
            pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(pair_launcher_id).get_tree_hash()
            
            assert (await self.get_balance(wallet_client, token_tail_hash)) == 1000 * 1000000 # it's in mojos
            assert (await self.get_balance(wallet_client, pair_liquidity_tail_hash)) == 0

            # 1. Deposit liquidity: 1000 CAT mojos and 10000 mojos
            token_wallet_id = self.get_wallet_id_for_cat(wallet_client, token_tail_hash)
            liquidity_wallet_id = self.get_wallet_id_for_cat(wallet_client, pair_liquidity_tail_hash)

            xch_amount = 10000
            token_amount = 1000
            liquidity_token_amount = token_amount # initial deposit

            offer_dict = {}
            offer_dict[1] = - xch_amount - liquidity_token_amount # also for liqiudity TAIL creation
            offer_dict[token_wallet_id] = -token_amount
            offer_dict[liquidity_wallet_id] = liquidity_token_amount
            offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
            offer = offer_resp[0]
            offer_str = offer.to_bech32()

            # get pair state, even though it's 0 - we need to test teh func-tion!
            current_pair_coin, pair_creation_spend, pair_state = await sync_pair(
                full_node_client, current_pair_coin.name(), token_tail_hash
            )
            assert pair_state["liquidity"] == 0
            assert pair_state["xch_reserve"] == 0
            assert pair_state["token_reserve"] == 0

            # there are no reserves at this point, but the function should be tested nonetheless
            xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
                full_node_client,
                pair_launcher_id,
                current_pair_coin,
                token_tail_hash,
                pair_creation_spend
            )

            sb = await respond_to_deposit_liquidity_offer(
                pair_launcher_id,
                current_pair_coin,
                pair_creation_spend,
                token_tail_hash,
                pair_state["liquidity"],
                pair_state["xch_reserve"],
                pair_state["token_reserve"],
                offer_str,
                xch_reserve_coin,
                token_reserve_coin,
                token_reserve_lineage_proof
            )

            resp = await full_node_client.push_tx(signed_sb)

            assert resp["success"]
            await self.wait_for_full_node_sync(full_node_client)

            print(await self.get_balance(wallet_client))
            print(await self.get_balance(wallet_client, token_tail_hash))
            print(await self.get_balance(wallet_client, pair_liquidity_tail_hash))

        finally:
            full_node_client.close()
            wallet_client.close()
            await full_node_client.await_closed()
            await wallet_client.await_closed()
