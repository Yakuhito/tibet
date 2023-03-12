#!/bin/bash
. ./venv/bin/activate
export CHIA_ROOT=~/.chia/simulator/main

chia stop all
rm -r ~/.chia/simulator

export PREFARM_FINGERPRINT=2036195148
export ALICE_FINGERPRINT=381910353
export BOB_FINGERPRINT=3852922401
export CHARLIE_FINGERPRINT=1514229218

cdv sim create -f $PREFARM_FINGERPRINT
chia start wallet
pytest tests/ -s -v --durations 0 -W ignore::DeprecationWarning