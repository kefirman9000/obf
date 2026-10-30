# Changelog

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
