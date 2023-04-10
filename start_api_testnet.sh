#!/bin/bash

export TIBETSWAP_LAUNCHER_ID="d63637fea544958c0e9ce7b6cab2e517b5910980da7fc1a7a734ce0f2e236cd2"
export TIBETSWAP_CURRENT_ID="d63637fea544958c0e9ce7b6cab2e517b5910980da7fc1a7a734ce0f2e236cd2"
export TIBETSWAP_NETWORK="testnet10"
export FIREACADEMYIO_LEAFLET_URL=$(cat /home/yakuhito/fireacademyio_leaflet_url)
export TAILDATABASE_TAIL_INFO_URL=$(cat /home/yakuhito/taildatabase_tail_info_url)
uvicorn api:app --reload
