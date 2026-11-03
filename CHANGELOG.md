# Changelog

## 1.19.1
- **Reset account**: a new button on the left that simply puts the account back to its starting money, with no
  positions and no trades. Your farms, bots and everything they've learned are kept. The old Reset is now
  **More reset options** for resetting the farm too.
- **Smoother resizing**: resizing the window no longer sends every widget's resize through the app, so dragging the
  window edge is lighter.
- **Real option prices while the market is open**: Free roam now alternates between watching today live and replaying a
  past day on real option prices, so real-price replays keep happening during trading hours. The Overview no longer says
  "log in to Alpaca" when you are logged in; it says what it's waiting for instead. A day whose option prices failed to
  download is tried again later instead of being remembered as empty.
- **Overview cards stay one size**: the status text on every card has a fixed three lines of room and wraps to the
  card's width, so the cards no longer jump as the news changes.

## 1.19.0
- **Day replays trade real contracts at their real prices**: when Free roam replays a past trading day (scalp roams,
  now called day replays), it loads that day's real option history from Alpaca: the contracts that were actually
  listed, and what each one traded at minute by minute. Bots buy and sell those contracts at those prices, instead of a
  calculated estimate. Any day from February 2024 on works, nothing has to be recorded first, and each day is kept on
  disk after the first time. A contract with no real price falls back to the estimate; the study log says what share of
  fills were real. Needs the Alpaca login.
- **Kamikazes train in Free roam too**: your best kamikazes join every day replay, and every self-test includes your
  best kamikaze and (on short candles) your best scalper. Day replays now run when your farm has scalpers or kamikazes.
- **Overview** (the first tab, was Features): every farm at a glance (Bot Farm, Slow farm, Scalp lab: dragons, winning,
  generation, best right now, breeds, what it has learned and what it's doing), plus totals for everything being
  learned: Free roam studies, days replayed, share of real option prices, what would have worked, rules tested by
  kamikazes, graduates adopted, Library and Hall of Fame, and things learned. The feature cards are below it.

## 1.18.1
- **Features tab** (first tab): every learning feature on one page: Free roam, Hindsight, Scalp lab, Scalp scan, the
  Scalper and Kamikaze breeds, the Slow farm, Shadow Live, Farm knowledge, Training camp, practising on Alpaca paper too,
  and the learning switches. Each card says what the feature is, what it's learning right now (updated every few
  seconds), has an ON / OFF switch, and an Open button that jumps straight to it.

## 1.18.0
- **Hindsight: bots learn what WOULD have worked**: a new Free roam study (every fifth). Looking back at a stretch of the
  past, about 50 instincts and settings are tried on its first 70%, and the most promising are checked on the last 30%
  they never saw. Whatever made money on both goes into the farm's **hindsight book**; the best one hatches on your farm
  as a "Hindsight egg", and from then on most new eggs start from the book instead of being random. Good finds are tried
  again, tweaked, so they get refined. The book is kept with the farm and shows in Farm knowledge as "What would have
  worked". Settings > Learning > Hindsight.
- **Kamikaze dragons** (charcoal, with a burning tail): a new breed (10% of the farm by default) that makes
  all-or-nothing bets on cheap, far-out contracts with little time left, a huge target and almost no stop. They get only
  a small say in your account. Each one also tests one or two rules the farm knows least about, so your good bots don't
  pay for finding out what fails: when a kamikaze leaves, what its rules did goes into the farm's trial book (in Farm
  knowledge), and never-rules that kept saving money become more likely in ordinary eggs.
  Settings > Learning > Kamikaze breed.

## 1.17.3
- **Training shows each bot's own results**: Free roam and the Training camp no longer compare bots with simply holding.
  - Free roam's "best to worst" list: tests, how many made money, average return, total trades, win rate, and each
    bot's single best and worst trade (% of what it paid). The study log shows each bot's own return.
  - Training camp: training return, exam return, trades, win rate, best trade and worst trade for every bot.
  - Older Free roam results are shown as each bot's own return too (best / worst trade and win rate start with new
    studies).

## 1.17.2
- **Free roam no longer gets stuck on a ticker with a short or patchy history** (a new listing, or one with days
  without a single trade): it fits each journey to the history your tickers actually share and tries more starting
  points. If one ticker still leaves no clean stretch, Free roam studies the others without it for now and says so once
  (the farm still trades it as usual). Before, it could fail with "no stretch that long where every ticker was trading"
  every few minutes.
- **No more error reports when OBF closes or restarts**: messages that arrive after the window is gone are skipped
  instead of trying to update screens that no longer exist ("invalid command name ..." in the crash log). Nothing was
  ever lost; it only cluttered the log.
- The last few "vs hold" labels (on dragon cards, in Training camp and in a bot's saved tests) now say "vs market" too.

## 1.17.1
- **Practice in both places at once**: under Account > "Practice trades go to", choose **Both: OBF and my Alpaca paper
  account**. The PRACTICE session runs inside OBF as usual, and every practice trade is also copied to your Alpaca paper
  account: the listed contract closest to the practice one (same type, nearest expiry and strike), same number of
  contracts, sold when the practice trade is sold. The copies show as ALPACA PAPER in the Trades list and the log, and
  never change the PRACTICE numbers. The switch reads PRACTICE + ALPACA PAPER. Copies are only ever placed with a paper
  key; with a real-money key nothing is copied.
- ALPACA PAPER trades now keep their label in the trades file too (they could show as LIVE after a restart), and they
  count toward the day-trade guard and the weekly report under their own name.

## 1.17.0
- **Two modes, clearly named**:
  - **PRACTICE** is everything with pretend money. Under Account, choose where practice trades go: **Stay in OBF**
    (labelled PRACTICE: simulated inside OBF) or **My Alpaca paper account** (labelled ALPACA PAPER: the orders really
    go to your Alpaca paper account; needs your paper key). The switch at the top then reads PRACTICE or
    PRACTICE • ALPACA PAPER, in green.
  - **LIVE** is real money only: blue, "LIVE • REAL MONEY". With a paper key, clicking LIVE explains how to get to
    Alpaca paper instead (it used to open your paper account as "LIVE").
- **Each keeps its own saved session**: PRACTICE, ALPACA PAPER and LIVE never share one. If your saved key is a paper
  key, the session you had behind LIVE (which was your Alpaca paper account) moves to ALPACA PAPER the first time
  this version starts.
- The headline, the account card and the line under the tiles all name the account you're in, and the expiry warning
  covers every saved session at your broker.

## 1.16.4
- **Your Alpaca account's own value**: while you're logged in, a new tile at the top shows the Alpaca account itself
  (ALPACA PAPER ACCOUNT, or ALPACA ACCOUNT (LIVE)) straight from Alpaca, with its change since yesterday's close. It sits
  next to the PRACTICE numbers, which run on OBF's own pretend money, so it's clear which is which. Updated every minute,
  in Practice too. Settings > Basics to turn it off.
- **Filter the Trades list by account**: "Show" All accounts, PRACTICE, ALPACA PAPER, IBKR PAPER, LIVE or FARM TEST.

## 1.16.3
- **The account is named for what it really is**: PRACTICE when trades are simulated inside OBF, ALPACA PAPER when
  orders go to your Alpaca paper account (a paper key), IBKR PAPER for Interactive Brokers' paper port, and LIVE only
  for real money. This shows on the mode switch at the top (it used to say "LIVE - REAL MONEY" even with a paper
  key), the window title, the PROFIT / LOSS tile, the trade log, notifications and the Trades list.
- Trades made before this update through an Alpaca paper key still show as LIVE in the Trades list (they weren't
  marked at the time); new ones show ALPACA PAPER.

## 1.16.2
- **The numbers at the top are easier to read**: PROFIT / LOSS now says whose money it counts ("your practice account"
  or "your LIVE account"), and VS THE MARKET shows its working underneath ("you -52.00 | market -752.00"), so a loss on
  your account next to "+700 vs the market" makes sense: the account lost much less than your tickers did.
- **The market figure can't be thrown off by a missing price**: if a ticker had no price for a moment, the market used
  to count that ticker as worth $0, which made the account look far ahead. It now uses the last known price.
- **Your account and the farm's tests are kept apart**: the Trades list says PRACTICE ACCOUNT, LIVE ACCOUNT or FARM TEST
  (instead of PAPER / LIVE / BOT), and the farm's pretend test trades are hidden unless you tick "Also show the farm's
  test trades". The line under the tiles says which trades the tiles count.

## 1.16.1
- **"Holding" is now "the market"**: everywhere the bots are compared with simply keeping your tickers, the app now says
  "the market": "beat the market", "+12% vs the market", the VS THE MARKET tile, the grey "market" line on the charts,
  Free roam's "Beat the market" and "Avg vs the market". It still means the same thing: your tickers bought at the
  start and left alone (the tooltips and the guide say so). "Holding" a contract keeps its usual meaning.

## 1.16.0
- **Farm knowledge** (Learning > Farm knowledge, or the \U0001f4d6 Knowledge button on the farm): everything a farm has
  learned in one place. Ability meters show how much of each kind it has mastered (never-rules, studies, instincts,
  volatility gates, seasons, elders, breeding lessons, proven dragons), and a grid lists every lesson with the evidence
  behind it. Save it as a named **book**, keep as many books as you like, and pick any lessons to add to the Bot Farm,
  the Slow farm or the Scalp lab: proven rules make new eggs favour them, proven dragons hatch there, elders and
  season champions move across, and mutation memory merges.
- **Free roam's numbers are fair now**: "Avg / Best / Worst vs holding" compare the money a bot ended with to what just
  holding would have ended with, so they can never read below -100%. Before, the two returns were subtracted, so a bot
  that made +20% while holding rallied +400% over a long stretch showed -380%, which looked like an impossible loss.
  Older study results are converted the same way.
- New look for the GitHub page.

## 1.15.0
- **Scalp lab** (new, under the "\u26a1 Scalpers" tab): a farm of scalpers only that learns on its own from LIVE prices
  while the market is open, like Free roam but in real time. Switch it on and it:
  - each morning picks up to 8 tickers (yours, the ones the Scalp scan found paying, then the busiest), starts from
    yesterday's best scalpers plus new ones, and warms up on the day so far;
  - every minute, as each 1-minute bar finishes, lets 24 scalpers decide with real bid/ask costs, their own stops,
    targets and time limits, and their volatility gates (VIXY, SPY and the live VIX-like reading);
  - every 15 minutes evolves: losers retire, winners lay eggs and crossbreed, new scalpers are tried, all judged on
    their last 30 scalps;
  - every 30 minutes sends its best proven scalper (15+ scalps, in profit, winning) to your farm as a "Scalp lab
    graduate" (or pick one yourself: "Send selected to my farm");
  - at the close keeps its 12 best scalpers for tomorrow.
  Its screen shows the scalpers best to worst, their live trades (CALL / PUT), the tickers it's on with their
  volatility, and a lab log. It never trades your account. Needs the Alpaca login.
- The Scalp scan moved under the same "\u26a1 Scalpers" tab.

## 1.14.0
- **Scalp roams in Free roam**: Free roam now has a third kind of study next to Self-tests and Practice farms. Every
  fourth study, your best scalpers plus four new ones (two tweaked from your best, two brand new) trade a whole day on
  1-minute prices across about 16 tickers, with VIXY and SPY for their volatility gates and real bid/ask costs. While
  the market is open the day is today, live; otherwise it's a random past day back to 2016 they haven't studied yet.
  Their trades scroll by in Free roam's live list, and each day goes into the study log (filter: "Scalp roams").
- **What scalp roams teach your farm**: each scalper's results across past days build up (older days count a little
  less), so scalpers that keep paying on tickers and days they never saw get a bigger say, and ones that don't get less.
  A scalper with 8+ winning scalps on a day becomes an elder for future scalp eggs, and a new scalper that beats all of
  yours there (10+ scalps, in profit) joins your farm as a "Free roam scalp graduate". These records survive restarts.
- Switch them on or off with "\u26a1 Scalp roams" at the top of the Free roam screen (on by default when your farm has
  scalpers).

## 1.13.0
- **Scalpers read volatility (VIX)**: every scalper now carries a volatility gate, chosen and evolved by the farm:
  only calm markets, only when volatility is rising, only spikes, never a spike, or ignore it. Some also widen their
  stop and target when volatility jumps. Every trade a gate blocks is graded in hindsight, so the farm keeps the gates
  that pay.
- **Intraday VIX, minute by minute**: while the market is open, OBF reads SPY's ~30-day at-the-money implied volatility
  from its live option quotes about once a minute. That's what the VIX itself measures, so the gates see it move within
  the minute: up 2% in 15 minutes (say 16.0 to 16.3) counts as rising, up 5% as a spike. VIXY (the VIX fund) and how
  fast SPY is swinging vs its last two hours count too. With scalpers on, VIXY and SPY are always watched, and the Scalp
  scan tab shows what the gates are reading right now. The day's readings are kept, so a restart doesn't lose them.
- **The Scalp scan sees the market too**: today's live implied-volatility readings, VIXY and SPY are lined up with every ticker it tries, so volatility gates and
  market studies work there as they do on your farm. A new Volatility column shows each ticker's state (calm, normal,
  rising, spiking).
- **Practice prices follow the market during the day**: while the market is open, OBF reads each traded ticker's live
  option quotes every 15 minutes. Their implied volatility (which climbs with the VIX) now prices Practice contracts
  for every bot, instead of a reading from once a day at most.
- **Scan alerts**: a notification when a setup fires on a ticker where the scalpers are already up today (Scalp scan
  tab > "Alert me").

## 1.12.1
- **Updates are more reliable**: "Check for updates" no longer says you have the latest version for a few minutes after a
  new one comes out (GitHub's file cache was answering with the old number).
- **Restarting after an update works when a folder name has a space in it** (like C:\Users\John Smith\...). Before,
  OBF could close and silently fail to reopen; the update was installed, but it looked like nothing happened.

## 1.12.0
- **Scalps and long-term trades no longer trip over each other**: your account now keeps two books on every ticker, one
  for scalps and one for long-term trades. Each follows only its own bots' votes, so a scalper's "sell" can never close a
  long-term contract, and a scalp can open on SPY while a long-term SPY contract is held. The per-ticker limit counts
  both, and LIVE never buys the same contract in both books. Scalps show as "(scalp)" everywhere.
- **Scalp scan** (new tab): every 5 minutes while the market is open, your farm's best scalpers are tried on today's
  1-minute prices of up to 30 tickers (yours, your watchlist and the most-traded ones), with pretend money and real
  bid/ask costs. See where scalps are paying today, which setups are firing right now, and add a hot ticker to your list
  in one click. Scalpers that also win out there get a bigger say on your farm; ones that only win on your own tickers
  get less. It never trades your account. Needs the Alpaca login.
- **Bot positions** (new tab): every bot's open pretend contracts on both farms, with what it paid, what it's worth now,
  P/L in $ and %, how long it's held and its exit plan. Filter by farm or by scalpers / long-term.
- **Calls and puts are labelled**: chart arrows say CALL or PUT, the farm's pop-ups say "BUY CALL!" / "SELL PUT!", and
  trade notifications name the contract instead of just the ticker.
- Fixed: your account's own trades now show on a ticker's chart (they were missing, because the trade said "SPY 680C"
  instead of "SPY"), placed at the stock price.

## 1.11.0
- **Scalpers: a new breed (wind dragons)**: fast in-and-out bots for the quick moves the long-term bots let pass.
  Five scalp instincts of their own: Micro pullback, Volume burst, VWAP reclaim, Range scalp and Quick flip.
  Every scalper always carries a tight stop AND target on the premium, a time limit, near-the-money contracts, and is
  flat before the close (never overnight). Breeding and mutation can't push one outside that.
- **Their own den on the farm**: a share of the fast farm (25% by default) is kept for scalpers. They breed from the best
  scalpers and can win up to twice their share (never over 60%), so the long-term bots are never crowded out. Off on the
  Slow farm and whenever the decision speed is slower than 5 minutes.
- **The account trades scalps like scalps**: when scalpers carry a vote, that contract uses the scalpers' own stop,
  target and time limit, opens only during the trading day, and is sold before the bell. Long-term trades keep the
  stops they had (scalpers' tight stops no longer count toward "Let the winning bots set stops").
- **Small nips to big runs**: a scalper's target can be anything from 6% to 300% (stops 5% to 60%), and it can pick
  cheaper strikes up to 4% out of the money, so the farm can learn which kind of scalp actually pays.
- **Scalpers pay the real bid/ask gap**: OBF reads each ticker's live option quotes once a day and learns its typical
  gap; scalpers in Practice pay exactly that instead of a flat guess, and skip contracts with a gap wider than 8%
  (adjustable). LIVE scalps use the same limit when picking a contract.
- **Judged by their trades, not the clock**: a scalper is rated on its last 30 finished trades, so one that waits
  patiently for its setup isn't culled as "idle" between them.
- Settings > Learning > "Scalp breed", "...% of the farm kept for scalpers" and the scalpers' bid/ask limit.
- If you saw "The syntax of the command is incorrect." in a command window after updating to 1.10.1: that was the old
  launcher being replaced while it was still open. It's harmless and won't happen again with the new launcher.

## 1.10.1
- **No more black command window**: Run OBF.bat now starts OBF with Python's windowless version and closes right away.
  There's also a new OBF.pyw in the folder: double-click it to start with no window flashing at all (you can pin a
  shortcut to it). If Python can't start OBF, a message box explains why instead of the command window.

## 1.10.0
- **Tickers that move together**: the account never puts more than 50% of your money (adjustable) into calls, or into
  puts, on tickers whose prices have been moving in step (SPY and QQQ often move as one).
  Settings > Basics > "Tickers that move together".

## 1.9.1
- **Start with Windows** is now also in the File menu (it was only on the icon). It runs OBF as the icon by the clock,
  training on practice prices only. It sets up the icon add-on first if needed.
- **Even lighter in the background**: after Windows starts, OBF waits 2 minutes before training so it never slows your
  start-up, and the start-up warm-up uses one processor core instead of several while running as the icon.

## 1.9.0
- **Update alerts on the icon**: while OBF runs in the background it still checks for updates and shows a small note
  when one is out. Nothing installs until you open OBF and say yes.
- **Daily recap**: once a day, a short note on how the bots did vs just holding, plus new BEASTS (on the icon and in
  the log). Settings > "Daily recap".
- **Learning from its own losses**: when one never-rule would have stopped at least 3 of a bot's losing buys and
  clearly fewer of its winners, the bot takes that rule on itself during its lifetime. It's graded afterwards like
  every other rule. Settings > Learning > "Learn from its own losses".
- **Ready for LIVE? checklist** (Account menu): plain evidence that the practice farm is ready: time spent learning,
  Winning bots, beating holding, enough trades, twin test passed, no deep slump, and the account itself ahead.
- **Weekly backup**: once a week a copy of your bots, farms, sessions and settings goes into your data folder under
  auto-backups (the last 4 are kept, no keys, price history left out to keep them small). Settings > "Weekly backup".
- **New from CBBF**: bots can learn to skip the opening or closing rush (never opens a contract in the first or last
  minutes of the trading day, graded in hindsight), and the account trades bigger when several different strategies
  agree, smaller when the farm is split. "Sell in parts" was left out: a contract can't be split in half.

## 1.8.1
- When Windows signs out or shuts down, OBF now saves the whole farm and session first, so the bots pick up
  from that exact point next time (before, up to 5 minutes of learning could be lost).

## 1.8.0
- **Background mode (icon by the clock)**: File > "Run in the background" hides OBF to a small icon next to the
  clock. It keeps training the bots on practice prices at a lower priority (anything you're doing comes first), skips
  all drawing, and never keeps the computer awake. Click the icon to open the window; right-click for Pause/Resume,
  Go LIVE, "Start when Windows starts" and Quit. The first time, OBF installs two small add-ons for the icon.
- **Start with Windows**: tick it on the icon's menu and OBF starts as the icon whenever you log in, training on
  practice prices. LIVE never starts by itself: choose Go LIVE on the icon and type LIVE, once after each restart.
- While OBF is in the background, the window's X hides it back to the icon; Quit is in the File menu and on the icon.
- Opening OBF a second time brings up the copy that's already running instead of starting another one.

## 1.7.6
- **Luck check**: a bot's score now counts for less while it rests on only a few trades (3 trades counts about a
  third, 40 trades almost fully). This applies to which bots steer your account and which ones breed, so a few lucky
  trades can't fill the farm with copies. Settings > Learning > "Luck check".

## 1.7.5
- **Snappier window**: background work (Free roam, warm-up, history loading) no longer makes the window stutter.
  The longest freezes while Free roam runs dropped from about 1.5 seconds to under 0.2.
- **Reset can keep bots**: choose to reset the account, the farm, or both, and keep the BEASTS, Rising, Eggs or
  Hall of Fame bots - they rejoin the next farm when you press Start.
- **Saved farms**: Reset saves a copy of the whole farm first (on by default), and "Bring back a saved farm..."
  restores one later.
- Fixed: starting the farm a second time could get stuck while warming up islands on several processor cores.

## 1.7.4
- Fixed: Free roam could stop with an error when one study's results were saved just as the next study began.

## 1.7.3
- **Free roam only studies history that exists**: it checks each ticker's daily history first, so newly listed tickers
  don't send it looking at years they didn't trade.
- **Backtest and Training camp say what's there** ("XYZ: Mar 2024 to now"), and trim a stretch with a long hole in it.
- **Test on any ticker**: Backtest and Training camp have a tickers box, up to 8, separate from what the farm trades.
- **Smoother**: the chart redraws at most about once a second while prices tick, and bots share prepared candle
  summaries (about 2x less work per price update with ~50 bots).

## 1.7.2
- Diagnostics (Tools > System) no longer copies itself to your clipboard when you open it; press Copy all.
- A hint that still pointed to the old Backtest menu now points to Tools > Learning.

## 1.7.1
- Free roam always starts OFF when OBF opens, even if it was on when you closed it. It only studies after you switch
  it on.

## 1.7.0
**Streamlined: fewer windows, tabs, menus and settings**

- **One Learning window** (Tools, or Ctrl+L): Backtest a bot, Hall of Fame test, Training camp and Free roam are tabs
  of one window. Bot Lab is gone (Training camp's final exam does the same job), and so is the old strategy backtest.
- **Merged windows**: Insights (market context, economic calendar, weekly report, farm replay), System (security
  check, disk use, diagnostics), Family (family tree and drawn bloodlines) and Help (how it works, words, shortcuts,
  plus the tour and welcome screen) are each one window with tabs.
- **One Reset window**: tick the account, the farm, or both.
- **Six main tabs instead of nine**: Markets holds the watchlist and live prices; Trades holds trades, what the bot
  did and the strategy scoreboard.
- **Menus**: 35 entries instead of 52 (the Help menu is one item). Sell everything and the KILL SWITCH are in the Account menu.
- **Settings open on "Everyday"**: the 15 settings most people change. Tick "Show advanced settings" for the rest.
  Long switch descriptions wrap instead of stretching the window.
- **Crypto leftovers removed**: the cash-currency box, staking info, the add-on-buys and market/limit order settings,
  BTC/ETH defaults (the watchlist and tickers now start with SPY and QQQ), "coin" wording, and the welcome and help text
  (rewritten for options). The "follow the leader" study now follows SPY instead of Bitcoin.

## 1.6.1
**Security review**

- **Fixed: hand buys went to the wrong broker.** With LIVE set to Interactive Brokers, a buy from the Options tab was
  still sent to Alpaca, and OBF then tried to sell it through IBKR (where the safety lock refused, so the expiry guard
  couldn't sell it either). Hand buys now go to the broker LIVE trades through, every contract remembers where it was
  bought, and it's always sold there.
- **Hand buys follow the guards**: no contracts inside the expiry guard's window, none while the day-trade guard is
  blocking, and a warning for contracts outside your price range or with a wide bid/ask gap.
- **LIVE contracts are watched from Practice too**: if your saved LIVE session holds a contract close to expiry while
  OBF is in Practice, you get a warning to switch to LIVE so the guard can sell it.
- **Backups never contain keys**, even on computers without a system keychain.
- **Restoring a backup only restores OBF's own data files** (never programs, never anything outside the data folder).
- Ticker names are checked before they're used in file names.
- Security check (Tools) lists the expiry and day-trade guards.

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
