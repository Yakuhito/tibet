```bash
# environment stuff
# python3 -m venv venv + install
. ./venv/bin/activate
export CHIA_ROOT=~/.chia/simulator/main

# remove prev sessions
chia stop all
rm -r ~/.chia/simulator
rm config.json

# new testing session
cdv sim create # choose a wallet that you *won't* use for testing
chia start wallet
chia wallet get_address # choose wallet that you will use for testing
cdv sim farm -b 7 -a [ADDRESS]

# setup router, test token, and test token pair
python3 tibet.py  config-node --use-preset simulator
python3 tibet.py test-node-config
python3 tibet.py launch-router
python3 tibet.py launch-router --push-tx
python3 tibet.py launch-test-token
python3 tibet.py launch-test-token --push-tx
python3 tibet.py create-pair --asset-id [asset_id_from_last_output]
python3 tibet.py create-pair --asset-id [asset_id_from_last_output] --push-tx
```