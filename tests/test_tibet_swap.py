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
from chia.wallet.util.tx_config import CoinSelectionConfig
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
from chia.wallet.util.tx_config import TXConfig

tx_config = TXConfig(
    min_coin_amount=1,
    max_coin_amount=1337 * 10 ** 15,
    excluded_coin_amounts=[],
    excluded_coin_ids=[],
    reuse_puzhash=True
)

class TestTibetSwap:
    async def wait_for_wallet_sync(self, wallet_client):
        sync_resp = await wallet_client.get_sync_status()
        while not sync_resp.synced or sync_resp.syncing or not sync_resp.genesis_initialized:
            time.sleep(0.5)
            sync_resp = await wallet_client.get_sync_status()

    @pytest_asyncio.fixture(scope="function")
    async def node_and_wallets(self):
        async with setup_simulators_and_wallets(1, 1, test_constants) as sims:
            yield sims
    
    @pytest_asyncio.fixture(scope="function")
    async def setup(self, node_and_wallets):
        # this was done using the old fixture first, and then adapted with the help of:
        # https://github.com/Chia-Network/chia-blockchain/blob/ebf8105fc12c351888069ba399be6cf998f680e0/chia/_tests/conftest.py#L118
        full_nodes = [node_and_wallets.simulators[0].peer_api]
        wallets = node_and_wallets.wallets
        bt = node_and_wallets.bt
        assert len(wallets) == 1
    
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
                config['full_node'],
                connect_to_daemon=False,
            )
            rpc_server_makers.append(rpc_server_maker)

            client_maker: WalletRpcClient = await WalletRpcClient.create(
                self_hostname, rpc_server_maker.listen_port, bt.root_path, config
            )
            await client_maker.get_next_address(1, True)
            client_makers.append(client_maker)

        client_node: SimulatorFullNodeRpcClient = await SimulatorFullNodeRpcClient.create(
            self_hostname, rpc_server_node.listen_port, bt.root_path, config
        )
        await client_node.set_auto_farming(True)

        for client_maker in client_makers:
            await self.wait_for_wallet_sync(client_maker)

        yield client_node, client_makers[0]

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
        full_node_client, wallet_client = setup
        
        full_node_resp = await full_node_client.healthz()
        assert full_node_resp['success']

        wallet_resp = await wallet_client.healthz()
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
        coin_selection_config = CoinSelectionConfig(
            min_coin_amount=amount - 1,
            max_coin_amount=uint64.MAXIMUM,
            excluded_coin_amounts=[amount - 1],
            excluded_coin_ids=[]
        )
        await self.wait_for_wallet_sync(wallet_client)
        spendable_coins = await wallet_client.get_spendable_coins(1, coin_selection_config) # wallet id 1
        
        coin_puzzle = None
        index = 0
        
        retries = 0
        while coin_puzzle is None:
            try:
                coin = spendable_coins[0][index].coin
                await self.wait_for_wallet_sync(wallet_client)
                coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)
                index += 1
            except:
                await self.wait_for_wallet_sync(wallet_client)
                spendable_coins = await wallet_client.get_spendable_coins(1, coin_selection_config) # wallet id 1
                index = 0
                retries += 1
                if retries > 3:
                    print("ok, won't find a coin any time soon :(")
                    spendable_coins[0][31337][":("]
                else:
                    time.sleep(4)

        return coin, coin_puzzle


    async def launch_router(self, wallet_client, full_node_client, rcat):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, 2)

        launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle, rcat)

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        assert((await full_node_client.push_tx(signed_sb))["success"])

        router_launch_coin_spend = None
        router_current_coin = None

        for cs in signed_sb.coin_spends:
            if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                router_launch_coin_spend = cs
                router_current_coin = self.get_created_coins_from_coin_spend(cs)[0]

        return bytes.fromhex(launcher_id), router_current_coin, router_launch_coin_spend


    async def create_test_cat_with_clients(
        self,
        wallet_client: WalletRpcClient,
        full_node_client,
        hidden_puzzle_hash,
        token_amount=1000000
    ):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, token_amount)
        
        tail_hash, sb = await create_test_cat(hidden_puzzle_hash, token_amount, coin, coin_puzzle)

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        assert((await full_node_client.push_tx(signed_sb))["success"])

        # create wallet
        # Note: Existing CAT wallets that receive rCATs as their first coin are automatically
        #  converted to rCAT wallets by the wallet state manager.
        await wallet_client.create_wallet_for_existing_cat(bytes.fromhex(tail_hash))

        return bytes.fromhex(tail_hash)


    async def create_pair(
        self,
        wallet_client,
        full_node_client,
        router_launcher_id,
        tail_hash,
        hidden_puzzle_hash,
        inverse_fee,
        current_router_coin,
        current_router_coin_creation_spend
    ):
        coin, coin_puzzle = await self.select_standard_coin_and_puzzle(wallet_client, ROUTER_MIN_FEE + 2)

        pair_launcher_id, sb, _a, _b = await create_pair_from_coin(
            coin,
            coin_puzzle,
            tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            router_launcher_id,
            current_router_coin,
            current_router_coin_creation_spend
        )

        signed_sb = await sign_spend_bundle(wallet_client, sb)
        assert((await full_node_client.push_tx(signed_sb))["success"])

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


    async def get_wallet_id_for_cat(self, wallet_client, tail_hash, rcat):
        wallet_type = WalletType.CAT if not rcat else WalletType.RCAT
        wallets = await wallet_client.get_wallets(wallet_type=wallet_type)
        wallet_id = next((_['id'] for _ in wallets if _['data'].startswith(tail_hash.hex())), None)

        if wallet_id is None:
            await wallet_client.create_wallet_for_existing_cat(tail_hash) # create wallet

            while wallet_id is None:
                time.sleep(0.5) # I don't have any other solution, ok?!

                wallets = await wallet_client.get_wallets(wallet_type=wallet_type)
                wallet_id = next((_['id'] for _ in wallets if _['data'].startswith(tail_hash.hex())), None)

            await self.wait_for_wallet_sync(wallet_client)
            return wallet_id

        return int(wallet_id)
            

    async def get_balance(self, wallet_client, tail_hash_or_none = None, rcat_if_cat = False):
        await self.wait_for_wallet_sync(wallet_client)

        wallet_id = 1 # XCH
        if tail_hash_or_none is not None:
            wallet_id = await self.get_wallet_id_for_cat(wallet_client, tail_hash_or_none, rcat_if_cat)

        resp = await wallet_client.get_wallet_balance(wallet_id)
        return resp["spendable_balance"]


    @pytest.mark.parametrize(
        "hidden_puzzle_hash",
        [None, bytes32(b"\x00" * 32)],
        ids=["CAT", "rCAT"]
    )
    @pytest.mark.asyncio
    async def test_router_launch(self, setup, hidden_puzzle_hash):
        full_node_client, wallet_client = setup
        
        launcher_id, _, __ = await self.launch_router(wallet_client, full_node_client, hidden_puzzle_hash is not None)

        cr = await full_node_client.get_coin_record_by_name(launcher_id)
        assert cr is not None
        assert cr.spent


    @pytest.mark.parametrize(
        "hidden_puzzle_hash",
        [None, bytes32(b"\x00" * 32)],
        ids=["CAT", "rCAT"]
    )
    @pytest.mark.asyncio
    async def test_pair_creation(self, setup, hidden_puzzle_hash):
        full_node_client, wallet_client = setup
        router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
            wallet_client, full_node_client, hidden_puzzle_hash is not None
        )
            
        tail_hash = await self.create_test_cat_with_clients(wallet_client, full_node_client, hidden_puzzle_hash)

        pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            tail_hash,
            hidden_puzzle_hash,
            993 if hidden_puzzle_hash is None else 999,
            current_router_coin,
            router_creation_spend
        )
        cr = await full_node_client.get_coin_record_by_name(pair_launcher_id)
        assert cr is not None
        assert cr.spent

        # another pair, just to be sure
        tail_hash2 = await self.create_test_cat_with_clients(wallet_client, full_node_client, hidden_puzzle_hash)

        pair2_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            tail_hash2,
            hidden_puzzle_hash,
            993 if hidden_puzzle_hash is None else 998,
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
        hidden_puzzle_hash,
        initial_amount,
        delta,
        max_retries = 120,
        time_to_sleep = 1
    ):
        retries = 0
        balance = await self.get_balance(wallet_client, token_tail_hash, hidden_puzzle_hash is not None)
        while balance - initial_amount != delta:
            print("balance", balance, "initial_amount", initial_amount, "delta", delta)

            retries += 1
            assert retries <= max_retries

            time.sleep(1)
            balance = await self.get_balance(wallet_client, token_tail_hash, hidden_puzzle_hash is not None)

        assert balance - initial_amount == delta

        return balance


    @pytest.mark.parametrize(
        "hidden_puzzle_hash",
        [None, bytes32(b"\x00" * 32)],
        ids=["CAT", "rCAT"]
    )
    @pytest.mark.asyncio
    async def test_pair_operations(self, setup, hidden_puzzle_hash):
        full_node_client, wallet_client = setup
        router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
            wallet_client, full_node_client, hidden_puzzle_hash is not None
        )
            
        token_total_supply = 1000000 * 1000 # in mojos
        token_tail_hash = await self.create_test_cat_with_clients(
            wallet_client,
            full_node_client,
            hidden_puzzle_hash,
            token_amount=token_total_supply // 1000
        )
        await self.wait_for_wallet_sync(wallet_client)
        
        inverse_fee = 993 if hidden_puzzle_hash is None else 999
        pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            current_router_coin,
            router_creation_spend
        )
            
        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(pair_launcher_id).get_tree_hash()
        
        await self.wait_for_wallet_sync(wallet_client)
        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, 0, token_total_supply)
        assert (await self.get_balance(wallet_client, pair_liquidity_tail_hash, None)) == 0

        xch_balance_before_all_ops = xch_balance_before = await self.get_balance(wallet_client)

        # 1. Deposit liquidity: 1000 CAT mojos and 100000000 mojos
        # python3 tibet.py deposit-liquidity --xch-amount 100000000 --token-amount 1000 --asset-id [asset_id] --push-tx
        token_wallet_id = await self.get_wallet_id_for_cat(wallet_client, token_tail_hash, hidden_puzzle_hash is not None)
        liquidity_wallet_id = await self.get_wallet_id_for_cat(wallet_client, pair_liquidity_tail_hash, False)

        xch_amount = 100000000
        token_amount = 1000
        liquidity_token_amount = token_amount # initial deposit

        offer_dict = {}
        offer_dict[1] = - xch_amount - liquidity_token_amount # also for liqiudity TAIL creation
        offer_dict[token_wallet_id] = -token_amount
        offer_dict[liquidity_wallet_id] = liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_deposit_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_total_supply, -token_amount)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, 0, liquidity_token_amount)

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
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_deposit_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, -token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, liquidity_balance_before, liquidity_token_amount)

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
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_remove_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, liquidity_balance_before, -liquidity_token_amount)

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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        xch_amount = 100000000
        token_amount = pair_state["token_reserve"] * xch_amount * inverse_fee // (1000 * pair_state["xch_reserve"] + inverse_fee * xch_amount)

        offer_dict = {}
        offer_dict[1] = -xch_amount # offer XCH
        offer_dict[token_wallet_id] = token_amount # ask for token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
        offer_str = offer.to_bech32()

        sb = await respond_to_swap_offer(
           pair_launcher_id,
           current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, token_amount)
        
        liquidity_balance_now = await self.get_balance(wallet_client, pair_liquidity_tail_hash, None)
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        token_amount = 1000
        xch_amount = pair_state["xch_reserve"] * token_amount * inverse_fee // (1000 * pair_state["token_reserve"] + inverse_fee * token_amount)

        offer_dict = {}
        offer_dict[1] = xch_amount # ask for XCH
        offer_dict[token_wallet_id] = -token_amount # offer token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
        offer_str = offer.to_bech32()

        sb = await respond_to_swap_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, -token_amount)

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
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
        offer_str = offer.to_bech32()

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_remove_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now == xch_balance_before_all_ops

        await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, token_total_supply - token_balance_before)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, liquidity_balance_before, -liquidity_balance_before)

    @pytest.mark.parametrize(
        "hidden_puzzle_hash",
        [None, bytes32(b"\x00" * 32)],
        ids=["CAT", "rCAT"]
    )
    @pytest.mark.asyncio
    async def test_donations(self, setup, hidden_puzzle_hash):
        full_node_client, wallet_client = setup
        router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
            wallet_client, full_node_client, hidden_puzzle_hash is not None
        )
            
        token_total_supply = 1000000 * 1000 # in mojos
        token_tail_hash = await self.create_test_cat_with_clients(
            wallet_client,
            full_node_client,
            hidden_puzzle_hash,
            token_amount=token_total_supply // 1000
        )
        await self.wait_for_wallet_sync(wallet_client)
            
        inverse_fee = 993 if hidden_puzzle_hash is None else 999
        pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            current_router_coin,
            router_creation_spend
        )
            
        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(pair_launcher_id).get_tree_hash()
        
        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, 0, token_total_supply)
        assert (await self.get_balance(wallet_client, pair_liquidity_tail_hash, None)) == 0

        xch_balance_before_all_ops = xch_balance_before = await self.get_balance(wallet_client)

        # 1. Deposit liquidity: 1000 CAT mojos and 100000000 mojos
        # python3 tibet.py deposit-liquidity --xch-amount 100000000 --token-amount 1000 --asset-id [asset_id] --push-tx
        token_wallet_id = await self.get_wallet_id_for_cat(wallet_client, token_tail_hash, hidden_puzzle_hash is not None)
        liquidity_wallet_id = await self.get_wallet_id_for_cat(wallet_client, pair_liquidity_tail_hash, False)

        xch_amount = 100000000
        token_amount = 1000
        liquidity_token_amount = token_amount # initial deposit

        offer_dict = {}
        offer_dict[1] = - xch_amount - liquidity_token_amount # also for liqiudity TAIL creation
        offer_dict[token_wallet_id] = -token_amount
        offer_dict[liquidity_wallet_id] = liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_deposit_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])

        await self.wait_for_wallet_sync(wallet_client)
        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_total_supply, -token_amount)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, 0, liquidity_token_amount)

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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        xch_amount = 100000000
        xch_donation_amount = 10000
        token_amount = pair_state["token_reserve"] * xch_amount * inverse_fee // (1000 * pair_state["xch_reserve"] + inverse_fee * xch_amount)

        offer_dict = {}
        offer_dict[1] = -(xch_amount + xch_donation_amount) # offer XCH
        offer_dict[token_wallet_id] = token_amount # ask for token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            inverse_fee,
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

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + xch_donation_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, token_amount)

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
        if hidden_puzzle_hash is None:
            assert pair_state["xch_reserve"] == 200000000
            assert pair_state["token_reserve"] == 502
            assert pair_state["liquidity"] == 1000
        else:
            assert pair_state["xch_reserve"] == 200000000
            assert pair_state["token_reserve"] == 501
            assert pair_state["liquidity"] == 1000

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        token_amount = 1000
        xch_donation_amount = 100000
        xch_amount = pair_state["xch_reserve"] * token_amount * inverse_fee // (1000 * pair_state["token_reserve"] + inverse_fee * token_amount) - xch_donation_amount

        offer_dict = {}
        offer_dict[1] = xch_amount - xch_donation_amount # ask for XCH
        offer_dict[token_wallet_id] = - token_amount # offer token
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
        offer_str = offer.to_bech32()

        third_donation_ph = b"\xd3" * 32
        third_donation_address = encode_puzzle_hash(third_donation_ph, "xch")
        sb = await respond_to_swap_offer(
           pair_launcher_id,
           current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
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

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount - xch_donation_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, -token_amount)

        third_donation_address_coins = await full_node_client.get_coin_records_by_puzzle_hash(third_donation_ph)
        assert len(third_donation_address_coins) == 1
        assert third_donation_address_coins[0].coin.amount == xch_donation_amount

    @pytest.mark.parametrize(
        "split_kind",
        ["reverse-split", "normal-split", "new-cat"],
        ids=["reverse-split", "normal-split", "new-cat"]
    )
    @pytest.mark.asyncio
    async def test_v2r_rebase(self, setup, split_kind):
        hidden_puzzle = Program.to(1)
        hidden_puzzle_hash = hidden_puzzle.get_tree_hash()

        full_node_client, wallet_client = setup
        router_launcher_id, current_router_coin, router_creation_spend = await self.launch_router(
            wallet_client, full_node_client, True
        )
            
        token_total_supply = 10000000 * 1000 # in mojos
        token_tail_hash = await self.create_test_cat_with_clients(
            wallet_client,
            full_node_client,
            hidden_puzzle_hash,
            token_amount=token_total_supply // 1000
        )
        await self.wait_for_wallet_sync(wallet_client)
        
        inverse_fee = 1000 - 42 # 4.2% swap fee
        pair_launcher_id, current_pair_coin, pair_creation_spend, current_router_coin, router_creation_spend = await self.create_pair(
            wallet_client,
            full_node_client,
            router_launcher_id,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            current_router_coin,
            router_creation_spend
        )
            
        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(pair_launcher_id).get_tree_hash()
        
        await self.wait_for_wallet_sync(wallet_client)
        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, 0, token_total_supply)
        assert (await self.get_balance(wallet_client, pair_liquidity_tail_hash, None)) == 0

        xch_balance_before_all_ops = xch_balance_before = await self.get_balance(wallet_client)

        # 1. Deposit liquidity: 1000 CAT mojos and 100000000 mojos
        # python3 tibet.py deposit-liquidity --xch-amount 100000000 --token-amount 1000 --asset-id [asset_id] --push-tx
        token_wallet_id = await self.get_wallet_id_for_cat(wallet_client, token_tail_hash, hidden_puzzle_hash is not None)
        liquidity_wallet_id = await self.get_wallet_id_for_cat(wallet_client, pair_liquidity_tail_hash, False)

        xch_amount = 100000000
        token_amount = 1000
        liquidity_token_amount = token_amount # initial deposit

        offer_dict = {}
        offer_dict[1] = - xch_amount - liquidity_token_amount # also for liqiudity TAIL creation
        offer_dict[token_wallet_id] = -token_amount
        offer_dict[liquidity_wallet_id] = liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_deposit_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_total_supply, -token_amount)
        await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, 0, liquidity_token_amount)

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
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_deposit_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, -token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, liquidity_balance_before, liquidity_token_amount)

        # 3. Simulate split
        #      - reverse split: all on-chain rCAT balances are divided by a factor of 10
        #      - normal split: all on-chain rCAT balances are multiplied by a factor of 2
        #      - new CAT: on-chain rCAT becomes worthless; rCAT balance set to 0 to disable trading but allow LPs to withdraw their XCH 
        
        # First, if this is a normal split, the extra 5000 CATs will need to come from somewhere
        # The body of this if statement makes sure the 5000 delta is there :)
        additional_spendable_cats = None
        if split_kind == "normal-split":
            needed_amount = 5000
            await wallet_client.cat_spend(
                wallet_id=token_wallet_id,
                tx_config=tx_config,
                amount=needed_amount,
                inner_address=encode_puzzle_hash(hidden_puzzle_hash, "txch"),
            )
            token_balance_now = await self.expect_change_in_token(
                wallet_client,
                token_tail_hash,
                hidden_puzzle_hash,
                token_balance_now,
                -needed_amount
            )

            additional_cat_ph = get_cat_puzzle(
                token_tail_hash,
                hidden_puzzle_hash,
                hidden_puzzle
            ).get_tree_hash()

            additional_cat_record = None
            i = 0
            while additional_cat_record is None and i < 10:
                resp = await full_node_client.get_coin_records_by_puzzle_hash(additional_cat_ph)
                if len(resp) > 0:
                    additional_cat_record = resp[0]
                i += 1
                time.sleep(10)

            assert additional_cat_record is not None
            assert additional_cat_record.coin.amount == needed_amount

            # spend required for lineage proof
            parent_spend = await full_node_client.get_puzzle_and_solution(
                additional_cat_record.coin.parent_coin_info,
                additional_cat_record.confirmed_block_index
            )

            # CAT worth [needed_amount] spent without creating any output
            #   --> delta can go into the new TibetSwap reserve
            additional_spendable_cats = [
                SpendableCAT(
                    additional_cat_record.coin,
                    token_tail_hash,
                    get_cat_inner_puzzle(hidden_puzzle_hash, hidden_puzzle),
                    get_cat_inner_solution(True, hidden_puzzle, Program.to([])),
                    lineage_proof=LineageProof(
                        parent_spend.coin.parent_coin_info,
                        get_innerpuzzle_from_puzzle(parent_spend.puzzle_reveal).get_tree_hash(),
                        parent_spend.coin.amount
                    )
                )
            ]
        
        # Create the coin that will send the rebase
        await wallet_client.send_transaction(
            wallet_id=1,
            amount=1,
            address=encode_puzzle_hash(hidden_puzzle_hash, "txch"),
            tx_config=tx_config,
        )
        xch_balance_now = await self.expect_change_in_token(wallet_client, None, None, xch_balance_now, -1)

        admin_coin_record = None
        i = 0
        while admin_coin_record is None and i < 10:
            resp = await full_node_client.get_coin_records_by_puzzle_hash(hidden_puzzle_hash)
            if len(resp) > 0:
                admin_coin_record = resp[0]
            i += 1
            time.sleep(10)

        assert admin_coin_record is not None

        # Do the rebase

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
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        new_token_reserve = pair_state["token_reserve"] * 2 if split_kind == "normal-split" else pair_state["token_reserve"] // 10 if split_kind == "reverse-split" else 0
        coin_spends, conds = await rebase_spends_and_conditions(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            new_token_reserve,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof,
            additional_spendable_cats=additional_spendable_cats,
        )

        coin_spends.append(make_spend(admin_coin_record.coin, hidden_puzzle, Program.to(conds)))
        sb = SpendBundle(coin_spends, AugSchemeMPL.aggregate([]))

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        if split_kind != "normal-split":
            # 'Change' coin is created by the offer coin that's creaed by the reserve
            # Just want to make sure it correctly ends back to the issuer
            eph_liq_ph = get_cat_puzzle(
                token_tail_hash,
                hidden_puzzle_hash,
                OFFER_MOD
            ).get_tree_hash()
            eph_liq_coin = Coin(token_reserve_coin.name(), eph_liq_ph, token_reserve_coin.amount)
            
            expected_coin_ph = get_cat_puzzle(
                token_tail_hash,
                hidden_puzzle_hash,
                hidden_puzzle
            ).get_tree_hash()
            expected_coin = Coin(eph_liq_coin.name(), expected_coin_ph, eph_liq_coin.amount - new_token_reserve)
            cr = None
            i = 0
            while cr is None and i < 10:
                cr = await full_node_client.get_coin_record_by_name(expected_coin.name())
                i += 1
                time.sleep(10)

            assert cr is not None
            assert not cr.spent

        # 4. Withdraw 800 liquidity tokens
        # python3 tibet.py remove-liquidity --liquidity-token-amount 800 --asset-id [asset_id] --push-tx
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_balance_now

        xch_amount = 80000000
        if split_kind == "reverse-split":
            token_amount = 80
        elif split_kind == "normal-split":
            token_amount = 800 * 2
        else: # new-cat
            token_amount = 0 # No CATs will be given back
        liquidity_token_amount = 800 # 10 for every 1 CAT removed

        offer_dict = {}
        offer_dict[1] = xch_amount + liquidity_token_amount # also ask for xch from liquidity cat burn
        if token_amount > 0:
            offer_dict[token_wallet_id] = token_amount
        offer_dict[liquidity_wallet_id] = -liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
        offer_str = offer.to_bech32()

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 5000
        assert pair_state["xch_reserve"] == 500000000
        if split_kind == "new-cat":
            assert pair_state["token_reserve"] == 0
        elif split_kind == "normal-split":
            assert pair_state["token_reserve"] == 10000
        else: # reverse-split
            assert pair_state["token_reserve"] == 500

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_remove_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_now - xch_balance_before == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, liquidity_balance_before, -liquidity_token_amount)

        # 5. Add 100 liquidity CATs (to make sure it's not possible)
        xch_balance_before = xch_balance_now
        token_balance_before = token_balance_now
        liquidity_balance_before = liquidity_token_amount

        xch_amount = 100000000
        liquidity_token_amount = 1000 # 1:1

        token_amount = -1
        if split_kind == "normal-split":
            token_amount = 1000 * 2
        elif split_kind == "reverse-split":
            token_amount = 1000 // 10
        else: # new-cat
            token_amount = 0 # No CATs will be deposited, duh

        offer_dict = {}
        offer_dict[1] = - xch_amount - liquidity_token_amount # also for liqiudity TAIL creation
        if token_amount != 0:
            offer_dict[token_wallet_id] = -token_amount
        offer_dict[liquidity_wallet_id] = liquidity_token_amount
        offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config)
        offer = offer_resp.offer
        offer_str = offer.to_bech32()

        current_pair_coin, pair_creation_spend, pair_state, sb_to_aggregate, _ = await sync_pair(
            full_node_client, current_pair_coin.name()
        )
        assert pair_state["liquidity"] == 4200
        assert pair_state["xch_reserve"] == 420000000
        if split_kind == "new-cat":
            assert pair_state["token_reserve"] == 0
        elif split_kind == "normal-split":
            assert pair_state["token_reserve"] == 840
        else: # reverse-split
            assert pair_state["token_reserve"] == 420

        xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
            full_node_client,
            pair_launcher_id,
            current_pair_coin,
            token_tail_hash,
            hidden_puzzle_hash,
            pair_creation_spend,
            sb_to_aggregate
        )

        sb = await respond_to_deposit_liquidity_offer(
            pair_launcher_id,
            current_pair_coin,
            pair_creation_spend,
            token_tail_hash,
            hidden_puzzle_hash,
            inverse_fee,
            pair_state["liquidity"],
            pair_state["xch_reserve"],
            pair_state["token_reserve"],
            offer_str,
            xch_reserve_coin,
            token_reserve_coin,
            token_reserve_lineage_proof
        )

        assert((await full_node_client.push_tx(sb))["success"])
        await self.wait_for_wallet_sync(wallet_client)

        xch_balance_now = await self.get_balance(wallet_client)
        assert xch_balance_before - xch_balance_now == xch_amount + liquidity_token_amount

        token_balance_now = await self.expect_change_in_token(wallet_client, token_tail_hash, hidden_puzzle_hash, token_balance_before, -token_amount)
        liquidity_balance_now = await self.expect_change_in_token(wallet_client, pair_liquidity_tail_hash, None, liquidity_balance_before, liquidity_token_amount)

        