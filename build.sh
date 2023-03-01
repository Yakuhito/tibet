#!/bin/bash

echo "pair.clvm"
run clsp/pair.clsp -O -i include/ > clvm/pair.clvm

echo "pair.clvm.hex"
run clsp/pair.clsp -O -i include/ -d > clvm/pair.clvm.hex

echo "router.clvm"
run clsp/router.clsp -O -i include/ > clvm/router.clvm

echo "router.clvm.hex"
run clsp/router.clsp -O -i include/ -d > clvm/router.clvm.hex

echo "liquidity_tail.clvm"
run clsp/liquidity_tail.clsp -O -i include/ > clvm/liquidity_tail.clvm

echo "liquidity_tail.clvm.hex"
run clsp/liquidity_tail.clsp -O -i include/ -d > clvm/liquidity_tail.clvm.hex

echo "p2_singleton_flashloan.clvm"
run clsp/p2_singleton_flashloan.clsp -O -i include/ > clvm/p2_singleton_flashloan.clvm

echo "p2_singleton_flashloan.clvm.hex"
run clsp/p2_singleton_flashloan.clsp -O -i include/ -d > clvm/p2_singleton_flashloan.clvm.hex
