# CLI on mainnet

Install the required packages:

```bash
python3 -m venv venv
. ./venv/bin/activate
pip install -r requirements.txt
```

Next, you'll have to ensure that you're on mainnet. If you're on testnet, here's how to switch back to mainnet:

```bash
chia stop all
chia configure --testnet false
chia start wallet
```

If you've used the `testnet` version of TibetSwap, do not forget to remove the configuration:


```bash
rm config.json # delete prev. config
```

Use the following command to configure `tibet.py` (using [coinset.org](https://www.coinset.org/) for the full node RPC):
```bash
python3 tibet.py config-node --use-preset mainnet
```

If you're running a full node, thank you for making the network more decentralized! Run this command instead of the last one to make requests go through your full node:

```bash
python3 tibet.py config-node --use-preset --use-local-node
```

To finish configuring `tibet.py`, run the following 3 commands:

```bash
python3 tibet.py test-node-config
python3 tibet.py set-router --launcher-id a6f4b5458aa99b07fbb9a5b2d5309610d01c17900015c48d40bc321b15fe64bd
python3 tibet.py set-routers \
    --launcher-id a6f4b5458aa99b07fbb9a5b2d5309610d01c17900015c48d40bc321b15fe64bd \
    --rcat-launcher-id [rcat-router-launcher-id]
python3 tibet.py sync-pairs
```

Time to play! See [TESTING.md](TESTING.md) to get an idea of the possible commands.

*Note on fees*: If your transaction says 'pending', it means that your previous fee was too low. You need to re-generate the offer (cancel/delete it and re-run the command) with a higher fee and then submit it to the blockchain. Keep in mind that the minimum fee bump is 10 million (10,000,000) mojos.
