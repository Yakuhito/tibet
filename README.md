# tibet

Also referred to as `yakSwap`, `tibet` is an attempt to recreate [`Uniswap V1`](https://github.com/Uniswap/v1-contracts) on the Chia blockchain.

Please see [contributors](CONTRIBUTORS.md) to know who to thank to.

# Explanations

## Singletons

Both the router and the pair puzzles need to maintain a global state. Using singletons as a top layer is the best approach. The one-spend-per-block can either be overcome by a) waiting for the multi-spend singleton feature to get released or b) looking up in the mempool for the tx that spends the last version of the singleton and adding your transaction to the spend-bundle (or having a service that does all that).

## Router

A router is necessary to keep track of all deployed pair singletons.
 * It's easier to just have a place to look for all deployed singletons
 * By having a deployer, we can make sure that the code in each pair is correct (singleton + inner puzzle)
 * Each pair's singleton launcher id can be calculated using the singleton 'state id' (coin id) that created it + information required for the pair puzzle hash (probably just the two token TAILs)

## Token-token Swaps

Like Uniswap V1, I chose to go with XCH-token pairs instead of token-token (and having 'Wrapped Chia'). This is a proof-of-concept and future versions (e.g., V2) might implement it though. I made this choice for practicality: the pair puzzle is easier and the majority of trades / pairs happen with XCH being on one side of the trade anyway.

## Offers

Theoretically, there is a way of having a service that does somr 'magic' in the backend and gives the user an offer that executes a trade on a pair. However, it's pretty complex and the offer changes with each trade made on the selected pair.

## Orders on Pairs

Unlike Uniswap, the router does not allow users to make trades on pairs. Since we're using the coin set model, there's significant cost to using an additional coin for every trade (think of scalability: the router coin would be spent for every trade ever). As such, only the pair singleton is modified when a trade happens.

## High Fees

'But uniswap has a fee of 0.3%' Yes, but this is not Uniswap. The ecosystem is small and devs need to be paid. 0.3% is a lot when your daily volume is over $900 million; 7% is very little when daily volume is $10. Yes, fees should be reduced in the future. Until then, thank you for (forcefully) contributing to the development of the next version.