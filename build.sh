#!/bin/bash

echo "pair.clvm"
run clsp/pair.clsp -O -i include/ > clvm/pair.clvm

echo "pair.clvm.hex"
run clsp/pair.clsp -O -i include/ -d > clvm/pair.clvm.hex

echo "router.clvm"
run clsp/router.clsp -O -i include/ > clvm/router.clvm

echo "router.clvm.hex"
run clsp/router.clsp -O -i include/ -d > clvm/router.clvm.hex
