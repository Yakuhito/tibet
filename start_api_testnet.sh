#!/bin/bash

export TIBETSWAP_LAUNCHER_ID="d037e35cc7269df10e45d0d152d2ff53d26f318adf5ea20578e5cfb80b5b2a71"
export TIBETSWAP_NETWORK="testnet10"
export FIREACADEMYIO_LEAFLET_URL=$(cat /home/yakuhito/fireacademyio_leaflet_url)
export TAILDATABASE_TAIL_INFO_URL=$(cat /home/yakuhito/taildatabase_tail_info_url)
uvicorn api:app --reload
