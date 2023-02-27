import click
import json
import sys
import os

@click.group()
def cli():
    pass


def get_config():
    try:
        config = json.loads(open("config.json", "r").read())
        return config
    except:
        open("config.json", "w").write("{}")
        return {}


def save_config(config):
    open("config.json", "w").write(json.dumps(config, sort_keys=True, indent=4))


@click.command()
@click.option('--chia-root', default=None, help='Chia root directory (e.g., ~/.chia/mainnet)')
@click.option('--full-node-rpc-port', default=None, help='Chia wallet RPC port')
@click.option('--wallet-rpc-port', default=None, help='Chia full node RPC port')
@click.option('--use-preset', default='custom', type=click.Choice(['custom', 'simulator', 'testnet10', 'mainnet'], case_sensitive=False))
def config_node(chia_root, full_node_rpc_port, wallet_rpc_port, use_preset):
    if use_preset == 'custom' and (chia_root is None or full_node_rpc_port is None or wallet_rpc_port is None):
        print("Use a preset or fill out all options.")
        sys.exit(1)
    
    if use_preset == "mainnet":
        chia_root = "~/.chia/mainnet"
        full_node_rpc_port = 8555
        wallet_rpc_port = 9256
    elif use_preset == "testnet10":
        chia_root = "~/.chia/testnet10"
        full_node_rpc_port = 8555
        wallet_rpc_port = 9256 
    elif use_preset == "simulator":
        chia_root = "~/.chia/simulator/main"
        full_node_rpc_port = 10568
        wallet_rpc_port = 11269

    chia_root = os.path.expanduser(chia_root)

    config_node_obj = {
        "chia_root": chia_root,
        "full_node_rpc_port": full_node_rpc_port,
        "wallet_rpc_port": wallet_rpc_port
    }
    config = get_config()
    config["node"] = config_node_obj
    save_config(config)
    click.echo("Config updated and saved successfully.")


@click.command()
def launch_router():
    click.echo("Launching router!")

if __name__ == "__main__":
    cli.add_command(config_node)
    cli.add_command(launch_router)
    cli()