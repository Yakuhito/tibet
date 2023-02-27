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
        ret = ret[arg]
    
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
        print("Use a preset or fill out all options.")
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

    coins = await wallet_client.select_coins(2, 1) # wallet id 1, amount 2
    if len(coins) > 1:
        click.echo("Really? You have a one-mojo coin?!")
        sys.exit(1)

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
        config["router_last_processed_id"] = ""
        save_config(config)
        click.echo("Done.")
        click.echo("Don't forget to sync-pairs now!")
    else:
        click.echo("Here's your spend bundle:")
        click.echo(str(signed_sb))
        click.echo("Use --push-tx to push this spend.")

    wallet_client.close()
    await wallet_client.await_closed()

@click.command()
def launch_test_token():
    pass # todo

@click.command()
def launch_pair():
    pass # todo

@click.command()
def sync_pairs():
    asyncio.run(_sync_pairs())

async def _sync_pairs():
    router_last_processed_id = get_config_item("router_last_processed_id")
    if router_last_processed_id is None or len(router_last_processed_id) != 32:
        router_last_processed_id = get_config_item("router_launcher_id")
        if router_last_processed_id is None:
            click.echo("No router launcher id. Please either set it or launch a new router.")
            os.exit(1)
    
    full_node_client = await get_full_node_client(get_config_item("chia_root"))
    resp = await full_node_client.get_blockchain_state()
    print(resp) # todo
    full_node_client.close()
    await full_node_client.await_closed()

if __name__ == "__main__":
    cli.add_command(config_node)
    cli.add_command(test_node_config)
    cli.add_command(launch_router)
    cli.add_command(launch_pair)
    cli.add_command(sync_pairs)
    cli()