from pathlib import Path
from typing import List

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint64
from clvm.casts import int_to_bytes

import cdv.clibs as std_lib
from cdv.util.load_clvm import load_clvm

clibs_path: Path = Path(std_lib.__file__).parent
ROUTER_MOD: Program = load_clvm("router.clsp", "clsp", search_paths=[clibs_path])
