import os
import sys

import pytest
import pytest_asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from pathlib import Path
from typing import List

from chia_rs import AugSchemeMPL, PrivateKey, Coin, SpendBundle
from cdv_replacement import get_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.simulator.block_tools import test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.full_node.full_node_rpc_client import FullNodeRpcClient
from chia.wallet.wallet_rpc_client import WalletRpcClient
from chia.simulator.simulator_full_node_rpc_client import \
    SimulatorFullNodeRpcClient
from chia.types.blockchain_format.program import (INFINITE_COST, Program)
from chia._tests.cmds.cmd_test_utils import TestWalletRpcClient
from chia_rs.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.bech32m import (decode_puzzle_hash, encode_puzzle_hash)
from chia.consensus.condition_tools import conditions_dict_for_solution
from chia.util.config import load_config
from chia.util.hash import std_hash
from chia_rs.sized_ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    get_innerpuzzle_from_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, CAT_MOD_HASH
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    puzzle_for_synthetic_public_key,
    solution_for_delegated_puzzle,
)
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    generate_launcher_coin,
    launch_conditions_and_coinsol,
    lineage_proof_for_coinsol,
    puzzle_for_singleton,
    solution_for_singleton,
)
from chia.wallet.puzzles.tails import GenesisById
from chia.wallet.trading.offer import OFFER_MOD, OFFER_MOD_HASH, Offer
from chia.wallet.util.puzzle_compression import (
    compress_object_with_puzzles,
    decompress_object_with_puzzles,
    lowest_best_version,
)
from chia.wallet.util.wallet_types import WalletType
from chia_rs import run_chia_program
from clvm.casts import int_to_bytes
# from chia.simulator.setup_nodes import setup_simulators_and_wallets
from chia._tests.util.setup_nodes import setup_simulators_and_wallets
from chia.types.peer_info import PeerInfo
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.wallet.wallet_rpc_api import WalletRpcApi
from chia.simulator.simulator_full_node_rpc_api import SimulatorFullNodeRpcApi
from chia.rpc.rpc_server import start_rpc_server

from clvm import SExp
from private_key_things import *
from tibet_lib import *
from secrets import token_bytes


class TestTibetSwap:
    async def wait_for_wallet_sync(self, wallet_client):
        sync_resp = await wallet_client.get_sync_status()
        while not sync_resp.synced:
            time.sleep(0.5)
            sync_resp = await wallet_client.get_sync_status()

    @pytest_asyncio.fixture(scope="function")
    async def node_and_wallets(self):
        async with setup_simulators_and_wallets(1, 2, test_constants) as sims:
            yield sims
    
    @pytest_asyncio.fixture(scope="function")
    async def setup(self, node_and_wallets):
        # this was done using the old fixture first, and then adapted with the help of:
        # https://github.com/Chia-Network/chia-blockchain/blob/ebf8105fc12c351888069ba399be6cf998f680e0/chia/_tests/conftest.py#L118
        full_nodes = [node_and_wallets.simulators[0].peer_api]
        wallets = node_and_wallets.wallets
        bt = node_and_wallets.bt
        assert len(wallets) == 2
    
        full_node_api: FullNodeSimulator = full_nodes[0]
        full_node_server = full_node_api.server

        wallet_node_makers = []
        servers = []
        wallet_makers = []
        api_makers = []
        for wallet_env in wallets:
            wallet_node_maker = wallet_env.node
            server = wallet_env.peer_server
            wallet_node_makers.append(wallet_node_maker)
            servers.append(server)

            wallet_maker: Wallet = wallet_node_maker.wallet_state_manager.main_wallet
            wallet_makers.append(wallet_maker)
        
            wallet_master_sk = wallet_node_maker.wallet_state_manager.get_master_private_key()
            ph_maker = WalletTool(bt.constants, wallet_master_sk).get_new_puzzlehash()
            
            wallet_node_maker.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }

            await server.start_client(PeerInfo("127.0.0.1", uint16(full_node_server._port)), None)

            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_maker))

            api_makers.append(WalletRpcApi(wallet_node_maker))

        config = bt.config
        daemon_port = config["daemon_port"]
        self_hostname = config["self_hostname"]
        def stop_node_cb() -> None:
            pass

        full_node_rpc_api = SimulatorFullNodeRpcApi(full_node_api.full_node)

        rpc_server_node = await start_rpc_server(
            full_node_rpc_api,
            self_hostname,
            daemon_port,
            uint16(0),
            stop_node_cb,
            bt.root_path,
            config,
            config['full_node'],
            connect_to_daemon=False,
        )

        rpc_server_makers = []
        client_makers = []
        for api_maker in api_makers:
            rpc_server_maker = await start_rpc_server(
                api_maker,
                self_hostname,
                daemon_port,
                uint16(0),
                lambda x: None,  # type: ignore
                bt.root_path,
                config,
                config['wallet'],
                connect_to_daemon=False,
            )
            rpc_server_makers.append(rpc_server_maker)

            client_maker: WalletRpcClient = await WalletRpcClient.create(
                self_hostname, rpc_server_maker.listen_port, bt.root_path, config
            )
            client_makers.append(client_maker)

        client_node: SimulatorFullNodeRpcClient = await SimulatorFullNodeRpcClient.create(
            self_hostname, rpc_server_node.listen_port, bt.root_path, config
        )
        await client_node.set_auto_farming(True)

        for client_maker in client_makers:
            await self.wait_for_wallet_sync(client_maker)

        yield client_node, client_makers[0], client_makers[1]

        for client_maker in client_makers:
            client_maker.close()
        client_node.close()
        for rpc_server_maker in rpc_server_makers:
            rpc_server_maker.close()
        rpc_server_node.close()
        for client_maker in client_makers:
            await client_maker.await_closed()
        await client_node.await_closed()
        for rpc_server_maker in rpc_server_makers:
            await rpc_server_maker.await_closed()
        await rpc_server_node.await_closed()


    @pytest.mark.asyncio
    async def test_healthz(self, setup):
        full_node_client, wallet_client, bob_wallet_client = setup
        
        full_node_resp = await full_node_client.healthz()
        assert full_node_resp['success']

        wallet_resp = await wallet_client.healthz()
        assert wallet_resp['success']

        wallet_resp = await bob_wallet_client.healthz()
        assert wallet_resp['success']


    def get_created_coins_from_coin_spend(self, cs):
        coins = []

        conditions_dict = conditions_dict_for_solution(
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
        
        retries = 0
        while coin_puzzle is None:
            try:
                coin = spendable_coins[0][index].coin
                coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)
                index += 1
            except:
                spendable_coins = await wallet_client.get_spendable_coins(1, min_coin_amount=amount) # wallet id 1, amount amount
                index = 0
                retries += 1
                if retries > 3:
                    print("ok, won't find a coin any time soon :(")
                    spendable_coins[0][31337][":("]
                else:
                    time.sleep(2)

        return coin, coin_puzzle


    async def launch_router(self, wallet_client, full_node_client):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, 2)

        launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle)

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        resp = await full_node_client.push_tx(signed_sb)

        assert resp["success"]

        router_launch_coin_spend = None
        router_current_coin = None

        for cs in signed_sb.coin_spends:
            if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                router_launch_coin_spend = cs
                router_current_coin = self.get_created_coins_from_coin_spend(cs)[0]

        return bytes.fromhex(launcher_id), router_current_coin, router_launch_coin_spend


    async def create_test_cat(self, wallet_client: WalletRpcClient, full_node_client, token_amount=1000000):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, token_amount)
        
        tail_hash, sb = await create_test_cat(token_amount, coin, coin_puzzle)

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        resp = await full_node_client.push_tx(signed_sb)

        assert resp["success"]

        await wallet_client.create_wallet_for_existing_cat(bytes.fromhex(tail_hash)) # create wallet

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
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, ROUTER_MIN_FEE + 2)

        pair_launcher_id, sbm, _a, _b = await create_pair_from_coin(
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

            while wallet_id is None:
                time.sleep(0.5) # I don't have any other solution, ok?!

                wallets = await wallet_client.get_wallets(wallet_type = WalletType.CAT)
                wallet_id = next((_['id'] for _ in wallets if _['data'].startswith(tail_hash.hex())), None)

            await self.wait_for_wallet_sync(wallet_client)
            return wallet_id

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
        full_node_client, wallet_client, bob_wallet_client = setup
        
        launcher_id, _, __ = await self.launch_router(wallet_client, full_node_client)

        cr = await full_node_client.get_coin_record_by_name(launcher_id)
        assert cr is not None
        assert cr.spent


    @pytest.mark.asyncio
    async def test_pair_creation(self, setup):
        full_node_client, wallet_client, bob_wallet_client = setup
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
        tail_hash2 = await self.create_test_cat(bob_wallet_client, full_node_client)

        pair2_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            bob_wallet_client,
            full_node_client,
            router_launcher_id,
            tail_hash2,
            current_router_coin,
            router_creation_spend
        )
        cr = await full_node_client.get_coin_record_by_name(pair2_launcher_id)
        assert cr is not None
        assert cr.spent


    async def expect_change_in_token(
        self,
        wallet_client,
        token_tail_hash,
        initial_amount,
        delta,
        max_retries = 120,
        time_to_sleep = 1
    ):
        retries = 0
        balance = await self.get_balance(wallet_client, token_tail_hash)
        while balance == initial_amount:
            print("balance", balance, "initial_amount", initial_amount, "delta", delta)

            retries += 1
            assert retries <= max_retries

            time.sleep(1)
            balance = await self.get_balance(wallet_client, token_tail_hash)

        assert balance - initial_amount == delta

        return balance


    @pytest.mark.asyncio
    async def test_pair_operations(self, setup):
        full_node_client, wallet_client, bob_wallet_client = setup
        router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
            wallet_client, full_node_client
        )
            
        token_total_supply = 1000000 * 1000 # in mojos
        token_tail_hash = await self.create_test_cat(
            wallet_client, full_node_client, token_amount=token_total_supply // 1000
        )
        await self.wait_for_wallet_sync(wallet_client)
            
        pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            token_tail_hash,
            current_router_coin,
            router_creation_spend
        )
            
        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(pair_launcher_id).get_tree_hash()
        
        await self.wait_for_wallet_sync(wallet_client)
        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, 0, token_total_supply)
        assert (await self.get_balance(wallet_client, pair_liquidity_tail_hash)) == 0

        xch_balance_before_all_ops = xch_balance_before = await self.get_balance(wallet_client)

        # 1. Deposit liquidity: 1000 CAT mojos and 100000000 mojos
        # python3 tibet.py deposit-liquidity --xch-amount 100000000 --token-amount 1000 --asset-id [asset_id] --push-tx
        token_wallet_id = await self.get_wallet_id_for_cat(wallet_client, token_tail_hash)
        liquidity_wallet_id = await self.get_wallet_id_for_cat(wallet_client, pair_liquidity_tail_hash)

        xch_amount = 100000000
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
        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
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
            pair_creation_spend,
            sb_to_aggregate
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

        resp = await full_node_client.push_tx(sb)

        assert resp["success"]

        await self.wait_for_wallet_sync(wallet_client)
        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_total_supply, -token_amount)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, 0, liquidity_token_amount)

        # 2. Deposit moar liquidity (worth 4000 tokens, so 4000 token mojos and 100000000 mojos)
        # python3 tibet.py deposit-liquidity --token-amount 4000 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_token_amount

        xch_amount = 400000000
        token_amount = 4000
        liquidity_token_amount = 4000 # 1:1

        offer_dict = {}
        offer_dict[1] = - xch_amount - liquidity_token_amount # also for liqiudity TAIL creation
        offer_dict[token_wallet_id] = -token_amount
        offer_dict[liquidity_wallet_id] = liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 1000
        assert pair_state["xch_reserve"] == 100000000
        assert pair_state["token_reserve"] == 1000

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
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

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, -token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, liquidity_balance_before, liquidity_token_amount)

        # 3. Withdraw 800 liquidity tokens
        # python3 tibet.py remove-liquidity --liquidity-token-amount 800 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_balance_now

        xch_amount = 80000000
        token_amount = 800
        liquidity_token_amount = 800 # 1:1

        offer_dict = {}
        offer_dict[1] = xch_amount + liquidity_token_amount # also ask for xch from liquidity cat burn
        offer_dict[token_wallet_id] = token_amount
        offer_dict[liquidity_wallet_id] = -liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 5000
        assert pair_state["xch_reserve"] == 500000000
        assert pair_state["token_reserve"] == 5000

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_remove_liquidity_offer(
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

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, liquidity_balance_before, -liquidity_token_amount)

        # 4. Change 100000000 XCH to tokens
        # python3 tibet.py xch-to-token --xch-amount 100000000 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_balance_now

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 4200
        assert pair_state["xch_reserve"] == 420000000
        assert pair_state["token_reserve"] == 4200

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        xch_amount = 100000000
        token_amount = pair_state["token_reserve"] * xch_amount * 993 // (1000 * pair_state["xch_reserve"] + 993 * xch_amount)

        offer_dict = {}
        offer_dict[1] = -xch_amount # offer XCH
        offer_dict[token_wallet_id] = token_amount # ask for token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        sb = await respond_to_swap_offer(
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

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, token_amount)
        
        liquidity_balance_now = await self.get_balance(wallet_client, pair_liquidity_tail_hash)
        assert liquidity_balance_before == liquidity_balance_now

        # 5. Change 1000 tokens to XCH
        # python3 tibet.py token-to-xch --token-amount 1000 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_balance_now

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 4200
        assert pair_state["xch_reserve"] == 420000000 + xch_amount
        assert pair_state["token_reserve"] == 4200 - token_amount

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        token_amount = 1000
        xch_amount = pair_state["xch_reserve"] * token_amount * 993 // (1000 * pair_state["token_reserve"] + 993 * token_amount)

        offer_dict = {}
        offer_dict[1] = xch_amount # ask for XCH
        offer_dict[token_wallet_id] = -token_amount # offer token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        sb = await respond_to_swap_offer(
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

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, -token_amount)

        # 6. Remove remaining liquidity and call it a day
        # python3 tibet.py remove-liquidity --liquidity-token-amount 4200 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_balance_now
        
        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 4200

        xch_amount = pair_state["xch_reserve"]
        token_amount = pair_state["token_reserve"]
        liquidity_token_amount = pair_state["liquidity"]

        offer_dict = {}
        offer_dict[1] = xch_amount + liquidity_token_amount # also ask for xch from liquidity cat burn
        offer_dict[token_wallet_id] = token_amount
        offer_dict[liquidity_wallet_id] = -liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_remove_liquidity_offer(
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

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now == xch_balance_before_all_ops

        await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, token_total_supply - token_balance_before)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, liquidity_balance_before, -liquidity_balance_before)

    @pytest.mark.asyncio
    async def test_donations(self, setup):
        full_node_client, wallet_client, bob_wallet_client = setup
        router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
            wallet_client, full_node_client
        )
            
        token_total_supply = 1000000 * 1000 # in mojos
        token_tail_hash = await self.create_test_cat(
            wallet_client, full_node_client, token_amount=token_total_supply // 1000
        )
        await self.wait_for_wallet_sync(wallet_client)
            
        pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            token_tail_hash,
            current_router_coin,
            router_creation_spend
        )
            
        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(pair_launcher_id).get_tree_hash()
        
        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, 0, token_total_supply)
        assert (await self.get_balance(wallet_client, pair_liquidity_tail_hash)) == 0

        xch_balance_before_all_ops = xch_balance_before = await self.get_balance(wallet_client)

        # 1. Deposit liquidity: 1000 CAT mojos and 100000000 mojos
        # python3 tibet.py deposit-liquidity --xch-amount 100000000 --token-amount 1000 --asset-id [asset_id] --push-tx
        token_wallet_id = await self.get_wallet_id_for_cat(wallet_client, token_tail_hash)
        liquidity_wallet_id = await self.get_wallet_id_for_cat(wallet_client, pair_liquidity_tail_hash)

        xch_amount = 100000000
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
        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
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
            pair_creation_spend,
            sb_to_aggregate
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

        resp = await full_node_client.push_tx(sb)

        assert resp["success"]

        await self.wait_for_wallet_sync(wallet_client)
        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_total_supply, -token_amount)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, 0, liquidity_token_amount)

        # Change 100000000 XCH to tokens
        # BUT leave 10000 mojos as a tip
        # != python3 tibet.py xch-to-token --xch-amount 100000000 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["xch_reserve"] == 100000000
        assert pair_state["token_reserve"] == 1000
        assert pair_state["liquidity"] == 1000

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        xch_amount = 100000000
        xch_donation_amount = 10000
        token_amount = pair_state["token_reserve"] * xch_amount * 993 // (1000 * pair_state["xch_reserve"] + 993 * xch_amount)

        offer_dict = {}
        offer_dict[1] = -(xch_amount + xch_donation_amount) # offer XCH
        offer_dict[token_wallet_id] = token_amount # ask for token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        first_donation_ph = b"\xd1" * 32
        second_donation_ph = b"\xd2" * 32
        first_donation_address = encode_puzzle_hash(first_donation_ph, "xch")
        second_donation_address = encode_puzzle_hash(second_donation_ph, "xch")
        sb = await respond_to_swap_offer(
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
            token_reserve_lineage_proof,
            total_donation_amount=xch_donation_amount,
            donation_addresses=[first_donation_address, second_donation_address],
            donation_weights=[2, 1]
        )

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + xch_donation_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, token_amount)

        first_donation_address_coins = await full_node_client.get_coin_records_by_puzzle_hash(first_donation_ph)
        assert len(first_donation_address_coins) == 1
        assert first_donation_address_coins[0].coin.amount == xch_donation_amount // 3 * 2 + 1 # 6667

        second_donation_address_coins = await full_node_client.get_coin_records_by_puzzle_hash(second_donation_ph)
        assert len(second_donation_address_coins) == 1
        assert second_donation_address_coins[0].coin.amount == xch_donation_amount // 3

        # test donations for token -> XCH swaps

        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["xch_reserve"] == 200000000
        assert pair_state["token_reserve"] == 502
        assert pair_state["liquidity"] == 1000

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        token_amount = 1000
        xch_donation_amount = 100000
        xch_amount = pair_state["xch_reserve"] * token_amount * 993 // (1000 * pair_state["token_reserve"] + 993 * token_amount) - xch_donation_amount

        offer_dict = {}
        offer_dict[1] = xch_amount - xch_donation_amount # ask for XCH
        offer_dict[token_wallet_id] = - token_amount # offer token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict)
        offer = offer_resp[0]
        offer_str = offer.to_bech32()

        third_donation_ph = b"\xd3" * 32
        third_donation_address = encode_puzzle_hash(third_donation_ph, "xch")
        sb = await respond_to_swap_offer(
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
            token_reserve_lineage_proof,
            total_donation_amount=xch_donation_amount,
            donation_addresses=[third_donation_address],
            donation_weights=[1]
        )

        resp = await full_node_client.push_tx(sb)
        await self.wait_for_wallet_sync(wallet_client)

        assert resp["success"]

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount - xch_donation_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, token_balance_before, -token_amount)

        third_donation_address_coins = await full_node_client.get_coin_records_by_puzzle_hash(third_donation_ph)
        assert len(third_donation_address_coins) == 1
        assert third_donation_address_coins[0].coin.amount == xch_donation_amount
