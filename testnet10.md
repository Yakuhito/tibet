# Testing on testnet10

First, set up [chia-dev-tools](https://github.com/Chia-Network/chia-dev-tools) first. Make sure your venv is active while using `tibet.py`:

```bash
. ./venv/bin/activate
```

Next, you'll have to switch to testnet10. There's no point in running a full node (db is comparable in size with that on mainnet), so this guide will use [FireAcademy.io](https://fireacademy.io) instead of a full node.

```bash
chia stop all
chia configure --testnet true
chia start wallet
```

Add some peers from [https://alltheblocks.net/testnet10/peers](https://alltheblocks.net/testnet10/peers) (copy the `chia peer -a` commands, but replace "full_node" with "wallet"). Do this until `chia wallet show` says that your wallet is syncing or synced.

Next, get some TXCH (test XCH, the currency of the testnet) from [here](https://xchdev.com/#!faucet.md) or [here](https://testnet10-faucet.chia.net/).

You can also get some TDBX by accepting offers from [Dexie](https://testnet.dexie.space/offers/TDBX/TXCH):
```bash
chia wallet take_offer -m [fee_amount_in_xch] [raw_offer]
```

Before configuring `tibet.py`, you'll need an API key from [FireAcademy.io](https://fireacademy.io). Create an account and get one for free [here](https://dashboard.fireacademy.io/).

Configure:
```bash
rm config.json # delete prev. config
python3 tibet.py config-node --use-preset testnet10 --fireacademyio-api-key [you-api-key]
python3 tibet.py test-node-config
python3 tibet.py set-router --launcher-id 95415cd28341ac7a8c4494ca185d719ad7c25928cea5a6d74ae478820fe48f40
python3 tibet.py sync-pairs
```

Time to play! See [TESTING.md](TESTING.md) to get an idea of the possible commands. Do not forget to use the `--fee` switch along with some mojos (e.g., 1000000000, which translates to 0.001 XCH).

To get back on mainnet:
```bash
chia stop all
chia configure --testnet false
```