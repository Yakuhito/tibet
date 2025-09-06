# Testing on testnet10

To use `tibet.py`, you'll first need to install the required packages:

```bash
python3 -m venv venv
. ./venv/bin/activate
pip install -r requirements.txt
```

Next, you'll have to switch to testnet. There's no point in running a full node (db is comparable in size with that on mainnet), so this guide will use [coinset.org](https://www.coinset.org/) instead of a full node.

```bash
chia stop all
chia configure --testnet true
chia start wallet
```

To speed up sync, add some peers from [https://alltheblocks.net/testnet11/peers](https://alltheblocks.net/testnet11/peers) (copy the `chia peer -a` commands, but replace "full_node" with "wallet"). Do this until `chia wallet show` says that your wallet is syncing or synced.

Next, get some TXCH (test XCH, the currency of the testnet) from [here](https://xchdev.com/#!faucet.md) or [here](https://testnet11-faucet.chia.net/).

You can also get some TDBX by accepting offers from [Dexie](https://testnet.dexie.space/offers/TDBX/TXCH):
```bash
chia wallet take_offer -m [fee_amount_in_xch] [raw_offer]
```

Configure tibet:
```bash
rm config.json # delete prev. config
python3 tibet.py config-node --use-preset testnet11
python3 tibet.py test-node-config
python3 tibet.py set-routers \
    --launcher-id [testnet-router-id] \
    --rcat-launcher-id [testnet-rcat-router-launcher-id]
python3 tibet.py sync-pairs
```

Time to play! See [TESTING.md](TESTING.md) to get an idea of the possible commands. Do not forget to use the `--fee` switch since the testnet mempool seems full.

*Note on fees*: If your transaction says 'pending', it means that your previous fee was too low. You need to re-generate the offer (cancel it and re-run the command) with a higher fee and then submit it to the blockchain. Keep in mind that the minimum fee bump is 10 million (10,000,000) mojos.

To get back on mainnet:
```bash
chia stop all
chia configure --testnet false
```
