```bash
# Before running commands, make sure you followed instructions in either:
#  - mainnet.md (for mainnet)
#  - testnet.md (for testnet)
# To set up wallet

# setup router, test token, and test token pair
python3 tibet.py config-node --use-preset [network]
python3 tibet.py test-node-config

python3 tibet.py launch-router
python3 tibet.py launch-router --push-tx
# For rCATs, just add a '--rcat' switch to the two commands above

python3 tibet.py launch-test-token # take note of asset_id
python3 tibet.py launch-test-token --push-tx
# For rCATs, add: --hidden-puzzle-hash 0000000000000000000000000000000000000000000000000000000000000000

python3 tibet.py create-pair --asset-id [asset_id]
python3 tibet.py create-pair --push-tx --asset-id [asset_id]
# For rCATs, add: --hidden-puzzle-hash 0000000000000000000000000000000000000000000000000000000000000000 --inverse-fee 999

python3 tibet.py sync-pairs
# For rCATs, add: --rcat

# running one of the following commands will generate an offer
# that is not cancelled even if --push-tx was not used
# that's why the second command always uses --offer and reads the offer from
# offer.txt, where the cli writes it for the first time

# to clear offers, use:
# chia wallet get_offers
# chia wallet cancel_offer -id [id]
python3 tibet.py deposit-liquidity --xch-amount 100000000 --token-amount 1000 --asset-id [asset_id]
python3 tibet.py deposit-liquidity --offer offer.txt --push-tx --asset-id [asset_id]

python3 tibet.py get-pair-info --asset-id [asset_id]

python3 tibet.py deposit-liquidity --token-amount 4000 --asset-id [asset_id] 
python3 tibet.py deposit-liquidity --offer offer.txt --push-tx --asset-id [asset_id]

python3 tibet.py get-pair-info --asset-id [asset_id]

python3 tibet.py remove-liquidity --liquidity-token-amount 800 --asset-id [asset_id]
python3 tibet.py remove-liquidity --offer offer.txt --push-tx --asset-id [asset_id]

python3 tibet.py get-pair-info --asset-id [asset_id]

python3 tibet.py xch-to-token --xch-amount 100000000 --asset-id [asset_id]
python3 tibet.py xch-to-token --offer offer.txt --push-tx --asset-id [asset_id]

python3 tibet.py get-pair-info --asset-id [asset_id]

python3 tibet.py token-to-xch --token-amount 1000 --asset-id [asset_id]
python3 tibet.py token-to-xch --offer offer.txt --push-tx --asset-id [asset_id]

python3 tibet.py get-pair-info --asset-id [asset_id]

python3 tibet.py remove-liquidity --liquidity-token-amount 4200 --asset-id [asset_id]
python3 tibet.py remove-liquidity --offer offer.txt --push-tx --asset-id [asset_id]

python3 tibet.py get-pair-info --asset-id [asset_id]
```
