# Changelog

## 1.6.0
**Expiry guard, day-trade guard, real fees, liquidity filter**

- **Expiry guard**: every contract is sold a set number of trading days before it expires (default 2: Wednesday for a
  Friday expiry), so nothing you bought is ever auto-exercised into 100 shares. It runs every minute whenever OBF is
  open, even with the bot stopped, and keeps retrying until the contract sells. On expiry day, as a last resort: IBKR is
  told NOT to exercise anything still held (3:40 pm); with Alpaca, a call still held at 1 pm brings up a warning to
  email Alpaca for a Do Not Exercise before 3 pm (Alpaca handles puts itself). Closing OBF while holding a contract near
  expiry asks whether to sell it first. Bots never buy a contract inside the guard's window.
- **Day-trade guard** (accounts under $25,000): once 3 day trades are used in 5 business days, OBF opens no new contracts
  and holds today's contracts overnight instead of selling them for a 4th, so the broker doesn't flag the account.
  It uses the broker's own count (Alpaca, IBKR) when it can. Safety exits (stops, expiry, kill switch, your own sells)
  still go through.
- **Real fees**: practice, backtests and every farm now charge your broker's per-contract fee each way (Alpaca about
  $0.04 of regulatory fees; IBKR about $0.65 + $0.04), on top of the spread. Override it in Settings > Basics.
- **Liquidity filter** (LIVE): skips contracts with a wide bid/ask gap (default over 15% of the price) or few open
  contracts (default under 50), where real fills go badly.

## 1.5.0
**Buy-only safety lock, contract price range, and nothing running behind your back**

- **Safety lock**: OBF only ever buys a call or put to open, and sells to close contracts it holds. Every sell is
  checked against the broker's own count first (Alpaca positions, or IBKR positions); an order that would sell more
  than you hold, which would open a short (naked/uncovered) position, is refused before it's sent. So no trade can lose
  more than what was paid for it. The kill switch and hand trades go through the same lock.
- **Options level check**: going LIVE with Alpaca checks your approved options level. Buying calls/puts is Alpaca's
  Level 2 (still defined risk); you get a clear message if the account isn't approved for it yet.
- **Contract price range** (Settings > Basics): the cheapest and most expensive contract the bots may buy, per share
  (e.g. $0.50 to $3.00 = $50 to $300 a contract). Bots move their strike to land inside the range, or skip the trade.
  Applies to practice, backtests, Training camp, Free roam, the Slow farm and LIVE.
- **No background learning**: Free roam now only studies while its switch is ON (no more idle studies), and switching
  it OFF stops the study in progress at once. The nightly Hall of Fame retest is off too (it can be turned back on in
  Settings > Library & Hall of Fame).
- **Disk use** (Tools): what OBF stores and how much it has written since it started, with buttons to delete the
  downloaded history or price cache. Routine saves are now spaced out (account at most every 30 s, farm at most every
  5 minutes); trades still save immediately.
- Leftover crypto wording ("coin", BTC examples) removed from the Basics settings.

## 1.4.0
**Backtesting back to 2016, and a Free roam you can watch**

- **Any stretch since 2016**: Backtest and Training camp have a new period picker: 1 day up to 5 years (or "Since 2016"),
  1 min to 1 day candles, and either the most recent stretch or one starting on a date you choose (try 2020-02-18 for the
  Covid crash, or 2022-01-03 for the 2022 bear market). History downloads once and is stored by year on your computer.
- **Regular hours only**: pre- and after-market candles (when options don't trade) are left out everywhere.
- **Backtest screen, cleaned up**: result tiles, a one-line verdict, a fixed-size chart with dates, walk-forward parts
  shaded and labelled, big news days marked, and a hover readout drawn inside the chart (nothing around it jumps any
  more). The details (stress tests, parts, per ticker, per mood, every rule) sit in their own scrolling box.
- **Free roam, fixed**: it showed impossible dates (it counted nights and weekends as trading time) and only ever
  studied the last few weeks. It now roams anywhere back to 2016, with real dates.
- **Free roam, visible**: an animated IN SESSION banner (what it's studying, which bot, progress), a LIVE TRADES list
  that fills as the bots trade the past, and problems shown on screen instead of failing silently. The stretch chart
  stays up until the next one is ready.
- **Free roam results, organised**: "Bots it tested: best to worst" (green = beats holding across tests, orange = mixed,
  red = usually loses, and whether each is still in your farm), a filterable study log (good finds, bad results...),
  and a "What the results do" tab explaining exactly what each kind of study changes.
- Training camp: a crypto leftover ("Coins", BTC defaults) fixed; up to 12,000 candles per ticker.

## 1.3.0
**Better history and the economic calendar**

- **Full-market history**: backtests, Training camp, Free roam and the farms now learn from candles built from every
  exchange (free on Alpaca for anything older than 15 minutes), instead of the IEX-only slice. The newest 15 minutes
  still come from the free real-time feed, and its volume is scaled up to match so volume rules stay consistent.
- **Download pacer**: long history downloads now slow themselves to Alpaca's free-plan limit (200 calls a minute) instead
  of failing halfway.
- **Economic calendar** (Tools, or the new "Upcoming news" card): CPI, jobs reports, Fed decisions, GDP, PCE and retail
  sales, past and scheduled, from FRED (the St. Louis Fed's free data service; one free key). It refreshes itself weekly.
- **News-day never-rules**: bots can now grow "quiet before big news", "quiet before the Fed" and "let the news settle".
  Like the other never-rules, every trade they skip is graded afterwards, everywhere the farm learns, back to 2016. The
  calendar window shows which rules are spreading and what they saved or cost. (They only appear once the calendar is
  downloaded.)
- Never-rules now also guard opening a put, not only buying calls. Leftover crypto wording in two rules fixed.

## 1.2.0
**Interactive Brokers**

- **Account > Connect Interactive Brokers**: LIVE mode can now place its option orders through your IBKR account, via
  IB Gateway or Trader Workstation running on your computer. The window walks through the one-time setup (enable the
  API, pick the port), installs the small IBKR add-on with one click, and connects. Paper (DU...) accounts get a simple
  yes/no before trading; a real-money account still needs you to type LIVE.
- **Prices**: the farm keeps learning from Alpaca's free history and option chains. Order prices, and the value of
  contracts you hold or watch, come from IBKR when you have real-time US options data there (OPRA); with delayed IBKR
  data, Alpaca's quotes are used for valuations instead. The status bar shows which you have.
- IBKR funds are shown in the status bar, refresh while trading, and set how much the bots can use.
- Optional: connect automatically when OBF starts. Account > Disconnect switches LIVE back to Alpaca.
- **Kill switch** now cancels waiting orders at Alpaca and IBKR (it used an old call that did nothing).

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
