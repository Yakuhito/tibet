import warnings
warnings.filterwarnings("ignore")

import pytest
import pytest_asyncio

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, calculate_synthetic_secret_key, DEFAULT_HIDDEN_PUZZLE_HASH
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
        puzzle = puzzle_for_pk(alice.pk())
        launcher_id, sb = await launch_router_from_coin(coin, puzzle)
        signed_sb = await sign_spend_bundle_with_specific_sk(sb, synth_sk)

        await network.push_tx(signed_sb)

        return launcher_id

    # async def create_test_cat(self, network, alice):
    #     coin = await alice.choose_coin(10000 * 1000000)
    #     coin = coin.coin # we want a Coin, not a CoinWrapper
    #     alice_sk = alice.pk_to_sk(alice.pk())
    #     synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)
    #     tail, sb = await create_test_cat(coin, synth_sk)
    #     await network.push_tx(sb)

    #     return tail

    # async def create_pair(self, network, alice, launcher_id, tail_hash):
    #     coin = await alice.choose_coin(2)
    #     coin = coin.coin # we want a Coin, not a CoinWrapper
    #     alice_sk = alice.pk_to_sk(alice.pk())
    #     synth_sk = calculate_synthetic_secret_key(alice_sk, DEFAULT_HIDDEN_PUZZLE_HASH)
    #     pair_launcher_id, sb = await create_pair(network, coin, synth_sk, launcher_id, tail_hash)
    #     await network.push_tx(sb)
    #     return pair_launcher_id

    @pytest.mark.asyncio
    async def test_router_launch(self, setup):
        network, alice, bob = setup
        try:
            launcher_id = await self.launch_router(network, alice)

            cr = await network.get_coin_record_by_name(bytes.fromhex(launcher_id))
            assert cr is not None
            assert cr.confirmed_block_index is not None
            assert cr.spent_block_index is not None
        finally:
            await network.close()

    # @pytest.mark.asyncio
    # async def test_pair_creation(self, setup):
    #     network, alice, bob = setup
    #     try:
    #         launcher_id = await self.launch_router(network, alice)
    #         tail = await self.create_test_cat(network, alice)
    #         pair_launcher_id = await self.create_pair(network, alice, launcher_id, tail)

    #         cr = await network.get_coin_record_by_name(bytes.fromhex(pair_launcher_id))
    #         assert cr is not None
    #         assert cr.spent

    #         # one more, to makesure lineage_proof is behaving correctly
    #         tail2 = await self.create_test_cat(network, alice)
    #         pair_launcher_id2 = await self.create_pair(network, alice, launcher_id, tail2)

    #         cr2 = await network.get_coin_record_by_name(bytes.fromhex(pair_launcher_id2))
    #         assert cr2 is not None
    #         assert cr2.spent

    #         # third time - assure pairs are parsed correctly
    #         tail3 = await self.create_test_cat(network, alice)
    #         pair_launcher_id3 = await self.create_pair(network, alice, launcher_id, tail3)

    #         cr3 = await network.get_coin_record_by_name(bytes.fromhex(pair_launcher_id3))
    #         assert cr3 is not None
    #         assert cr3.spent
    #     finally:
    #         await network.close()