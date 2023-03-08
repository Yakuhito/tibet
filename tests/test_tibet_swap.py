import warnings
warnings.filterwarnings("ignore")

import pytest
import pytest_asyncio

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, calculate_synthetic_secret_key, DEFAULT_HIDDEN_PUZZLE_HASH
from chia.wallet.puzzles.singleton_top_layer_v1_1 import launch_conditions_and_coinsol, SINGLETON_MOD_HASH, SINGLETON_MOD, SINGLETON_LAUNCHER_HASH, SINGLETON_LAUNCHER, lineage_proof_for_coinsol, puzzle_for_singleton, solution_for_singleton, generate_launcher_coin
from cdv.test import setup as setup_test
from tibet_lib import *
from private_key_things import *

class TestTibetSwap:
    @pytest_asyncio.fixture(scope="function")
    async def setup(self):
        network, alice, bob = await setup_test()
        await network.farm_block()
        await network.farm_block(farmer=alice)
        await network.farm_block(farmer=bob)
        yield network, alice, bob

    async def launch_router(self, network, alice):
        coin = await alice.choose_coin(2)
        coin = coin.coin # we want a Coin, not a CoinWrapper

        alice_sk = alice.pk_to_sk(alice.pk())
        synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)

        coin_puzzle = puzzle_for_pk(alice.pk())

        launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle)

        signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)
        await network.push_tx(signed_sb)

        router_launch_coin_spend = None
        router_current_coin = None
        for cs in signed_sb.coin_spends:
            if cs.coin.puzzle_hash == SINGLETON_LAUNCHER_HASH:
                router_launch_coin_spend = cs
            
                _, conditions_dict, __ = conditions_dict_for_solution(
                    cs.puzzle_reveal,
                    cs.solution,
                    INFINITE_COST
                )

                router_current_coin = Coin(
                    cs.coin.name(),
                    conditions_dict[ConditionOpcode.CREATE_COIN][0].vars[0], # puzzle hash of created coin
                    1
                )

        return bytes.fromhex(launcher_id), router_current_coin, router_launch_coin_spend

    async def create_test_cat(self, network, alice, token_amount=1000000000): # token_amount = 1000 * 1000000 = 1,000,000 tokens
        coin = await alice.choose_coin(token_amount)
        coin = coin.coin # we want a Coin, not a CoinWrapper

        alice_sk = alice.pk_to_sk(alice.pk())
        synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)

        coin_puzzle = puzzle_for_pk(alice.pk())

        tail_hash, sb = await create_test_cat(token_amount, coin, coin_puzzle)
        
        signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)
        await network.push_tx(signed_sb)

        return bytes.fromhex(tail_hash)

    async def create_pair(
        self,
        network,
        alice,
        router_launcher_id,
        tail_hash,
        current_router_coin,
        current_router_coin_creation_spend
    ):
        coin = await alice.choose_coin(2)
        coin = coin.coin # we want a Coin, not a CoinWrapper

        alice_sk = alice.pk_to_sk(alice.pk())
        synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)

        coin_puzzle = puzzle_for_pk(alice.pk())

        pair_launcher_id, sb = await create_pair_from_coin(
            coin,
            coin_puzzle,
            tail_hash,
            router_launcher_id,
            current_router_coin,
            current_router_coin_creation_spend
        )

        signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)
        await network.push_tx(signed_sb)

        return bytes.fromhex(pair_launcher_id)

    @pytest.mark.asyncio
    async def test_router_launch(self, setup):
        network, alice, bob = setup
        try:
            launcher_id, current_router_coin, router_launch_coin_spend = await self.launch_router(network, alice)

            cr = await network.get_coin_record_by_name(launcher_id)

            assert cr is not None
            assert cr.confirmed_block_index is not None
            assert cr.spent_block_index is not None
        finally:
            await network.close()

    @pytest.mark.asyncio
    async def test_pair_creation(self, setup):
        network, alice, bob = setup
        try:
            launcher_id, current_router_coin, router_launch_coin_spend  = await self.launch_router(network, alice)

            tail_hash = await self.create_test_cat(network, alice)
            pair_launcher_id = await self.create_pair(
                network, alice, launcher_id, tail_hash, current_router_coin, router_launch_coin_spend
            )

            cr = await network.get_coin_record_by_name(pair_launcher_id)
            assert cr is not None
            assert cr.spent
        finally:
            await network.close()