# tibet

Also referred to as `yakSwap`, `tibet` is an attempt to recreate [`Uniswap V1`](https://github.com/Uniswap/v1-contracts) on the Chia blockchain.

To see how to use on testnet, see [testnet10.md](testnet10.md).

# Explanations

Testers: see [TESTING.md](TESTING.md), [Security Overview Presentation](https://pitch.com/public/0dded5d1-0151-4e77-b4f8-bcc1706317a6)

## Singletons

The pair puzzles need to maintain a global state that only makes *valid* transitions. Using singletons as a top layer is the best approach. The one-spend-per-block can either be overcome by a) waiting for the multi-spend singleton feature to get released or b) looking up in the mempool for the tx that spends the last version of the singleton and adding your transaction to the spend-bundle (or having a service that does all that).

## Router

A router is necessary to keep track of all deployed pair singletons.
 * It's easier to just have a place to look for all deployed singletons
 * By having a deployer, we can make sure that the code in each pair is correct (singleton + inner puzzle)
 * Each pair's singleton launcher id can be calculated using the singleton 'state id' (coin id) that created it + information required for the pair puzzle hash (probably just the token TAIL)
 * The router also ensures the initial state of a given pair singleton is valid (liquidity = xch_reserve = token_reserve = 0).

## Token-token Swaps

I chose to go with XCH-token pairs instead of token-token (and having 'Wrapped Chia'). This is a proof-of-concept and future versions (e.g., V2) might implement token-token pairs. The majority of trades will probably happen with XCH being on one side of the trade anyway. If you really need a token-token swap, simply go through token1-XCH and XCH-token2. You'll pay twice the liquidity fee, but the amount is negligible at this point. Also, liquidity is a big pro - users can supply liquidity for a token and get rewarded each time it's traded.

## Zap and Other Things

This is Chia, so you can chain actions together. For example, you can have a transaction where x XCH get supplied as liquidity without supplying the other token - under the hood, it swaps about 50% of x to the other token and then supplies liquidity to the pair. Or you can have token1-token2 swaps by grouping 2 swaps in the same spend bundle. These things will probably not be offered until there's demand for them, but no-one's preventing any developer fromimplementing them before that.

## Offers

The pair code leverages offers code (`settlement_payments.clvm`) to verify deposits (re-create reserves). The initial code was also designed to build transactions (spend bundles) in response to offers. Having offers is just safer - if the price changes too much, the offer will become invalid. The cool thing is that the offer will be valid again if the price 'recovers' - this is a thing I need to think more about :)

## Trade Orders on Pairs

Unlike Uniswap, the router does not allow users to make trades on pairs. Since we're using the coin set model, there's significant cost to using an additional coin for every trade (think of scalability: the router coin would be spent for every trade ever). As such, only the pair singleton is modified when a trade happens. This means that trades for different pairs are executed in parallel, without influencing one another (yay!). 

## High Fees

'But uniswap has a fee of 0.3% and that goes to liquidity providers' Yes, but this is not Uniswap. The ecosystem is small and good incentives need to be put in place. 0.3% is a lot when your daily volume is over $900 million; 50% is very little when daily volume is $10. Yes, fees should be reduced in the future. Until then, thank you for (forcefully) contributing to the development of the Chia ecosystem. Also, you might end up paying even more fees for Uniswap in the form of slippage, which is impossible here. The current fee candidate is 0.7% and I'm open to discussing it until we deploy the router on mainnet, which sets the fee in stone (i.e., the router needs to be re-deployed and liquiditymoved to new pairs if we want to change the fee).

## Flash Loans

Each transaction, token and XCH reserves are burned (destroyed, spent) and then new reserve coins are asserted (via  the settlement payments - just like in offers!). Since everything happens at the same time during a block, you can do whatever you want with all the pair's reserves as long as you 'leave the right amount' at the end of the tx. What's more, I modified the `p2_singleton` puzzle into one that allows anyone to add extra output conditions - this means that you truly have full control over the reserves.

## Imports

Why do imports look like they do? `isort [file].py --split-on-trailing-comma`

## Higher SPS (Swaps per Second)

If a greater number of swaps per second is really required, one can come up with a sequencer that takes all offers at 'convenient' prices, aggregates them, and then only spends the pair singleton once (using the aggregated offer). This should significantly reduce the overall transaction cost (compared to spending the singleton for each trade), which means that more trades can fit in one single block!

# Special Thanks

This project benefited from the goodwill of multiple Chia community members. Without them, the project wouldn't be where it is today.

Please note that their mention here does not represent their endorsement or their company's; these people simply helped someone who needed it. And for that, I am forever thankful.



| Username                                                                                                                            | Most Notable Contribution(s)                                                                                                       |
|-------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| [dimitry](https://twitter.com/cityu_dimitry)                                                                                        | Shared his team's AMM design and code w/ me; A lot of support                                                                      |
| [jde5011](https://twitter.com/jde5011)                                                                                              | Had a meeting to discuss security posture/opsec best practices for TibetSwap; Recorded the presentation and shared it internally!  |
| [trepca](https://twitter.com/trepca)                                                                                                | Answered (a lot of) questions about testing; Took a look at the tests, provided some code that took them to the next level         |
| [jm](https://twitter.com/XCHcentral_jm) & [kt](https://twitter.com/XCHcentral_kt) from [XCHcentral](https://twitter.com/XCHcentral) | Designed the logo that won the logo competition & is currently used by TibetSwap.                                                  |
| [hoffmang](https://twitter.com/hoffmang)                                                                                            | Described this project as 'a functional AMM' when talking to Bram during a SF Chia Meetup (I was there!) -> motivation             |
| [quexington](https://github.com/quexington)                                                                                         | Took a quick look at the chialisp code, sent short message that described how to significantly improve it. Left me speechless.     |
| [RightSexyOrc](https://twitter.com/RightSexyOrc)                                                                                    | Pull request [#4](https://github.com/Yakuhito/tibet/pull/4) - spotted a typo in README.md.                                         |
| [NamesDAO](https://twitter.com/https://twitter.com/theNamesdao)                                                                     | Gave us a lot of NAME tokens as a development grant. Thank you!                                                                    |
