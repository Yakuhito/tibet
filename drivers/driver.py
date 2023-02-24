import os
from pathlib import Path
from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint64
from clvm.casts import int_to_bytes

from chia.wallet.puzzles.load_clvm import load_clvm

ROUTER_MOD: Program = load_clvm("../../../../../../../clvm/router.clvm", recompile=False)
PAIR_MOD: Program = load_clvm("../../../../../../../clvm/pair.clvm", recompile=False)

print(ROUTER_MOD)