#!/bin/bash

puzzles=(
    "router"
    "p2_singleton_flashloan"
    "p2_merkle_tree_modified"
    "liquidity_tail"
    "pair_inner_puzzle"
    "add_liquidity"
    "remove_liquidity"
    "swap"
    "v2r_router"
    "v2r_pair_inner_puzzle"
)

for puzzle in ${puzzles[@]}; do
    echo "$puzzle.clvm"
    run "clsp/$puzzle.clsp" -O -i include/ > "clvm/$puzzle.clvm"

    echo "$puzzle.clvm.hex"
    run "clsp/$puzzle.clsp" -O -i include/ -d > "clvm/$puzzle.clvm.hex"
done