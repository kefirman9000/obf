# Changelog

## 1.1.0
**Market context: the bots watch the market around them**

- **Watched tickers** (left panel, "Market context"): tickers the bots watch but never trade. Default: SPY, VIXY,
  TLT and MSFT. The free data feed has no VIX index, so VIXY (an ETF that follows VIX futures) stands in for it. Edit
  the list from the card or Settings > Learning (up to 8).
- **Context studies**: each bot can evolve up to 3 rules on the watched tickers, either a move rule ("VIXY up 1.5% over
  10 decisions votes against buying") or a full strategy run on that ticker's chart ("TLT trend-follower saying buy votes
  for buying"). Each rule also learns its direction: whether that ticker rising is good or bad for its trades. When the
  market around a stock looks bullish, the bot won't open a new put on it.
- **Graded in hindsight**: every trade a context study held back is checked afterwards, per watched ticker. Rules that
  saved money spread to children; rules that blocked winners fade out.
- **"What they learned"** screen (Tools, or the card): per watched ticker, how many bots study it, how many trades it
  judged, what it saved or cost, and the best rule so far.
- The context tickers also feed the Slow farm, Training camp, Free roam and backtests, so the farm can learn these
  reactions from months of history (lined up bar by bar with each traded ticker).

## 1.0.0
**OBF: the bot farm, for options**

Built on CBBF (the crypto bot farm), with everything it has: the dragons, dens, breeding, studies, never-rules,
islands, seasons, the Slow farm, the Training camp, Free roam, the Bot Lab, the Library and Hall of Fame.

- **Calls and puts**: the bots read stock charts (SPY, QQQ, AAPL, NVDA, TSLA...) and act through options. A buy signal
  buys a call (or closes a put), a sell signal sells the call (or buys a put).
- **Option genes** every bot evolves: calls only, puts only or both; days to expiry (1 to 60); how far out of the money
  (0 to 12%); how many days before expiry to get out. Their own stops and targets work on the premium paid.
- **Fair practice pricing**: contracts are priced with Black-Scholes from each stock's recent swings, or from the live
  implied volatility once you've opened its option chain. Time decay, the bid/ask spread and expiry all count, so a bot
  that is right too slowly still loses.
- **Options tab**: live option chains with bid, ask, implied volatility, delta and theta for each strike, colour-coded
  by moneyness; buy a contract by hand; a watchlist of contracts.
- **Contracts in the portfolio**: each holding shows the contract, days left, value, profit and its greeks (click
  "details"). Every contract is closed the day before it expires.
- **Alpaca**: prices, history and option chains come from Alpaca (a free paper account is enough). LIVE mode trades
  your Alpaca account: with a paper key that's Alpaca's pretend money, with a live key it's real (type LIVE to confirm).
  Orders are limit orders on the listed contract closest to what the bots want.
- **Market hours**: the farm only trades while the market is open; outside hours Free roam and the Training camp keep
  learning from the past.
- Practice starts with $10,000 (one contract often costs a few hundred dollars), and the risk styles use stops and
  targets suited to option premiums (Balanced: stop 50%, target 100%).
