import warnings
warnings.filterwarnings("ignore")

import pytest
import pytest_asyncio

import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, calculate_synthetic_secret_key, DEFAULT_HIDDEN_PUZZLE_HASH
from cdv.test import setup as setup_test
from tibet import *

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
        launcher_id, sb = await launch_router_with_sk(coin, synth_sk)
        await network.push_tx(sb)

        return launcher_id

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