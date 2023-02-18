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
 * Each pair's singleton launcher id can be calculated using the singleton 'state id' (coin id) that created it + information required for the pair puzzle hash (probably just the token TAIL)

## Token-token Swaps

Like Uniswap V1, I chose to go with XCH-token pairs instead of token-token (and having 'Wrapped Chia'). This is a proof-of-concept and future versions (e.g., V2) might implement it. I made this choice for practicality: the pair puzzle is easier and the majority of trades / pairs happen with XCH being on one side of the trade anyway. If token-token swaps need to happen, simply go through token1-XCH and XCH-token2. You'll pay twice the fee, but the amount is negligible at this point. Also, liquidity is a big pro - users can supply liquidity for a token and get rewarded each time it's traded.

## Zap and Other Things

This is Chia, so you can chaing actions together. For example, you can have a transaction where x XCH get supplied as liquidity without supplying the other token - under the hood, it swaps about 50% of x to the other token and then supplies liquidity to the pair. Or you can have token1-token2 swaps by grouping 2 swaps in the same spend bundle. These things will probably not be offered until there's demand for them, but no-one's preventing any developer fromimplementing them before that.

## Offers

The pair code leverages offers code (`settlement_payments.clvm`) to verify deposits (re-create reserves). Tehnically speaking, the code works with offers, and offers can be generated to simulate trades. However, it's important to note that the offer changes each time a trade is executed on a pair (but hey, when you sign it, at least you know there's no slippage - if the price changes, the transaction will become invalid forever).

## Orders on Pairs

Unlike Uniswap, the router does not allow users to make trades on pairs. Since we're using the coin set model, there's significant cost to using an additional coin for every trade (think of scalability: the router coin would be spent for every trade ever). As such, only the pair singleton is modified when a trade happens. This means that trades for different pairs are executed in parallel, without influencing one another (yay!). 

## High Fees

'But uniswap has a fee of 0.3% and that goes to liquidity providers' Yes, but this is not Uniswap. The ecosystem is small and good incentives need to be put in place. 0.3% is a lot when your daily volume is over $900 million; 50% is very little when daily volume is $10. Yes, fees should be reduced in the future. Until then, thank you for (forcefully) contributing to the development of the Chia ecosystem.

## Flash Loans
Each transaction, token and XCH reserves are burned (destroyed, spent) and then new reserve coins are asserted (via  the settlement payments - just like in offers!). Since everything happens at the same time during a block, you can do whatever you want with all the pair's reserves as long as you 'leave the right amount' at the end of the tx. This is, in my opinion, the equivalent of a traditional flash loan.