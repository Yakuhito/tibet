import click
import json
import sys
import os
import asyncio
from tibet_lib import *
from private_key_things import *

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
            click.echo(f"Could not find {'->'.join(args)} - is this an error on your part?")
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
    open("config.json", "w").write(json.dumps(config, sort_keys=True, indent=4))


@click.command()
@click.option('--chia-root', default=None, help='Chia root directory (e.g., ~/.chia/mainnet)')
@click.option('--use-preset', default='custom', type=click.Choice(['custom', 'simulator', 'testnet10', 'mainnet'], case_sensitive=False))
def config_node(chia_root, use_preset):
    if use_preset == 'custom' and (chia_root is None or full_node_rpc_port is None or wallet_rpc_port is None):
        click.echo("Use a preset or fill out all options.")
        sys.exit(1)
    
    if use_preset == "mainnet":
        chia_root = "~/.chia/mainnet"
    elif use_preset == "testnet10":
        chia_root = "~/.chia/testnet10"
    elif use_preset == "simulator":
        chia_root = "~/.chia/simulator/main"
    
    chia_root = os.path.expanduser(chia_root)

    config = get_config()
    config["chia_root"] = chia_root
    save_config(config)
    click.echo("Config updated and saved successfully.")


@click.command()
def test_node_config():
    asyncio.run(_test_node_config())

async def _test_node_config():
    full_node_client = await get_full_node_client(get_config_item("chia_root"))
    full_node_client_status = await full_node_client.healthz()
    click.echo("full node client... " + str(full_node_client_status))

    full_node_client.close()
    await full_node_client.await_closed()

    wallet_client = await get_wallet_client(get_config_item("chia_root"))
    wallet_client_status = await wallet_client.healthz()
    click.echo("wallet client... " + str(wallet_client_status))

    wallet_client.close()
    await wallet_client.await_closed()


@click.command()
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and update launcher is in config.")
def launch_router(push_tx):
    asyncio.run(_launch_router(push_tx))

async def _launch_router(push_tx):
    wallet_client = await get_wallet_client(get_config_item("chia_root"))

    coins = await wallet_client.select_coins(2, 1, min_coin_amount=2) # wallet id 1, amount 2

    coin = coins[0]
    coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)

    click.echo(f"Using coin 0x{coin.name().hex()}...")

    launcher_id, sb = await launch_router_from_coin(coin, coin_puzzle)
    click.echo(f"Router launcher id: {launcher_id}")

    signed_sb = await sign_spend_bundle(wallet_client, sb)

    if push_tx:
        click.echo(f"Pushing tx...")
        full_node_client = await get_full_node_client(get_config_item("chia_root"))
        resp = await full_node_client.push_tx(signed_sb)
        click.echo(resp)
        full_node_client.close()
        await full_node_client.await_closed()

        click.echo("Saving config...")
        config = get_config()
        config["router_launcher_id"] = launcher_id
        config["router_last_processed_id"] = launcher_id
        config["pairs"] = {}
        save_config(config)
        click.echo("Done.")
    else:
        click.echo("Here's your spend bundle:")
        click.echo(str(signed_sb))
        click.echo("Use --push-tx to push this spend.")

    wallet_client.close()
    await wallet_client.await_closed()

@click.command()
@click.option('--amount', default=1000000, help='Amount, in CATs (1 CAT = 1000 mojos)')
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and add cat to wallet.")
def launch_test_token(amount, push_tx):
    asyncio.run(_launch_test_token(amount, push_tx))


async def _launch_test_token(amount, push_tx):
    click.echo(f"Creating test CAT with a supply of {amount} ({amount * 1000} mojos used)...")
    wallet_client = await get_wallet_client(get_config_item("chia_root"))

    coins = await wallet_client.select_coins(amount * 1000, 1, min_coin_amount=amount * 1000) # wallet id 1 = XCH

    coin = coins[0]
    coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)

    click.echo(f"Using coin 0x{coin.name().hex()}...")

    tail_id, sb = await create_test_cat(amount, coin, coin_puzzle)
    click.echo(f"Token asset id: {tail_id}")

    signed_sb = await sign_spend_bundle(wallet_client, sb)

    if push_tx:
        click.echo(f"Pushing tx...")
        full_node_client = await get_full_node_client(get_config_item("chia_root"))
        resp = await full_node_client.push_tx(signed_sb)
        click.echo(resp)
        full_node_client.close()
        await full_node_client.await_closed()

        click.echo("Adding asset id to wallet...")
        resp = await wallet_client.create_wallet_for_existing_cat(bytes.fromhex(tail_id))
        click.echo(resp)
        click.echo("Done.")
    else:
        click.echo("Here's your spend bundle:")
        click.echo(str(signed_sb))
        click.echo("Use --push-tx to push this spend.")

    wallet_client.close()
    await wallet_client.await_closed()


@click.command()
@click.option('--asset-id', required=True, help='Asset id (TAIL hash) of token to be offered in pair (token-XCH)')
@click.option("--push-tx", is_flag=True, show_default=True, default=False, help="Push the signed spend bundle to the network and add liquidity CAT to wallet.")
def create_pair(asset_id, push_tx):
    # very basic check to prevent most mistakes
    if len(asset_id) != 64:
        click.echo("Oops! That asset id doesn't look right...")
        sys.exit(1)

    asyncio.run(_create_pair(asset_id, push_tx))


async def _create_pair(tail_hash, push_tx):
    click.echo(f"Creating pair for {tail_hash}...")

    router_launcher_id = get_config_item("router_launcher_id")
    router_last_processed_id = get_config_item("router_last_processed_id")
    if router_launcher_id is None or router_last_processed_id is None:
        click.echo("Oops - looks like someone forgot to launch their router.")
        sys.exit(1)
    
    click.echo("But first, we do a little sync")
    full_node_client = await get_full_node_client(get_config_item("chia_root"))
    current_router_coin, latest_creation_spend, pairs = await sync_router(full_node_client, router_last_processed_id)
    router_last_processed_id_new = current_router_coin.name().hex()
    click.echo(f"Last router id: {router_last_processed_id_new}")

    if len(pairs) != 0 or router_last_processed_id_new != router_last_processed_id:
        click.echo("New pairs found! Saving them...")
        router_last_processed_id = router_last_processed_id_new

        config = get_config()
        config["router_last_processed_id"] = router_last_processed_id
        config["pairs"] = config.get("pairs", {})
        for pair in pairs:
            if config["pairs"].get(pair[0], -1) == -1:
                config["pairs"][pair[0]] = pair[1]
        save_config(config)

    wallet_client = await get_wallet_client(get_config_item("chia_root"))
    coins = await wallet_client.select_coins(2, 1, min_coin_amount=2) # wallet id 1 = XCH

    coin = coins[0]
    coin_puzzle = await get_standard_coin_puzzle(wallet_client, coin)

    click.echo(f"Using coin 0x{coin.name().hex()}...")

    pair_launcher_id, sb = await create_pair_from_coin(
        coin,
        coin_puzzle,
        tail_hash,
        router_launcher_id,
        current_router_coin,
        latest_creation_spend
    )
    click.echo(f"Pair launcher id: {pair_launcher_id}")

    pair_liquidity_tail_hash = pair_liquidity_tail_puzzle(bytes.fromhex(pair_launcher_id)).get_tree_hash().hex()
    click.echo(f"Liquidity asset id: {pair_liquidity_tail_hash}")

    signed_sb = await sign_spend_bundle(wallet_client, sb)

    if push_tx:
        click.echo(f"Pushing tx...")
        resp = await full_node_client.push_tx(signed_sb)
        click.echo(resp)
        
        click.echo("Adding liquidity asset id to wallet...")
        resp = await wallet_client.create_wallet_for_existing_cat(bytes.fromhex(pair_liquidity_tail_hash))
        click.echo(resp)
        click.echo("Done.")
    else:
        click.echo("Here's your spend bundle:")
        click.echo(str(signed_sb))
        click.echo("Use --push-tx to push this spend.")

    wallet_client.close()
    await wallet_client.await_closed()
    full_node_client.close()
    await full_node_client.await_closed()


@click.command()
def sync_pairs():
    asyncio.run(_sync_pairs())


async def _sync_pairs():
    router_last_processed_id = get_config_item("router_last_processed_id")
    if router_last_processed_id is None or len(router_last_processed_id) != 64:
        click.echo("No router launcher id. Please either set it or launch a new router.")
        sys.exit(1)
    
    full_node_client = await get_full_node_client(get_config_item("chia_root"))

    current_router_coin, latest_creation_spend, pairs = await sync_router(full_node_client, router_last_processed_id)
    router_last_processed_id_new = current_router_coin.name().hex()
    click.echo(f"Last router id: {router_last_processed_id_new}")

    if len(pairs) != 0 or router_last_processed_id_new != router_last_processed_id:
        click.echo("New pairs found! Saving them...")
        router_last_processed_id = router_last_processed_id_new

        config = get_config()
        config["router_last_processed_id"] = router_last_processed_id
        config["pairs"] = config.get("pairs", {})
        for pair in pairs:
            if config["pairs"].get(pair[0], -1) == -1:
                config["pairs"][pair[0]] = pair[1]
        save_config(config)

    click.echo("Bye!")
    full_node_client.close()
    await full_node_client.await_closed()


if __name__ == "__main__":
    cli.add_command(config_node)
    cli.add_command(test_node_config)
    cli.add_command(launch_router)
    cli.add_command(launch_test_token)
    cli.add_command(create_pair)
    cli.add_command(sync_pairs)
    cli()