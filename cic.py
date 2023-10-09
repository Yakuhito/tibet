try:
    from chia.types.blockchain_format.serialized_program import SerializedProgram
except:
    from chia.types.blockchain_format.program import SerializedProgram
import hashlib
from typing import List
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.singleton_top_layer_v1_1 import \
    SINGLETON_LAUNCHER_HASH
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_MOD_HASH
from chia.types.coin_spend import CoinSpend
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.cat_wallet.cat_utils import get_innerpuzzle_from_puzzle
from typing import Tuple, Dict, List, Any

# stolen from cic: https://github.com/Chia-Network/internal-custody/blob/main/cic/drivers/merkle_utils.py
HASH_TREE_PREFIX = bytes([2])
HASH_LEAF_PREFIX = bytes([1])

TupleTree = Any  # Union[bytes32, Tuple["TupleTree", "TupleTree"]]
Proof_Tree_Type = Any  # Union[bytes32, Tuple[bytes32, "Proof_Tree_Type"]]


def compose_paths(path_1: int, path_2: int, path_2_length: int) -> int:
    return (path_1 << path_2_length) | path_2


def sha256(*args: bytes) -> bytes32:
    return bytes32(hashlib.sha256(b"".join(args)).digest())


def build_merkle_tree_from_binary_tree(tuples: TupleTree) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    if isinstance(tuples, bytes):
        tuples = bytes32(tuples)
        return sha256(HASH_LEAF_PREFIX, tuples), {tuples: (0, [])}

    left, right = tuples
    left_root, left_proofs = build_merkle_tree_from_binary_tree(left)
    right_root, right_proofs = build_merkle_tree_from_binary_tree(right)

    new_root = sha256(HASH_TREE_PREFIX, left_root, right_root)
    new_proofs = {}
    for name, (path, proof) in left_proofs.items():
        proof.append(right_root)
        new_proofs[name] = (path, proof)
    for name, (path, proof) in right_proofs.items():
        path |= 1 << len(proof)
        proof.append(left_root)
        new_proofs[name] = (path, proof)
    return new_root, new_proofs


def list_to_binary_tree(objects: List[Any]):
    size = len(objects)
    if size == 1:
        return objects[0]
    midpoint = (size + 1) >> 1
    first_half = objects[:midpoint]
    last_half = objects[midpoint:]
    return (list_to_binary_tree(first_half), list_to_binary_tree(last_half))


def build_merkle_tree(objects: List[bytes32]) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    """
    return (merkle_root, dict_of_proofs)
    """
    objects_binary_tree = list_to_binary_tree(objects)
    return build_merkle_tree_from_binary_tree(objects_binary_tree)
