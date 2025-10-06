import asyncio
import json
import os
import sys

import click
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig


from private_key_things import *
from tibet_lib import *

tx_config = TXConfig(
    1,
    1337 * 10 ** 15,
    [],
    [],
    True
)


@click.group()
def cli():
    pass


cached_config = None


def get_config_item(*args):
    global cached_config
    if cached_config is None:
        get_config()

    ret = cached_config
    for arg in args:
        if ret is None:
            return ret
        ret = ret.get(arg, None)

    return ret


def get_config():
    global cached_config
    if cached_config is None:
        try:
            cached_config = json.loads(open("config.json", "r").read())
        except:
            open("config.json", "w").write("{}")
            cached_config = {}

    return cached_config


def save_config(config):
    cached_config = config
    open("config.json", "w").write(
        json.dumps(config, sort_keys=True, indent=4))


@click.command()
@click.option('--chia-root', default=None, help='Chia root directory (e.g., ~/.chia/mainnet)')
@click.option('--use-sage', default=False, help='Use Sage wallet instead of reference wallet (recommended)')
@click.option('--network', default='mainnet', type=click.Choice(['testnet', 'mainnet'], case_sensitive=False))
@click.option('--use-local-node', default=False, help='Use your local full node instead of coinset.org')
def config_node(chia_root, use_sage, network, use_local_node):
    chia_root = os.path.expanduser(os.getenv('CHIA_ROOT', default="~/.chia/mainnet"))

    root_path = Path(chia_root)
    config = load_config(root_path, "config.yaml")
    selected_network = config["selected_network"]
    agg_sig_me_additional_data = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA.hex()
    try:
        agg_sig_me_additional_data = config['full_node']['network_overrides'][
            'constants'][selected_network]['AGG_SIG_ME_ADDITIONAL_DATA']
        print(f"Using network overrides for agg_sig_me_additional_data: {agg_sig_me_additional_data}")
    except:
        pass

    config = get_config()

    config["chia_root"] = chia_root
    config["agg_sig_me_additional_data"] = agg_sig_me_additional_data
    config["use_sage"] = use_sage

    if use_local_node:
        config["rpc_url"] = ""
    else:
        if network == 'mainnet':
            config["rpc_url"] = "https://api.coinset.org/"
        else:
            config["rpc_url"] = "https://testnet11.api.coinset.org/"

    save_config(config)
    click.echo("Config updated and saved successfully.")


@click.command()
def test_node_config():
    asyncio.run(_test_node_config())


async def _test_node_config():
    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))
    full_node_client_status = await full_node_client.healthz()
    click.echo("full node client... " + str(full_node_client_status))

    full_node_client.close()
    await full_node_client.await_closed()

    sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))
    wallet_client_status = 'OK'
    if not sage:
        wallet_client_status = await wallet_client.healthz()
    click.echo("wallet client... " + str(wallet_client_status))

    if not sage:
        wallet_client.close()
        await wallet_client.await_closed()


@click.command()
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and update launcher is in config.")
@click.option('--fee', default=0, help='Fee to use for transaction')
@click.option('--rcat', is_flag=True, show_default=True, default=False, help="Launch a v2r router (for XCH-rCAT pairs) instead of a v2 router (for XCH-CAT pairs)")
def launch_router(push_tx, fee, rcat):
    asyncio.run(_launch_router(push_tx, fee, rcat))


async def _launch_router(push_tx, fee, rcat):
    sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))
    if sage:
        print("Cannot launch router with Sage yet")
        return

    # wallet id 1, amount 2 (+ fee)
    coins = await wallet_client.select_coins(2 + fee, 1, coin_selection_config=CoinSelectionConfig(
        min_coin_amount=fee + 2,
        max_coin_amount=1337 * 10 ** 12,
        excluded_coin_amounts=[],
        excluded_coin_ids=[]
    ))

    coin = coins[0]
    coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)

    click.echo(f"Using coin 0x{coin.name().hex()}...")

    launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle, rcat, fee=fee)
    click.echo(f"Router launcher id: {launcher_id}")

    signed_sb = await sign_spend_bundle(
        wallet_client,
        sb,
        additional_data=bytes.fromhex(get_config_item("agg_sig_me_additional_data"))
    )

    if push_tx:
        click.echo(f"Pushing tx...")
        full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))
        resp = await full_node_client.push_tx(signed_sb)
        click.echo(resp)
        full_node_client.close()
        await full_node_client.await_closed()

        click.echo("Saving config...")
        config = get_config()
        if rcat:
            config["rcat_router_launcher_id"] = launcher_id
            config["rcat_router_last_processed_id"] = launcher_id
            config["rcat_pairs"] = {}
        else:
            config["router_launcher_id"] = launcher_id
            config["router_last_processed_id"] = launcher_id
            config["pairs"] = {}
        save_config(config)
        click.echo("Done.")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            signed_sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    wallet_client.close()
    await wallet_client.await_closed()


@click.command()
@click.option('--launcher-id', required=False, help='Launcher coin id of the v2 router.')
@click.option('--rcat-launcher-id', required=False, help='Launcher coin id of the v2r (XCH-rCAT pairs) router.')
def set_routers(launcher_id, rcat_launcher_id):
    asyncio.run(_set_routers(launcher_id, rcat_launcher_id))


async def _set_routers(router_launcher_id, rcat_launcher_id):
    click.echo("Saving config...")
    config = get_config()

    if router_launcher_id is not None:
        print("Updating v2 router...")
        config["router_launcher_id"] = router_launcher_id
        config["router_last_processed_id"] = router_launcher_id
        config["pairs"] = {}
    else:
        print("No v2 router provided, skipping update...")

    if rcat_launcher_id is not None:
        print("Updating v2r router...")
        config["rcat_router_launcher_id"] = rcat_launcher_id
        config["rcat_router_last_processed_id"] = rcat_launcher_id
        config["rcat_pairs"] = {}
    else:
        print("No v2r router provided, skipping update...")

    save_config(config)
    click.echo("Done.")


@click.command()
@click.option('--amount', default=1000000, help='Amount, in CATs (1 CAT = 1000 mojos)')
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and add cat to wallet.")
@click.option('--hidden-puzzle-hash', default=None, help="Hidden puzzle hash (hex string) for rCATs; if not provided, a normal CAT will be created.")
def launch_test_token(amount, push_tx, hidden_puzzle_hash):
    if hidden_puzzle_hash is not None and len(hidden_puzzle_hash) != 64:
        click.echo("Oops! That hidden puzzle hash doesn't look right...")
        sys.exit(1)

    if hidden_puzzle_hash is not None:
        hidden_puzzle_hash = bytes.fromhex(hidden_puzzle_hash)

    asyncio.run(_launch_test_token(amount, push_tx, hidden_puzzle_hash))


async def _launch_test_token(amount, push_tx, hidden_puzzle_hash):
    click.echo(
        f"Creating test CAT with a supply of {amount} ({amount * 1000} mojos used)...")
    sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))
    if sage:
        print("Cannot launch test CAT with Sage yet")
        return

    # wallet id 1 = XCH
    coins = await wallet_client.select_coins(amount * 1000, 1, coin_selection_config=CoinSelectionConfig(
        min_coin_amount=amount * 1000,
        max_coin_amount=1337 * 10 ** 12,
        excluded_coin_amounts=[],
        excluded_coin_ids=[]
    ))

    coin = coins[0]
    coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)

    click.echo(f"Using coin 0x{coin.name().hex()}...")

    tail_id, sb = await create_test_cat(hidden_puzzle_hash, amount, coin, coin_puzzle)
    click.echo(f"Token asset id: {tail_id}")

    signed_sb = await sign_spend_bundle(wallet_client, sb, additional_data=bytes.fromhex(get_config_item("agg_sig_me_additional_data")))

    if push_tx:
        click.echo(f"Pushing tx...")
        full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))
        resp = await full_node_client.push_tx(signed_sb)
        click.echo(resp)
        full_node_client.close()
        await full_node_client.await_closed()

        click.echo("Adding asset id to wallet...")
        resp = await wallet_client.create_wallet_for_existing_cat(bytes.fromhex(tail_id))
        click.echo(resp)
        click.echo("Done.")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            signed_sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    wallet_client.close()
    await wallet_client.await_closed()


@click.command()
@click.option('--asset-id', required=True, help='Asset id (TAIL hash) of token to be offered in pair (token-XCH)')
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and add liquidity CAT to wallet.")
@click.option('--fee', default=ROUTER_MIN_FEE, help=f'Fee to use for transaction (min fee: {ROUTER_MIN_FEE} = 0.042 XCH)')
@click.option('--hidden-puzzle-hash', show_default=True, default=None, help="If provided, the pair will be created for an rCAT instead of a normal CAT.")
@click.option('--inverse-fee', show_default=True, default=999, help="[for XCH-rCAT pairs only] Inverse fee for the pair (999 means 0.1 percent fee)")
def create_pair(asset_id, push_tx, fee, hidden_puzzle_hash, inverse_fee):
    # very basic check to prevent most mistakes
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)

    if hidden_puzzle_hash is not None and len(hidden_puzzle_hash) != 64:
        click.echo("Oops! That hidden puzzle hash doesn't look right...")
        sys.exit(1)

    if hidden_puzzle_hash is not None:
        hidden_puzzle_hash = bytes.fromhex(hidden_puzzle_hash)

    if hidden_puzzle_hash is not None and (inverse_fee < 952 or inverse_fee >= 1000):
        click.echo("Oops! That inverse fee doesn't look right - chose a value between 952 and 999 (inclusive).")
        sys.exit(1)

    asyncio.run(_create_pair(asset_id, push_tx, fee, hidden_puzzle_hash, inverse_fee))


async def _create_pair(tail_hash, push_tx, fee, hidden_puzzle_hash, inverse_fee):
    if fee < ROUTER_MIN_FEE:
        click.echo(
            "The router imposes a minimum fee of 42000000000 mojos (0.042 XCH)")
        sys.exit(1)

    if hidden_puzzle_hash is not None:
        click.echo(f"Creating XCH-rCAT pair for {tail_hash}...")
    else:
        click.echo(f"Creating XCH-CAT pair for {tail_hash}...")

    router_launcher_id = get_config_item("router_launcher_id")
    router_last_processed_id = get_config_item("router_last_processed_id")
    if hidden_puzzle_hash is not None:
        router_launcher_id = get_config_item("rcat_router_launcher_id")
        router_last_processed_id = get_config_item("rcat_router_last_processed_id")

    if router_launcher_id is None or router_last_processed_id is None:
        click.echo("Oops - looks like someone forgot to launch their router.")
        sys.exit(1)

    click.echo("But first, we do a little sync")
    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))
    current_router_coin, latest_creation_spend, pairs = await sync_router(
        full_node_client, bytes.fromhex(router_last_processed_id), hidden_puzzle_hash is not None
    )
    router_last_processed_id_new = current_router_coin.name().hex()
    click.echo(f"Last router id: {router_last_processed_id_new}")

    if len(pairs) != 0 or router_last_processed_id_new != router_last_processed_id:
        click.echo("New pairs found! Saving them...")
        router_last_processed_id = router_last_processed_id_new

        config = get_config()
        pairs_key = "rcat_pairs" if hidden_puzzle_hash is not None else "pairs"
        if hidden_puzzle_hash is not None:
            config["rcat_router_last_processed_id"] = router_last_processed_id
            config["rcat_pairs"] = config.get("rcat_pairs", {})

            for (tail_hash, pair_launcher_id, pair_hidden_puzzle_hash, pair_inverse_fee) in pairs:
                saved_pairs = config["rcat_pairs"].get(tail_hash, [])
                already_seen = False
                for saved_pair in saved_pairs:
                    if saved_pair["hidden_puzzle_hash"] == pair_hidden_puzzle_hash and saved_pair["inverse_fee"] == pair_inverse_fee:
                        already_seen = True
                        break
                if not already_seen:
                    if len(config["rcat_pairs"].get(tail_hash, [])) == 0:
                        config["rcat_pairs"][tail_hash] = []

                    config["rcat_pairs"][tail_hash].append({
                        "hidden_puzzle_hash": pair_hidden_puzzle_hash,
                        "inverse_fee": pair_inverse_fee,
                        "pair_launcher_id": pair_launcher_id
                    })
        else:
            config["router_last_processed_id"] = router_last_processed_id
            config["pairs"] = config.get("pairs", {})
            for pair in pairs:
                if config["pairs"].get(pair[0], -1) == -1:
                    config["pairs"][pair[0]] = pair[1]
        save_config(config)

    sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))
    if sage:
        print("Cannot create pair with Sage yet")
        return
    print(f"Fee: {fee}")
    # wallet id 1 = XCH
    coins = await wallet_client.select_coins(fee + 1, 1, coin_selection_config=CoinSelectionConfig(
        min_coin_amount=fee + 1,
        max_coin_amount=1337 * 10 ** 12,
        excluded_coin_amounts=[],
        excluded_coin_ids=[]
    ))

    coin = coins[0]
    coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)

    click.echo(f"Using coin 0x{coin.name().hex()} (amount: {coin.amount})...")

    pair_launcher_id, sb, _a, _b = await create_pair_from_coin(
        coin,
        coin_puzzle,
        bytes.fromhex(tail_hash),
        hidden_puzzle_hash,
        inverse_fee,
        bytes.fromhex(router_launcher_id),
        current_router_coin,
        latest_creation_spend,
        fee=fee
    )
    click.echo(f"Pair launcher id: {pair_launcher_id}")

    pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(
        bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()
    click.echo(f"Liquidity asset id: {pair_liquidity_tail_hash}")

    signed_sb = await sign_spend_bundle(wallet_client, sb, additional_data=bytes.fromhex(get_config_item("agg_sig_me_additional_data")))

    if push_tx:
        click.echo(f"Pushing tx...")
        resp = await full_node_client.push_tx(signed_sb)
        click.echo(resp)

        click.echo("Adding liquidity asset id to wallet...")
        resp = await wallet_client.create_wallet_for_existing_cat(bytes.fromhex(pair_liquidity_tail_hash))
        click.echo(resp)
        click.echo("Done.")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            signed_sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    wallet_client.close()
    await wallet_client.await_closed()
    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option('--rcat', is_flag=True, show_default=True, default=False, help="Sync rCAT pairs instead of normal CAT pairs.")
def sync_pairs(rcat):
    asyncio.run(_sync_pairs(rcat))


async def _sync_pairs(rcat):
    router_last_processed_id = get_config_item("rcat_router_last_processed_id" if rcat else "router_last_processed_id")
    if router_last_processed_id is None or len(router_last_processed_id) != 64:
        click.echo(
            "No router launcher id. Please either set it or launch a new router.")
        sys.exit(1)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    current_router_coin, latest_creation_spend, pairs = await sync_router(
        full_node_client, bytes.fromhex(router_last_processed_id), rcat
    )
    router_last_processed_id_new = current_router_coin.name().hex()
    click.echo(f"Last router id: {router_last_processed_id_new}")

    if len(pairs) != 0 or router_last_processed_id_new != router_last_processed_id:
        click.echo("New pairs found! Saving them...")
        router_last_processed_id = router_last_processed_id_new

        config = get_config()
        pairs_key = "rcat_pairs" if rcat else "pairs"
        if rcat:
            config["rcat_router_last_processed_id"] = router_last_processed_id
            config["rcat_pairs"] = config.get("rcat_pairs", {})

            for (tail_hash, pair_launcher_id, pair_hidden_puzzle_hash, pair_inverse_fee) in pairs:
                saved_pairs = config["rcat_pairs"].get(tail_hash, [])
                already_seen = False
                for saved_pair in saved_pairs:
                    if saved_pair["hidden_puzzle_hash"] == pair_hidden_puzzle_hash and saved_pair["inverse_fee"] == pair_inverse_fee:
                        already_seen = True
                        break
                if not already_seen:
                    if len(config["rcat_pairs"].get(tail_hash, [])) == 0:
                        config["rcat_pairs"][tail_hash] = []

                    config["rcat_pairs"][tail_hash].append({
                        "hidden_puzzle_hash": pair_hidden_puzzle_hash,
                        "inverse_fee": pair_inverse_fee,
                        "launcher_id": pair_launcher_id
                    })
        else:
            config["router_last_processed_id"] = router_last_processed_id
            config["pairs"] = config.get("pairs", {})
            for pair in pairs:
                if config["pairs"].get(pair[0], -1) == -1:
                    config["pairs"][pair[0]] = pair[1]

        save_config(config)

    click.echo("Bye!")
    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option("--asset-id", required=True, help='Asset id (TAIL hash) of token to be offered in pair (token-(r)XCH)')
def get_pair_info(asset_id):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)
    asyncio.run(_get_pair_info(asset_id))

# returns (hidden puzzle hash or None, inverse fee, pair launcher id)
def get_pair_data(asset_id_hex):
    rcat_pairs = get_config_item("rcat_pairs", asset_id_hex)
    pair_launcher_id = get_config_item("pairs", asset_id_hex)

    choices = []
    if pair_launcher_id is not None:
            possible_pairs.append((pair_launcher_id, None, 997))

    if rcat_pairs is not None:
        for rcat_pair in rcat_pairs:
            choices.append((rcat_pair["launcher_id"], bytes.fromhex(rcat_pair["hidden_puzzle_hash"]), rcat_pair["inverse_fee"]))
        
    if len(choices) == 1:
        return choices[0]
    elif len(choices) == 0:
        click.echo(
            "Corresponding pair launcher id not found in config - you might want to sync-pairs or create-pair.")
        sys.exit(1)

    remember_choice_key = f"remember_pair_{asset_id_hex}"
    remember_choice_value = get_config_item(remember_choice_key)
    if remember_choice_value is not None:
        for c in choices:
            if c[0] == remember_choice_value:
                return c

    print("Multiple pairs for the pair found - which one do you want to use?")
    for i, choice in enumerate(choices):
        print(f"{i}: launcher_id: {choice[0]}, hidden_puzzle_hash: {choice[1].hex()}, inverse_fee: {choice[2]}")
    
    user_choice = input("Enter the number of the pair you want to use (append an 'r' to remember your choice): ")

    user_choice_int = int(user_choice.replace("r", ""))
    choice = choices[user_choice_int]
    if 'r' in user_choice:
        config = get_config()
        config[remember_choice_key] = choice[0]
        save_config(config)
        print(f"Choice saved - if you want to undo, remove the 'remember_pair_{asset_id_hex}' entry from your config.json file.")

    return choice


async def _get_pair_info(token_tail_hash):
    click.echo("Getting info...")
    offer_str = ""

    pair_launcher_id, hidden_puzzle_hash, inverse_fee = get_pair_data(token_tail_hash)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    last_synced_pair_id = get_config_item("pair_sync", pair_launcher_id)
    last_synced_pair_id_not_none = last_synced_pair_id
    if last_synced_pair_id_not_none is None:
        last_synced_pair_id_not_none = pair_launcher_id

    current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        full_node_client, bytes.fromhex(last_synced_pair_id_not_none)
    )
    current_pair_coin_id = current_pair_coin.name().hex()
    click.echo(f"Current pair coin id: {current_pair_coin_id}")
    click.echo(f"Current pair coin puzzle hash: {current_pair_coin.puzzle_hash.hex()}")
    click.echo(f"Liquidity asset id: {pair_liquidity_tail_puzzle(bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()}")

    if hidden_puzzle_hash is not None:
        click.echo(f"Declared hidden puzzle hash: {hidden_puzzle_hash.hex()}")
        click.echo(f"Inverse fee: {inverse_fee} (fee: {(1000 - inverse_fee) / 10}%)")

    click.echo(f"XCH reserve: {pair_state['xch_reserve'] / 10 ** 12} XCH")
    click.echo(f"Token reserve: {pair_state['token_reserve'] / 1000} tokens")
    click.echo(f"Total liquidity: {pair_state['liquidity'] / 1000} tokens")

    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option("--asset-id", required=True, help='Asset id (TAIL hash) of token to be offered in pair (token-XCH)')
@click.option("--offer", default=None, help='Offer to build liquidity tx from. By default, a new offer will be generated. You can also provide the offer directly or the path to a file containing the offer.')
@click.option("--token-amount", default=0, help="If offer is none, this amount of tokens will be asked for in the offer. Unit is mojos (1 CAT = 1000 mojos).")
@click.option("--xch-amount", default=0, help="Only required if pair has no liquidity. If offer is none, this amount of XCH will be asked for in the generated offer. Unit is mojos.")
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and add liquidity CAT to wallet.")
@click.option('--fee', default=0, help='Fee to use for transaction; only used if offer is generated')
@click.option('--use-fee-estimate', is_flag=True, default=False, show_default=True, help='Estimate required fee when generating offer')
def deposit_liquidity(asset_id, offer, xch_amount, token_amount, push_tx, fee, use_fee_estimate):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)
    asyncio.run(_deposit_liquidity(asset_id, offer, xch_amount,
                token_amount, push_tx, fee, use_fee_estimate))


async def _deposit_liquidity(token_tail_hash, offer, xch_amount, token_amount, push_tx, fee, use_fee_estimate):
    click.echo("Depositing liquidity...")
    offer_str = ""

    pair_launcher_id, hidden_puzzle_hash, inverse_fee = get_pair_data(token_tail_hash)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    last_synced_pair_id = get_config_item("pair_sync", pair_launcher_id)
    last_synced_pair_id_not_none = last_synced_pair_id
    if last_synced_pair_id_not_none is None:
        last_synced_pair_id_not_none = pair_launcher_id

    current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        full_node_client, bytes.fromhex(last_synced_pair_id_not_none)
    )
    current_pair_coin_id = current_pair_coin.name().hex()
    click.echo(f"Current pair coin id: {current_pair_coin_id}")

    if offer is not None:
        click.echo("No need to generate new offer.")
        if os.path.isfile(offer):
            offer_str = open(offer, "r").read().strip()
        else:
            offer_str = offer
    else:
        click.echo("Generating new offer...")

        if token_amount == 0:
            click.echo("Please set ---token-amount to use this option.")
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(
            bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()
        click.echo(f"Liquidity asset id: {pair_liquidity_tail_hash}")

        liquidity_token_amount = token_amount
        if pair_state['liquidity'] != 0:
            liquidity_token_amount = pair_state['liquidity'] * \
                token_amount // pair_state['token_reserve']
            xch_amount = pair_state['xch_reserve'] * \
                token_amount // pair_state['token_reserve']

        if use_fee_estimate:
            fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
            print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

        sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))

        offer = None
        if not sage:
            wallets = await wallet_client.get_wallets(
                wallet_type=WalletType.CAT if hidden_puzzle_hash is None else WalletType.RCAT
            )
            token_wallet_id = next((_['id'] for _ in wallets if _[
                                'data'].startswith(token_tail_hash)), None)
            
            if hidden_puzzle_hash is not None:
                wallets = await wallet_client.get_wallets(wallet_type=WalletType.CAT)
            liquidity_wallet_id = next((_['id'] for _ in wallets if _[
                                    'data'].startswith(pair_liquidity_tail_hash)), None)

            if token_wallet_id is None or liquidity_wallet_id is None:
                click.echo(
                    "You don't have a wallet for the token and/or the pair liquidity token. Please set them up before using this command.")
                wallet_client.close()
                await wallet_client.await_closed()
                full_node_client.close()
                await full_node_client.await_closed()
                sys.exit(1)
        
            offer_dict = {}
            # also for liqiudity TAIL creation
            offer_dict[1] = - xch_amount - liquidity_token_amount
            offer_dict[token_wallet_id] = -token_amount
            offer_dict[liquidity_wallet_id] = liquidity_token_amount
            offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config, fee=fee)
            offer = offer_resp.offer

            wallet_client.close()
            await wallet_client.await_closed()
        else:
            offer = wallet_client.make_offer(
                [[pair_liquidity_tail_hash, None, liquidity_token_amount]],
                [
                    [bytes.fromhex(token_tail_hash), hidden_puzzle_hash, token_amount],
                    [None, None, xch_amount + liquidity_token_amount]
                ],
                fee,
                auto_import=False
            )


        offer_str = offer.to_bech32()
        open("offer.txt", "w").write(offer_str)

        click.echo("Offer successfully generated and saved to offer.txt.")

    xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
        full_node_client,
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        creation_spend,
        sb_to_aggregate
    )

    if last_synced_pair_id_on_blockchain != last_synced_pair_id:
        click.echo("Pair state updated since last sync; saving it...")
        config = get_config()
        config["pair_sync"] = config.get("pair_sync", {})
        config["pair_sync"][pair_launcher_id] = last_synced_pair_id_on_blockchain.hex()
        save_config(config)

    sb = await respond_to_deposit_liquidity_offer(
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        creation_spend,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        inverse_fee,
        pair_state["liquidity"],
        pair_state["xch_reserve"],
        pair_state["token_reserve"],
        offer_str,
        xch_reserve_coin,
        token_reserve_coin,
        token_reserve_lineage_proof
    )

    if sb_to_aggregate is not None:
        sb = SpendBundle.aggregate([sb, sb_to_aggregate])

    if push_tx:
        resp = input("Are you sure you want to broadcast this spend? (Yes): ")
        if resp == "Yes":
            click.echo(f"Pushing tx...")
            resp = await full_node_client.push_tx(sb)
            click.echo(resp)
            click.echo("Congrats on the rebase!")
        else:
            click.echo("That's not a clear 'Yes'!")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option("--asset-id", required=True, help='Asset id (TAIL hash) of token part of the pair (token-XCH)')
@click.option("--offer", default=None, help='Offer to build liquidity removal tx from. By default, a new offer will be generated. You can also provide the offer directly or the path to a file containing the offer.')
@click.option("--liquidity-token-amount", default=0, help="If offer is none, this amount of liqudity tokens will be included in the offer. Unit is mojos (1 CAT = 1000 mojos).")
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network.")
@click.option('--fee', default=0, help='Fee to use for transaction; only used if offer is generated')
@click.option('--use-fee-estimate', is_flag=True, default=False, show_default=True, help='Estimate required fee when generating offer')
def remove_liquidity(asset_id, offer, liquidity_token_amount, push_tx, fee, use_fee_estimate):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)
    asyncio.run(_remove_liquidity(asset_id, offer,
                liquidity_token_amount, push_tx, fee, use_fee_estimate))


async def _remove_liquidity(token_tail_hash, offer, liquidity_token_amount, push_tx, fee, use_fee_estimate):
    click.echo("Removing liquidity...")
    offer_str = ""

    pair_launcher_id, hidden_puzzle_hash, inverse_fee = get_pair_data(token_tail_hash)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    last_synced_pair_id = get_config_item("pair_sync", pair_launcher_id)
    last_synced_pair_id_not_none = last_synced_pair_id
    if last_synced_pair_id_not_none is None:
        last_synced_pair_id_not_none = pair_launcher_id

    current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        full_node_client, bytes.fromhex(last_synced_pair_id_not_none)
    )
    current_pair_coin_id = current_pair_coin.name().hex()
    click.echo(f"Current pair coin id: {current_pair_coin_id}")

    if offer is not None:
        click.echo("No need to generate new offer.")
        if os.path.isfile(offer):
            offer_str = open(offer, "r").read().strip()
        else:
            offer_str = offer
    else:
        click.echo("Generating new offer...")

        if liquidity_token_amount == 0:
            click.echo(
                "Please set ---liquidity-token-amount to use this option.")
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(
            bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()
        click.echo(f"Liquidity asset id: {pair_liquidity_tail_hash}")

        sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))

        token_amount = pair_state['token_reserve'] * \
            liquidity_token_amount // pair_state['liquidity']
        xch_amount = pair_state['xch_reserve'] * \
            liquidity_token_amount // pair_state['liquidity']

        offer = None
        if not sage:
            wallets = await wallet_client.get_wallets(wallet_type=WalletType.CAT if hidden_puzzle_hash is None else WalletType.RCAT)
            token_wallet_id = next((_['id'] for _ in wallets if _[
                                   'data'].startswith(token_tail_hash)), None)

            if hidden_puzzle_hash is not None:
                wallets = await wallet_client.get_wallets(wallet_type=WalletType.CAT)
            liquidity_wallet_id = next((_['id'] for _ in wallets if _[
                                       'data'].startswith(pair_liquidity_tail_hash)), None)

            if token_wallet_id is None or liquidity_wallet_id is None:
                click.echo(
                    "You don't have a wallet for the token and/or the pair liquidity token. Please set them up before using this command.")
                wallet_client.close()
                await wallet_client.await_closed()
                full_node_client.close()
                await full_node_client.await_closed()
                sys.exit(1)

            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

            offer_dict = {}
            # also ask for xch from liquidity cat burn
            offer_dict[1] = xch_amount + liquidity_token_amount
            offer_dict[token_wallet_id] = token_amount
            offer_dict[liquidity_wallet_id] = -liquidity_token_amount
            offer_resp = await wallet_client.create_offer_for_ids(offer_dict,  tx_config=tx_config,  fee=fee)
            offer = offer_resp.offer

            wallet_client.close()
            await wallet_client.await_closed()
        else:
            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

            offer = wallet_client.make_offer(
                [
                    [None, None, xch_amount + liquidity_token_amount],
                    [bytes.fromhex(token_tail_hash), hidden_puzzle_hash, token_amount]
                ],
                [[bytes.fromhex(pair_liquidity_tail_hash), None, liquidity_token_amount]],
                fee,
                auto_import=False
            )

        offer_str = offer.to_bech32()
        open("offer.txt", "w").write(offer_str)

        click.echo("Offer successfully generated and saved to offer.txt.")

    xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
        full_node_client,
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        creation_spend,
        sb_to_aggregate
    )

    if last_synced_pair_id_on_blockchain != last_synced_pair_id:
        click.echo("Pair state updated since last sync; saving it...")
        config = get_config()
        config["pair_sync"] = config.get("pair_sync", {})
        config["pair_sync"][pair_launcher_id] = last_synced_pair_id_on_blockchain.hex()
        save_config(config)

    sb = await respond_to_remove_liquidity_offer(
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        creation_spend,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        inverse_fee,
        pair_state["liquidity"],
        pair_state["xch_reserve"],
        pair_state["token_reserve"],
        offer_str,
        xch_reserve_coin,
        token_reserve_coin,
        token_reserve_lineage_proof
    )

    if sb_to_aggregate is not None:
        sb = SpendBundle.aggregate([sb, sb_to_aggregate])

    if push_tx:
        resp = input("Are you sure you want to broadcast this spend? (Yes): ")
        if resp == "Yes":
            click.echo(f"Pushing tx...")
            resp = await full_node_client.push_tx(sb)
            click.echo(resp)
            click.echo("We're extremely sorry to see your liquidity go :(")
        else:
            click.echo("That's not a clear 'Yes'!")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option("--asset-id", required=True, help='Asset id (TAIL hash) of token part of the pair (token-XCH)')
@click.option("--offer", default=None, help='Offer to build tx from. By default, a new offer will be generated. You can also provide the offer directly or the path to a file containing the offer.')
@click.option("--xch-amount", default=0, help="If offer is none, this amount of xch will be included in the offer. Unit is mojos.")
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the spend bundle to the network.")
@click.option('--fee', default=0, help='Fee to use for transaction; only used if offer is generated')
@click.option('--use-fee-estimate', is_flag=True, default=False, show_default=True, help='Estimate required fee when generating offer')
def xch_to_token(asset_id, offer, xch_amount, push_tx, fee, use_fee_estimate):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)
    asyncio.run(_xch_to_token(asset_id, offer, xch_amount,
                push_tx, fee, use_fee_estimate))


async def _xch_to_token(token_tail_hash, offer, xch_amount, push_tx, fee, use_fee_estimate):
    click.echo("Swapping XCH for token...")
    offer_str = ""

    pair_launcher_id, hidden_puzzle_hash, inverse_fee = get_pair_data(token_tail_hash)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    last_synced_pair_id = get_config_item("pair_sync", pair_launcher_id)
    last_synced_pair_id_not_none = last_synced_pair_id
    if last_synced_pair_id_not_none is None:
        last_synced_pair_id_not_none = pair_launcher_id

    current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        full_node_client, bytes.fromhex(last_synced_pair_id_not_none)
    )
    current_pair_coin_id = current_pair_coin.name().hex()
    click.echo(f"Current pair coin id: {current_pair_coin_id}")

    if offer is not None:
        click.echo("No need to generate new offer.")
        if os.path.isfile(offer):
            offer_str = open(offer, "r").read().strip()
        else:
            offer_str = offer
    else:
        click.echo("Generating new offer...")

        if xch_amount == 0:
            click.echo("Please set ---xch-amount to use this option.")
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(
            bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()
        click.echo(f"Liquidity asset id: {pair_liquidity_tail_hash}")

        sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))

        token_amount = inverse_fee * xch_amount * \
            pair_state['token_reserve'] // (1000 *
                                            pair_state['xch_reserve'] + inverse_fee * xch_amount)

        click.echo(
            f"You'll receive {token_amount / 1000} tokens from this trade.")
        if token_amount == 0:
            if not sage:
                wallet_client.close()
                await wallet_client.await_closed()
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        offer = None
        if not sage:
            wallets = await wallet_client.get_wallets(wallet_type=WalletType.CAT if hidden_puzzle_hash is None else WalletType.RCAT)
            token_wallet_id = next((_['id'] for _ in wallets if _[
                                   'data'].startswith(token_tail_hash)), None)

            if token_wallet_id is None:
                click.echo(
                    "You don't have a wallet for the token offered in the pair. Please set them up before using this command.")
                wallet_client.close()
                await wallet_client.await_closed()
                full_node_client.close()
                await full_node_client.await_closed()
                sys.exit(1)

            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

            offer_dict = {}
            offer_dict[1] = -xch_amount  # offer XCH
            offer_dict[token_wallet_id] = token_amount  # ask for token
            offer_resp = await wallet_client.create_offer_for_ids(offer_dict,  tx_config=tx_config, fee=fee)
            offer = offer_resp.offer

            wallet_client.close()
            await wallet_client.await_closed()
        else:
            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

            offer = wallet_client.make_offer(
                [[bytes.fromhex(token_tail_hash), hidden_puzzle_hash, token_amount]],
                [[None, None, xch_amount]],
                fee,
                auto_import=False
            )

        offer_str = offer.to_bech32()
        open("offer.txt", "w").write(offer_str)

        click.echo("Offer successfully generated and saved to offer.txt.")

    xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
        full_node_client,
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        creation_spend,
        sb_to_aggregate
    )

    if last_synced_pair_id_on_blockchain != last_synced_pair_id:
        click.echo("Pair state updated since last sync; saving it...")
        config = get_config()
        config["pair_sync"] = config.get("pair_sync", {})
        config["pair_sync"][pair_launcher_id] = last_synced_pair_id_on_blockchain.hex()
        save_config(config)

    sb = await respond_to_swap_offer(
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        creation_spend,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        inverse_fee,
        pair_state["liquidity"],
        pair_state["xch_reserve"],
        pair_state["token_reserve"],
        offer_str,
        xch_reserve_coin,
        token_reserve_coin,
        token_reserve_lineage_proof
    )

    if sb_to_aggregate is not None:
        sb = SpendBundle.aggregate([sb, sb_to_aggregate])

    if push_tx:
        resp = input("Are you sure you want to broadcast this spend? (Yes): ")
        if resp == "Yes":
            click.echo(f"Pushing tx...")
            resp = await full_node_client.push_tx(sb)
            click.echo(resp)
            click.echo("Enjoy your shiny new tokens!")
        else:
            click.echo("That's not a clear 'Yes'!")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option("--asset-id", required=True, help='Asset id (TAIL hash) of token part of the pair (token-XCH)')
@click.option("--offer", default=None, help='Offer to build tx from. By default, a new offer will be generated. You can also provide the offer directly or the path to a file containing the offer.')
@click.option("--token-amount", default=0, help="If offer is none, this amount of tokens will be included in the offer. Unit is mojos (1 CAT = 1000 mojos).")
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the spend bundle to the network.")
@click.option('--fee', default=0, help='Fee to use for transaction; only used if offer is generated')
@click.option('--use-fee-estimate', is_flag=True, default=False, show_default=True, help='Estimate required fee when generating offer')
def token_to_xch(asset_id, offer, token_amount, push_tx, fee, use_fee_estimate):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)
    asyncio.run(_token_to_xch(asset_id, offer, token_amount,
                push_tx, fee, use_fee_estimate))


async def _token_to_xch(token_tail_hash, offer, token_amount, push_tx, fee, use_fee_estimate):
    click.echo("Swapping token for XCH...")
    offer_str = ""

    pair_launcher_id, hidden_puzzle_hash, inverse_fee = get_pair_data(token_tail_hash)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    last_synced_pair_id = get_config_item("pair_sync", pair_launcher_id)
    last_synced_pair_id_not_none = last_synced_pair_id
    if last_synced_pair_id_not_none is None:
        last_synced_pair_id_not_none = pair_launcher_id

    current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        full_node_client, bytes.fromhex(last_synced_pair_id_not_none)
    )
    current_pair_coin_id = current_pair_coin.name().hex()
    click.echo(f"Current pair coin id: {current_pair_coin_id}")

    if offer is not None:
        click.echo("No need to generate new offer.")
        if os.path.isfile(offer):
            offer_str = open(offer, "r").read().strip()
        else:
            offer_str = offer
    else:
        click.echo("Generating new offer...")

        if token_amount == 0:
            click.echo("Please set ---token-amount to use this option.")
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(
            bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()
        click.echo(f"Liquidity asset id: {pair_liquidity_tail_hash}")

        sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))

        xch_amount = inverse_fee * token_amount * \
            pair_state['xch_reserve'] // (1000 *
                                          pair_state['token_reserve'] + inverse_fee * token_amount)

        click.echo(
            f"You'll receive {xch_amount / 1000000000000} XCH from this trade.")
        if token_amount == 0:
            if not sage:
                wallet_client.close()
                await wallet_client.await_closed()
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        offer = None
        if not sage:
            wallets = await wallet_client.get_wallets(wallet_type=WalletType.CAT if hidden_puzzle_hash is None else WalletType.RCAT)
            token_wallet_id = next((_['id'] for _ in wallets if _[
                                   'data'].startswith(token_tail_hash)), None)

            if token_wallet_id is None:
                click.echo(
                    "You don't have a wallet for the token offered in the pair. Please set them up before using this command.")
                wallet_client.close()
                await wallet_client.await_closed()
                full_node_client.close()
                await full_node_client.await_closed()
                sys.exit(1)

            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

            offer_dict = {}
            offer_dict[1] = xch_amount  # ask for XCH
            offer_dict[token_wallet_id] = -token_amount  # offer tokens
            offer_resp = await wallet_client.create_offer_for_ids(offer_dict,  tx_config=tx_config, fee=fee)
            offer = offer_resp.offer

            wallet_client.close()
            await wallet_client.await_closed()
        else:
            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")

            offer = wallet_client.make_offer(
                [[None, None, xch_amount]],
                [[bytes.fromhex(token_tail_hash), hidden_puzzle_hash, token_amount]],
                fee,
                auto_import=False
            )

        offer_str = offer.to_bech32()
        open("offer.txt", "w").write(offer_str)

        click.echo("Offer successfully generated and saved to offer.txt.")

    xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
        full_node_client,
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        creation_spend,
        sb_to_aggregate
    )

    if last_synced_pair_id_on_blockchain != last_synced_pair_id:
        click.echo("Pair state updated since last sync; saving it...")
        config = get_config()
        config["pair_sync"] = config.get("pair_sync", {})
        config["pair_sync"][pair_launcher_id] = last_synced_pair_id_on_blockchain.hex()
        save_config(config)

    sb = await respond_to_swap_offer(
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        creation_spend,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        inverse_fee,
        pair_state["liquidity"],
        pair_state["xch_reserve"],
        pair_state["token_reserve"],
        offer_str,
        xch_reserve_coin,
        token_reserve_coin,
        token_reserve_lineage_proof
    )

    if sb_to_aggregate is not None:
        sb = SpendBundle.aggregate([sb, sb_to_aggregate])

    if push_tx:
        resp = input("Are you sure you want to broadcast this spend? (Yes): ")
        if resp == "Yes":
            click.echo(f"Pushing tx...")
            resp = await full_node_client.push_tx(sb)
            click.echo(resp)
            click.echo("Enjoy your shiny new mojos!")
        else:
            click.echo("That's not a clear 'Yes'!")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option('--asset-id', required=True, help='Asset id (TAIL hash) of token to be offered in pair (token-XCH)')
@click.option('--hidden-puzzle-hash', required=False, help='If provided, an XCH-rCAT pair will be created instead.')
@click.option('--inverse-fee', required=False, default=993, help='Inverse fee for the pair - values other than 993 only allowed for rCAT pairs.')
@click.option("--offer", required=True, help='Offer to build tx from. Should contain CATs and 0.42 + 0.042 + 1 + [liquidity XCH] + [liquidity CAT] XCH.')
@click.option("--token-amount", required=True, help="CAT amount to deposit as initial liquidity. Unit is mojos (1 CAT = 1000 mojos).")
@click.option("--xch-amount", required=True, help="XCH amount to deposit as initial liquidity. Unit is mojos.")
@click.option("--liquidity-destination-address", required=True, help="Address to send liquidity tokens to.")
@click.option("--push-tx", is_flag=True, default=False, help="Push the tx to the network.")
def create_pair_with_initial_liquidity(
    asset_id,
    hidden_puzzle_hash,
    inverse_fee,
    offer,
    xch_amount,
    token_amount,
    liquidity_destination_address,
    push_tx
):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)

    if hidden_puzzle_hash is None and inverse_fee != 993:
        click.echo("Inverse fee cannot be something other than 993 for normal XCH-CAT pairs.")
        sys.exit(1)

    if hidden_puzzle_hash is not None and len(hidden_puzzle_hash) != 64:
        click.echo("Hidden puzzle hash must be 32 bytes.")
        sys.exit(1)

    if hidden_puzzle_hash is not None:
        hidden_puzzle_hash = bytes.fromhex(hidden_puzzle_hash)
    
    asyncio.run(
        _create_pair_with_initial_liquidity(
            asset_id,
            hidden_puzzle_hash,
            inverse_fee,
            offer,
            xch_amount,
            token_amount,
            liquidity_destination_address,
            push_tx
        )
    )


async def _create_pair_with_initial_liquidity(
    asset_id,
    hidden_puzzle_hash,
    inverse_fee,
    offer,
    xch_amount,
    token_amount,
    liquidity_destination_address,
    push_tx
):
    click.echo("Deploying pair AND depositing liquidity in the same tx - that's crazy!")
    offer_str = ""

    router_launcher_id = get_config_item("router_launcher_id")
    router_last_processed_id = get_config_item("router_last_processed_id")
    if hidden_puzzle_hash is not None:
        router_launcher_id = get_config_item("rcat_router_launcher_id")
        router_last_processed_id = get_config_item("rcat_router_last_processed_id")

    if router_launcher_id is None or router_last_processed_id is None:
        click.echo("Oops - looks like someone forgot to launch their router.")
        sys.exit(1)

    click.echo("But first, we do a little sync")
    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))
    current_router_coin, latest_creation_spend, pairs = await sync_router(
        full_node_client,
        bytes.fromhex(router_last_processed_id), 
        hidden_puzzle_hash is not None
    )
    router_last_processed_id_new = current_router_coin.name().hex()
    click.echo(f"Last router id: {router_last_processed_id_new}")

    if len(pairs) != 0 or router_last_processed_id_new != router_last_processed_id:
        click.echo("New pairs found! Saving them...")
        router_last_processed_id = router_last_processed_id_new

        config = get_config()
        pairs_key = "rcat_pairs" if hidden_puzzle_hash is not None else "pairs"
        if hidden_puzzle_hash is not None:
            config["rcat_router_last_processed_id"] = router_last_processed_id
            config["rcat_pairs"] = config.get("rcat_pairs", {})

            for (tail_hash, pair_launcher_id, pair_hidden_puzzle_hash, pair_inverse_fee) in pairs:
                saved_pairs = config["rcat_pairs"].get(tail_hash, [])
                already_seen = False
                for saved_pair in saved_pairs:
                    if saved_pair["hidden_puzzle_hash"] == pair_hidden_puzzle_hash and saved_pair["inverse_fee"] == pair_inverse_fee:
                        already_seen = True
                        break
                if not already_seen:
                    if len(config["rcat_pairs"].get(tail_hash, [])) == 0:
                        config["rcat_pairs"][tail_hash] = []

                    config["rcat_pairs"][tail_hash].append({
                        "hidden_puzzle_hash": pair_hidden_puzzle_hash,
                        "inverse_fee": pair_inverse_fee,
                        "launcher_id": pair_launcher_id
                    })
        else:
            config["router_last_processed_id"] = router_last_processed_id
            config["pairs"] = config.get("pairs", {})
            for pair in pairs:
                if config["pairs"].get(pair[0], -1) == -1:
                    config["pairs"][pair[0]] = pair[1]

        save_config(config)

    sb = await create_pair_with_liquidity(
        bytes.fromhex(asset_id),
        hidden_puzzle_hash,
        inverse_fee,
        offer,
        int(xch_amount),
        int(token_amount),
        liquidity_destination_address,
        bytes.fromhex(router_launcher_id),
        current_router_coin,
        latest_creation_spend,
        additional_data=bytes.fromhex(get_config_item("agg_sig_me_additional_data"))
    )

    if push_tx:
        resp = input("Are you sure you want to broadcast this spend? (Yes): ")
        if resp == "Yes":
            click.echo(f"Pushing tx...")
            resp = await full_node_client.push_tx(sb)
            click.echo(resp)
            click.echo("Enjoy your lp fees!")
        else:
            click.echo("That's not a clear 'Yes'!")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
@click.option("--asset-id", required=True, help='Asset id (TAIL hash) of token to be offered in pair (token-XCH)')
@click.option("--other-sb", required=True, help='JSON file containing the spend bundle that spends the hidden puzzle hash to send a message to this pair.')
@click.option("--offer", default=None, help='Offer to build liquidity tx from. By default, a new offer will be generated. You can also provide the offer directly or the path to a file containing the offer. Offer added CAT amount + 1 mojo.')
@click.option("--token-amount", default=0, help="Amount of tokens to *add* to the pair's reserve via rebase. Unit is mojos (1 CAT = 1000 mojos).")
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and add liquidity CAT to wallet.")
@click.option('--fee', default=0, help='Fee to use for transaction; only used if offer is generated')
@click.option('--use-fee-estimate', is_flag=True, default=False, show_default=True, help='Estimate required fee when generating offer')
def rebase_up(asset_id, other_sb, offer, token_amount, push_tx, fee, use_fee_estimate):
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)
    asyncio.run(_rebase_up(asset_id, other_sb, offer,
                token_amount, push_tx, fee, use_fee_estimate))


async def _rebase_up(token_tail_hash, other_sb, offer, token_amount, push_tx, fee, use_fee_estimate):
    click.echo("Rebasing UP...")
    offer_str = ""

    click.echo(f"Reading other spend bundle from '{other_sb}'...")
    other_sb = SpendBundle.from_json_dict(json.loads(open(other_sb, "r").read()))

    pair_launcher_id, hidden_puzzle_hash, inverse_fee = get_pair_data(token_tail_hash)

    if hidden_puzzle_hash is None:
        click.echo("Cannot rebase a CAT pair")
        sys.exit(1)

    full_node_client = await get_full_node_client(get_config_item("chia_root"), get_config_item("rpc_url"))

    last_synced_pair_id = get_config_item("pair_sync", pair_launcher_id)
    last_synced_pair_id_not_none = last_synced_pair_id
    if last_synced_pair_id_not_none is None:
        last_synced_pair_id_not_none = pair_launcher_id

    current_pair_coin, creation_spend, pair_state, sb_to_aggregate, last_synced_pair_id_on_blockchain = await sync_pair(
        full_node_client, bytes.fromhex(last_synced_pair_id_not_none)
    )
    current_pair_coin_id = current_pair_coin.name().hex()
    click.echo(f"Current pair coin id: {current_pair_coin_id}")

    if offer is not None:
        click.echo("No need to generate new offer.")
        if os.path.isfile(offer):
            offer_str = open(offer, "r").read().strip()
        else:
            offer_str = offer
    else:
        click.echo("Generating new offer...")

        if token_amount == 0:
            click.echo("Please set ---token-amount to use this option.")
            full_node_client.close()
            await full_node_client.await_closed()
            sys.exit(1)

        sage, wallet_client = await get_wallet_client(get_config_item("chia_root"), get_config_item("use_sage"))

        offer = None
        if not sage:
            wallets = await wallet_client.get_wallets(
                wallet_type=WalletType.CAT if hidden_puzzle_hash is None else WalletType.RCAT
            )
            token_wallet_id = next((_['id'] for _ in wallets if _[
                                'data'].startswith(token_tail_hash)), None)
            
            
            if token_wallet_id is None:
                click.echo(
                    "You don't have a wallet for the token. Please set them up before using this command.")
                wallet_client.close()
                await wallet_client.await_closed()
                full_node_client.close()
                await full_node_client.await_closed()
                sys.exit(1)

            if use_fee_estimate:
                fee = await get_fee_estimate(sb_to_aggregate, full_node_client)
                print(f"[!] Using estimated fee: {fee / 10 ** 12} XCH")
            offer_dict = {}
            offer_dict[token_wallet_id] = -token_amount
            offer_dict[1] = -1
            offer_resp = await wallet_client.create_offer_for_ids(offer_dict, tx_config=tx_config, fee=fee)
            offer = offer_resp.offer

            wallet_client.close()
            await wallet_client.await_closed()
        else:
            offer = wallet_client.make_offer(
                [],
                [
                    [bytes.fromhex(token_tail_hash), hidden_puzzle_hash, token_amount],
                    [None, None, 1]
                ],
                fee,
                auto_import=False
            )

        offer_str = offer.to_bech32()
        open("offer.txt", "w").write(offer_str)

        click.echo("Offer successfully generated and saved to offer.txt.")

    xch_reserve_coin, token_reserve_coin, token_reserve_lineage_proof = await get_pair_reserve_info(
        full_node_client,
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        creation_spend,
        sb_to_aggregate
    )

    if last_synced_pair_id_on_blockchain != last_synced_pair_id:
        click.echo("Pair state updated since last sync; saving it...")
        config = get_config()
        config["pair_sync"] = config.get("pair_sync", {})
        config["pair_sync"][pair_launcher_id] = last_synced_pair_id_on_blockchain.hex()
        save_config(config)

    sb = await respond_to_rebase_up_offer(
        bytes.fromhex(pair_launcher_id),
        current_pair_coin,
        creation_spend,
        bytes.fromhex(token_tail_hash),
        hidden_puzzle_hash,
        inverse_fee,
        pair_state["liquidity"],
        pair_state["xch_reserve"],
        pair_state["token_reserve"],
        offer_str,
        xch_reserve_coin,
        token_reserve_coin,
        token_reserve_lineage_proof,
        other_sb
    )

    if sb_to_aggregate is not None:
        sb = SpendBundle.aggregate([sb, sb_to_aggregate])

    if push_tx:
        resp = input("Are you sure you want to broadcast this spend? (Yes): ")
        if resp == "Yes":
            click.echo(f"Pushing tx...")
            resp = await full_node_client.push_tx(sb)
            click.echo(resp)
            click.echo("Enjoy your lp fees!")
        else:
            click.echo("That's not a clear 'Yes'!")
    else:
        open("spend_bundle.json", "w").write(json.dumps(
            sb.to_json_dict(), sort_keys=True, indent=4))
        click.echo("Spend bundle written to spend_bundle.json.")
        click.echo("Use --push-tx to broadcast this spend.")

    full_node_client.close()
    await full_node_client.await_closed()


if __name__ == "__main__":
    cli.add_command(config_node)
    cli.add_command(test_node_config)
    cli.add_command(launch_router)
    cli.add_command(set_routers)
    cli.add_command(launch_test_token)
    cli.add_command(create_pair)
    cli.add_command(sync_pairs)
    cli.add_command(get_pair_info)
    cli.add_command(deposit_liquidity)
    cli.add_command(remove_liquidity)
    cli.add_command(xch_to_token)
    cli.add_command(token_to_xch)
    cli.add_command(rebase_up)
    cli.add_command(create_pair_with_initial_liquidity)
    cli()
