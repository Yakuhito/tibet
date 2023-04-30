# CLI on mainnet

Install the required packages:

```bash
python3 -m venv venv
. ./venv/bin/activate
pip install -r requirements.txt
pip install --extra-index-url https://pypi.chia.net/simple/ chia-internal-custody
pip install --extra-index-url https://pypi.chia.net/simple/ chia-dev-tools
```

Next, you'll have to ensure that you're on mainnet. If you're on testnet10, here's how to switch back to mainnet:

```bash
chia stop all
chia configure --testnet false
chia start wallet
```

If you've used the `testnet10` version of TibetSwap, do not forget to remove the configuration:


```bash
rm config.json # delete prev. config
```

If you're not running a full node on your computer (i.e., wallet mode), you'll need an API key from [FireAcademy.io](https://fireacademy.io). Create an account and get one for free [here](https://dashboard.fireacademy.io/). Use the following command to start configuring `tibet.py`:
```bash
python3 tibet.py config-node --use-preset mainnet --fireacademyio-api-key [you-api-key]
```

If you're running a full node, thank you for making the network more decentralized! Run this command instead of the last one to make requests go through your full node:

```bash
python3 tibet.py config-node --use-preset mainnet
```

To finish configuring `tibet.py`, run the following 3 commands:

```bash
python3 tibet.py test-node-config
python3 tibet.py set-router --launcher-id [launcher_id]
python3 tibet.py sync-pairs
```

Time to play! See [TESTING.md](TESTING.md) to get an idea of the possible commands.

*Note on fees*: If your transaction says 'pending', it means that your previous fee was too low. You need to re-generate the offer (cancel it and re-run the command) with a higher fee and then submit it to the blockchain. Keep in mind that the minimum fee bump is 10 million (10,000,000) mojos.
