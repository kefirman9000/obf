# Changelog











## 1.43.0
The bots learn to fix their own habits. In the 11/12 report, trailing-stop sales won 9% of the time (104 trades),
and trades held only 1-2 decisions won 12% while ones held 30+ won 44%: each quick round trip pays the bid/ask gap.
- **Bots tune their own exits.** A bot whose trailing stop keeps selling it at a loss while its other sales do
  better (6+ of each, 5+ points apart) widens the trail by half, and drops it past 30%. A bot whose quick trades
  (held under 15 candles) lose while its longer ones do better starts holding at least that long before its signals
  may sell. Each change shows in the farm's news, and the bot then judges the new setting on fresh trades.
  Scalpers and kamikazes keep their breed's rules. Settings > Learning: "Tune its own exits" (on).
- **Two new trade lessons for new eggs**, like the overnight and days-to-expiry lessons:
  - *trailing stops*: when bots with trails under 8% do clearly worse, about half the new eggs carrying a tight
    trail get a wider one (12-30%) or none,
  - *pace*: when bots deciding every 1-2 candles do clearly worse, about half the new (non-scalper) bots that fast
    slow down to every 3-15 candles.
- **Trailing stops can now evolve up to 40%** (was 12%). An option contract often moves 12% in minutes, so the old
  ceiling only allowed trails that noise would trip.
- Free roam's feature tests measure what self-tuning is worth, like every other learning switch.

## 1.42.0
From the 11/12 report:
- **Practice prices follow the volatility smile.** Every strike was priced at the ticker's near-the-money volatility,
  but the market charges much more for strikes well below the stock. A 10%-out NVDA put came out at $66 when the
  market would have asked about $200, so when NVDA opened 14% lower the bots booked +1,342% where a real trade would
  have shown about +400%. Contracts are now priced on a smile measured from each ticker's live option chain (a
  typical stock's until it's read). Far-out contracts look dearer, and their wins smaller and more honest.
- **One huge trade can't carry a bot's score.** Whatever a single trade made beyond +200% of what it paid no longer
  counts toward the bot's ranking (it keeps the money). Electric Marten was the farm's only "active" bot on that one
  NVDA put alone. Farms saved before this cap their bots' best trade the same way.
- **No profit-taking on the opening prints.** In the first 5 minutes after the 9:30 open, bots' profit targets and
  trailing stops wait (stops still work), and estimated option fills pay twice the usual bid/ask gap (1.5x until
  9:45). NVDA's first print on 11/12 was $149.71 and it was back over $160 ten minutes later.
- **Practice no longer sells after the close.** Contracts near expiry were sold at 4:41 pm and 6:16 pm, at prices no
  one could trade at. The expiry guard now sells during market hours (an expired contract still settles).
- **No more ping-pong.** Bots that disagree passed one NVDA put back and forth three times in 13 minutes, paying the
  gap each time. A contract opened on a signal now isn't closed by another signal for 5 minutes, and after a signal
  closes one, nothing new opens on that ticker by signal for 10 minutes. Stops, targets and expiry never wait.
- **Scalp roams on estimated option prices count a quarter.** They showed +100% to +215% on premium where days with
  real prices showed about even. Only real-price days can graduate a scalper or make it an elder.
- **Fix: ticker rotation crashed on an empty download** (11/11 and 11/12). A candidate needs its own prices before
  it can be swapped in.
- **Feature tests skip switches that hardly ever change a result** (the twin test matched itself in 19 of 22 tests).
  They still get an occasional turn.

## 1.41.1
- **Practice no longer books gains a real sale wouldn't get.** Logged in to Alpaca, practice buys real contracts at
  their real ask, but it valued and sold them at the quote's midpoint, or, with no quote from the last 3 minutes,
  at a model price from the ticker's average volatility. On 11/11 it bought 2 RIVN 14 calls at $0.48 and "locked in
  +$29.58" two seconds later at a model $0.63; the Alpaca paper copy sold at the real $0.47 (-$6). Now:
  - practice sells a real contract at its real **bid** (it asks Alpaca for a quote first if the last one is old),
  - profit targets and trailing stops only fire on a fresh real bid (stops still work as before),
  - with no fresh quote, a contract's value is the model's, scaled to that contract's real price when it was bought,
  - the quote checked at purchase counts as fresh.
  Practice results will look a little lower from here, and closer to what your Alpaca paper account shows.

## 1.41.0
From the 11/11 report (1,344 finished bot trades), the farm now learns three more things by itself:
- **Holding overnight.** Trades held overnight did far better (median +6.5%, 59% won, 272 trades) than ones sold the
  same day (-5.8%, 28% won, 1,072 trades). A new habit bots can carry and evolve: **holds overnight** (its signals don't
  sell it in the last 30 minutes of the day; its stops and targets still do) or **flat before the close** (sells in
  the last 15 minutes and opens nothing new in the last 20). The trade lessons compare overnight with same-day
  trades, and about half the new eggs take the habit that's doing better.
- **Days to expiry.** Contracts bought 3 days or less from expiry did worse (-9.4% vs -4.7%). When the farm's own
  trades say so, about half the new eggs buy at least a week out.
- **The hour it buys.** Trades opened after 2 pm did worst (16-24% won). When the lessons agree, about half the new
  eggs carry the 'skip the closing rush' rule.
- **Instincts that trade well hatch more often.** Random new eggs used to pick every instinct equally. Now, once
  an instinct has 40+ finished trades on the farm, how they went sets its share: up to 2.5x for the best (VWAP
  snap-back +10.9% median), down to a third for the worst (Speed shift -19.6%). Every instinct keeps a chance.
- All of it shows under Learning > Trade lessons and in Farm knowledge, and travels with knowledge and camps.

## 1.40.2
- **Fix: a ticker swap that stopped halfway froze the bots.** On 11/11 the rotation swapped AMZN for SOXL, then
  crashed on the next swap (a download whose price lists weren't all the same length). The session switched to
  SOXL, but the farm and the price feed didn't, so no new candle came for every ticker. Now each swap is checked on
  its own (a bad download keeps the old ticker), and every 5 minutes the app makes sure the price feed follows the
  session's tickers.
- **A farm saved during such a swap carries on** with today's tickers on restart, instead of a new farm starting
  (it compares the tickers the bots were really saved on, and keeps every bot and what it learned).
- **Ticker rotation judges a ticker's options by its real swing.** It guessed an unknown ticker's volatility
  (40%), so SOXL looked like a $160 contract when it's about $900. Now a candidate's own prices are measured
  before the swap, and it's skipped if its real contracts don't fit the trade size better.
- (1.40.1) OBF opens in its window: only a start with Windows opens as the icon by the clock.

## 1.40.1
- **OBF opens in its window again.** If Windows started OBF at login (as the icon by the clock), every restart after
  an update came back as the icon too, even when you had the window open. A restart now opens the way the app is at
  that moment: in its window, unless it was hidden by the clock. Starting with Windows still starts as the icon.
- **Opening OBF while it's already running by the clock brings the window to the front**, instead of leaving it
  behind other windows or only flashing on the taskbar.

## 1.40.0
From the 11/10 report (1,331 finished bot trades: 30% won, median -6%):
- **No more far-out contracts by accident.** When a contract cost more than the trade size or your contract price
  range, the bots walked their strike out until it was cheap enough, up to 60 strikes away. That's how a bot that
  wanted 2% out of the money ended up 20-40% out, and those lost most (-7% to -9% a trade, vs +2% to +5% within 15%).
  Now nothing is bought farther out than **15%** (Settings > Farthest out; 0 = no limit): the trade is skipped
  instead. Each bot can also learn its own, tighter limit (a new habit, 'Farthest out it will buy'). Kamikazes are
  exempt (cheap far-out bets are their idea). The account's own contract picks follow the same limit.
- **Trade lessons** (new, on by default; Learning list and Knowledge). The farm learns from its own finished trades:
  calls vs puts, how far out of the money, selling on signals vs letting stops, targets and time limits do it, and
  how long it held. Once there are 40+ trades on each side and one way is clearly better (3+ points a trade), about
  half the new eggs lean that way (calls only, a farthest-out limit, stops-only selling, a minimum hold); the other
  half keep testing the other way, so a lesson can change its mind. One fluke trade counts at most +200%. Lessons
  travel with Knowledge and training camps, and show in the detailed report.
- **A record carried by one trade isn't proof.** If a bot's lifetime gain comes from one trade that doubled its money
  or more, and without it the bot lost money, it can't be proven, stand in, join the Hall of Fame or the Legends,
  and its say counts for less. Same for a bot whose typical (median) trade loses more than 15%. (One +1,784% trade
  in the report was likely a pricing fluke on a far-out contract.)
- **More exams.** Bots can't be proven or become Legends without 3 exams, and 120 of 150 bots had none. The exam
  pass now also runs while Free roam is on (every 20 minutes; every 10 with it off), tests 6 bots a round (Settings),
  starts with the bots closest to a verdict, and always uses a fresh stretch: before, about 2 in 3 rounds landed on
  a stretch Free roam had already studied and quietly did nothing.
- **Fix: the scalp roam got stuck** on 'no trading day with enough 1-minute prices'. It kept retrying the same oldest
  8 days even when too few tickers had 1-minute prices on them. Now a day that comes back short twice is skipped, and
  when no fresh day works it replays a day the scalpers studied before instead of failing.

## 1.39.0
- **The Strategy miner works harder before it gives up.** It used to try one batch of 40 instincts and settings per
  stretch and stop, even when nothing held up. Now it works in rounds: each new round refines the closest tries so far
  (settings nudged, a neighbouring decision speed, another stop/target), fills in instincts it has barely tried, and adds
  fresh ideas. It never tries the same settings twice, and it stops once 3 finds held up, after 240 tries, or after 10
  minutes on one stretch (Settings: miner budget, finds, minutes). A find now also needs at least one finished trade
  on the part it never saw. On test data where the first batch's best worked in 2 of 6 parts, later rounds reached
  5 of 6 and found settings that held up. Its log line says how many rounds it took, and how close it came when
  nothing held up.
- **Legends** (new, on by default; Tools menu, Learning list and Settings). Bots that proved themselves no longer
  vanish when they leave the farm: those that passed their exams and made money, beat just holding over 8+ finished
  trades, or were long-term winners join the Legends with their record, and keep it after they retire. The bots
  learn from them: about 10% of new eggs hatch from a legend (less while their eggs don't hold up), elders' nudges
  include them, and the Strategy miner re-tests the best legends on every new stretch ('Found again'). Each legend
  shows how many of its eggs did well. Legends are saved to `legends.json` in your data folder (up to 200, best
  first), so they carry over to new farms and sessions. In the Legends window you can bring one back to compete
  again from scratch, catch it to your Library, or forget it. The detailed report includes them.

## 1.38.0
- **Strategy miner** (new, on by default; Learning list and Settings). Free roam now also mines long stretches of the
  past (about 1 study in 6): it cuts the first 75% into 6 parts and tries 40 instincts and settings straight through,
  counting the parts each one made money in. The steadiest are checked on the last 25% they never saw. A find counts
  only when it made money in at least 4 of the 6 parts, overall, and on the check. Finds go into the miner's book
  (found again on another stretch = stronger), and up to 15% of new eggs hatch from them; the steadiest find of each
  study hatches on your farm right away. Each mined egg is graded on its exams, and finds whose eggs keep failing
  are dropped from the book. Its studies are in the Free roam log (filter: Strategy miner).
- **Auto training camp teaches your farm before you press Continue.** When the app reopens with your farm loaded
  but not running yet, the auto camp used to skip it ("start your farm"). Now the farm learns from every camp right
  away (and is saved), and the camps' graduates wait and join as soon as it runs.

## 1.37.1
- Fixed an error when pressing Bring / Save in the Training camp with no farm running or no bots passed: it now shows the note instead.

## 1.37.0
- **Chart any ticker.** Each chart now has a small box next to its dropdowns: type a ticker (F, PFE, anything) and
  press Enter or Show to chart it there. Tickers outside your session are downloaded and kept fresh about once a
  minute while shown, and the last 8 you typed stay in the charts' dropdowns.

## 1.36.0
Changes from what Free roam found (your settings move once to the new values; change them back in Settings if you like):
- **Scalpers.** They kept losing about 8% on premium, mostly to the bid/ask gap. Now: 10% of the farm (was 25%),
  they skip contracts whose gap is wider than 3% (was 8%), and a scalper may trade your account (or stand in) only
  after **2 winning exam days at real option prices** (Settings > Scalp breed; 0 = no extra test). They keep
  learning on the farm meanwhile.
- **Adaptive stops off by default.** Its tests leaned against it (-13% with it vs -5% without). Bots carrying it drop
  it. Free roam keeps testing it on vs off, so 'What learning is worth' will show if it earns its place back.
- **Hindsight eggs.** At most 20% of new eggs (was up to 60%), down to 5% while few hold up. Instincts whose eggs did
  well afterwards (Bollinger bands, SMA crossover) now hatch most of them. A hindsight egg that loses its first exam
  is retired instead of sitting in Rising.

## 1.35.0
- **Ticker rotation.** The bots no longer stay on the same tickers forever. Once a day, about 15 minutes after the
  open, the bot looks over about 70 busy tickers, now including cheap ones whose options a small account can really
  buy (F, PFE, T, VZ, BAC, KO, CSCO, GM, SNAP, HOOD and more), and swaps up to 2 of yours whose options don't fit its
  trade size or barely move for ones that clearly fit better (at least 1.5x the score). It never drops a ticker the
  account holds, and keeps one index ETF. The bots carry everything they've learned over; their open pretend
  positions in a dropped ticker are closed, and 'the market' carries on from today's value over the new tickers.
  A **Re-pick now** button next to Bot picks does it on demand. Settings > Ticker rotation (on), at most N a day (2).
- **Bot picks** (choosing tickers for a new session) also looks at the cheaper tickers now.
- **Hindsight eggs**: an instinct whose hindsight eggs never once held up afterwards (12+ tries, like Supertrend's
  0 of 25 on one farm) hatches no more of them.

## 1.34.1
- **Fix: practice could buy a far-out contract at a stale price and lose most of it a minute later.** The contract
  list practice picks from can be up to 30 minutes old; one AMD put was bought at that old $1.15 ask and the real
  price a minute later was $0.33, so the safety stop sold it at -$82. Practice now checks the contract's price right
  before buying when the list is over 90 seconds old, and skips it if the bid/ask gap is too wide.
- **The stand-ins message no longer fills the log.** The stand-ins swap places minute to minute; the line under the
  top still updates live, but the log says it once every 10 minutes.
- **Farm doctor: Essentials only.** While it's on, Free roam and the other trainers are paused, so no bot can pass
  exams and become proven; the doctor now says so, with a button to turn it off.

## 1.34.0
- **Flexible prices for option buys on Alpaca** (the bots' own trades in ALPACA PAPER and LIVE, and the paper copies
  made with 'Both'). Instead of one limit order at the ask that expires if the price moves:
  - a **busy contract** (bid/ask gap within 5% or 5 cents, and at least 500 traded today) on your **paper**
    account is bought with a **market order**, so it fills at once;
  - otherwise the limit **starts at the middle of the bid and ask**, steps up to the ask, then to today's ask plus
    up to 3%, each step taking its share of the limit wait.
  - **Real money never uses a market order**; it gets the stepping limit only.
  Settings > Flexible prices (how far above the ask, 0 = only ever the ask), Market orders on Alpaca paper when a
  contract is busy (on), and how many contracts traded today count as busy (500).

## 1.33.1
- **More practice trades reach your Alpaca paper account.** With 'Both' on, a copy was placed as a limit order at the
  ask OBF had just seen; when the price moved on during the wait, it never filled and the copy was skipped (about a
  third of copies on one farm). A copy that doesn't fill now tries once more at the current ask plus 5%, so it fills
  unless the market really ran away. (Paper sells already fell back to a market order.)
- The report for Claude now says whether 'Both' is on and how many copies were placed and filled.

## 1.33.0
- **Stand-ins while no bot is proven.** Until a proven bot is winning, the account no longer just waits: the 3 best
  winners trade it at half the normal size. Each must be winning right now, have 3+ finished trades, be ahead over
  its whole life and not have failed its exams; kamikazes never stand in. As soon as a proven bot is winning, it
  takes over and the stand-ins step back. The bar under the top line, the farm's status line and Home name the
  stand-ins. Settings (under "Only proven bots trade the account"): how many may stand in (0 = off, the old
  behaviour) and their size (0.5 = half).

## 1.32.0
- **A new layout: Home, plus four sections on a rail at the left.**
  - **Home** answers three questions at a glance: *Is it running?* (with Start / Stop), *Is anyone proven?* (the
    leading bot, and what the closest one still needs) and *What needs you?* (the farm doctor's findings, with their
    fix buttons). Below: your latest trades and what's learning right now.
  - **Trading**: Portfolio, Options, Trades, Alpaca account. **Bots**: Bot Farm, Slow farm, Scalpers, Success, Bot
    positions, and the Library & Hall of Fame. **Learning**: the Overview of every feature, plus Free roam, the
    Training camp and Farm knowledge. **Markets**.
  - Each section shows its screens as buttons along the top. The account panel and the charts stay in Home, Trading
    and Markets; Bots and Learning get the whole window.
  - Nothing was removed: every tab, button and window is where its section says. Links that jump to a tab (like
    'See the bots') move the rail along. Settings > New layout (off) brings the old row of tabs back after a restart.

## 1.31.1
- **Fix: Free roam's self-tests failed** ("backtest_bot() got an unexpected keyword argument 'stop'"). A study that
  stays in the app (because it reports each trade to the Free roam screen) was handed a stop option backtests don't
  take. It now gets only the options it was given.

## 1.31.0
- **Studies on their own processor cores.** Training camps, Auto camp, Free roam's studies, hindsight and backtests now
  run in separate worker processes, so they use other cores instead of sharing one with the window. Stopping them
  and their progress bars work as before, and if a worker can't start, the study simply runs inside OBF as it used
  to. Settings > Studies on their own cores (on). (The farm's own decisions were measured too: about 6 ms per
  decision even with 175 bots, so they stay where they are.)
- **Fix: double-clicking OBF.pyw could open a second copy of the app** in the background whenever a study ran on
  another core (the scalp scan did this already); the launcher now only starts the app itself.
- **One shared farm engine.** 39 farm methods that were identical in CBBF, OBF and SBF (ranking, farm size, families,
  replays, seasons, health...) now live once in farmcore.py, about 360 lines per app, so a fix there reaches all
  three apps.

## 1.30.0
- **Practice learns what real fills cost.** With 'Both' on, every practice trade is also placed on Alpaca paper. OBF now
  compares the two prices and, after 10 priced copies, practice charges the difference on buys and sells, so practice
  results stop being rosier (or harsher) than real ones. The Alpaca account tab shows the comparison, and the farm
  doctor warns when many paper copies don't fill at all. Settings > Learn from paper fills (on).
- **Earnings awareness.** OBF keeps the US earnings calendar for the next six weeks (from Nasdaq, refreshed every 6
  hours; off with Essentials only):
  - **Earnings guard** (Settings, default 1): the account opens nothing in a stock the day before or the day it
    reports.
  - A new never-rule bots can learn, **Stays away from earnings**, graded like the others.
  - The farm doctor warns when you're holding something into an earnings report.
- **Two new option exits bots can learn:** **Decay exit** (sell once time decay eats X% of the contract a day, so a
  contract isn't held while it melts near expiry) and **Volatility-collapse exit** (sell once the contract's
  volatility has fallen X% since it was bought, as after an earnings report or a calm-down).

## 1.29.0
- **Farm doctor** (top bar, next to Essentials only): checks the farm and the app every minute and offers a fix
  where there is one: a farm far past its size (one click trims it), most bots unjudged, no bot proven for hours,
  few exams, prices that stopped coming, Free roam stuck or idle, errors piling up, one strategy taking over, and
  today's loss limit or a losing-streak pause. The button turns amber or red when something needs you, and says
  so once in the log.
- **Safety limits for the account**, enforced whatever the bots decide (Settings, after the daily loss limit):
  **Most open positions** (default 10), and a **Losing-streak pause** (after 5 losing trades in a row, nothing new
  opens for 30 minutes). Sells and safety exits are never blocked. Together with the daily loss limit and the limit
  per ticker you already had.
- **Silent bots get loosened instead of just dropped.** Your reports showed farms where most bots never traded
  (100 of 120 on one): they carried so many conditions before buying (skip quiet markets, only some kinds of market,
  several signals in a row, the bigger trend agreeing...) that the moment never came, so they could never be judged
  or learn. A bot that goes a whole scoring window without a trade now loses its most restrictive condition and gets
  a fresh window, up to 4 times. In a test farm built like yours, bots stuck without trades went from 35 to 0 and
  more bots could be judged (29 instead of 23).
- **Fix: "not logged in" no longer fills the error log.** The price watcher logged an error every few seconds while
  you weren't logged in (26 of the last 27 errors in one report); it now just waits.
- **Fix: an overfull saved farm now really shrinks back to its size when it loads.** Loading stretched the size to
  fit every bot, so the trim did nothing and a 60-bot farm could stay at 125.

## 1.28.1
- Training camp Auto: **Stop now works while it waits** between camps (it cancels the next one), the wait shows a
  countdown, and a **wait** choice sets the pause between camps (0, 5, 10, 30 or 60 seconds; default 10). Unticking
  Auto during the wait stops it too.

## 1.28.0
- **Training camp: Randomize, Auto and Max decisions.**
  - **Max decisions** (default 5,000): the most farm decisions one run may take (candles x passes). Longer periods are
    cut to their latest candles, so a run can't grow huge.
  - **Randomize** picks a period, candle size, passes, farm size and starting bots for you, always under Max decisions,
    and mostly on your farm's own candle size so its graduates fit your farm.
  - **Auto** runs one camp after another with random settings. After each one your farm learns from it and up to 3
    bots that passed the exam join your farm. 30 seconds between runs; it runs while the Training camp window is open,
    stops with Stop (or untick Auto), gives up after 5 runs in a row that can't finish, and Essentials only keeps it off.

## 1.27.1
- Fixed: Auto camp's (or the exam pass's) first stretch after the app started could fail with "no attribute roam_log"
  when Free roam hadn't loaded its study log yet; it then waited 5 minutes before trying again. The log now loads
  whenever any of them needs it.
- Auto camp says when a stretch is a repeat visit. Each stretch is studied 3 times (Settings > Learning > Free roam
  reuse); repeat visits teach your farm, but only a first visit can bring an exam-passing bot over.

## 1.27.0
- **Auto camp** (the farm toolbar, next to Free roam): while your farm runs, it keeps picking stretches of past prices
  by itself and runs a practice farm through each one, at most 1,500 farm decisions per stretch (longer stretches are cut
  to their latest 1,500 candles). After each stretch your farm learns its lessons and the best bot that passed the
  exam joins your farm. It pauses a minute between stretches, starts OFF each time the app opens, waits while Free
  roam is on (Free roam runs its own camps), and Essentials only keeps it off.

## 1.26.1
- **Essentials only button** (top bar, next to Check for updates): one click switches off everything that downloads
  extra history or works the disk in the background: Free roam, the Slow farm, the Scalp lab, background exams, the automatic
  economic calendar refresh and weekly backups. Normal trading and its prices keep running. While it's on, those modes
  can't start by themselves; starting one by hand asks whether to switch Essentials only off. Click again to allow them.

## 1.26.0
- **Minimum days to expiry** (default 7): bots that hold overnight no longer buy contracts a day or two from expiry,
  which can lose most of their value overnight. Several top bots were buying 2-day contracts. Scalpers (flat by the
  close) and kamikazes are exempt. Settings > "Minimum days to expiry".
- **Exams with Free roam off**: most bots were never examined, because exams only happened inside Free roam. Now,
  every 20 minutes while the farm runs, up to 3 bots that still need exams are tested on a stretch of history none of
  them trained on, at their own candle size. It's only an exam: the bots learn nothing from it. Each stretch downloads
  once and is kept; with no connection it waits for the next round. Settings > "Exams with Free roam off".
- **Backup strategies stay alive**: when one strategy fills over half the farm, half the new eggs try other
  strategies, and the last two bots of any strategy are dropped last. If the market stops suiting the favourite, there
  are alternatives ready. Settings > "Keep backup strategies".
- **Thin-market warning**: once a day, a ticker that went without trades in a fifth or more of its recent bars gets a
  warning in the log (and on the icon), with well-traded tickers to consider instead.
- **Shared core**: about 800 lines that were identical in CBBF, OBF and SBF now live in one shared file, farmcore.py,
  so fixes to that code reach all three apps at once. tools/sync_core.py copies it between the apps, and a test fails
  if one app's copy drifts.

## 1.25.2
- **Successful bots stay.** A bot with 8+ finished trades that made money over its whole life and beat just holding
  is now protected from retirement and from being dropped to make room. A bad patch benches it (no say in trades)
  but no longer kills it; it only goes once its lifetime record turns. Weaker bots still die out as before.
  Settings > "Keep proven veterans".
- **No more exact copies.** Copies of the same bot on the same island (from migration, training camps or starter
  sets) wasted farm places and voted twice for the same idea. The best-scoring copy stays, the rest are removed.
- Fixed: a bot that learned a rule from its own losses kept its old identity, so the copy check and the Hall of Fame
  could mix it up with its parent.
- **Daily recap fixed**: it no longer reports gains while prices are stale or across a reset (it once showed
  +83% for a day with no trades). It waits for fresh prices and starts over when the session changes.
- **Background start logs in reliably.** When the computer had just started, the saved Alpaca login could time out
  and was never tried again, so the bots trained all day without prices. It now retries after 30 seconds, then 1, 2,
  4 and 8 minutes, then every 10 minutes, and loads the missed history once it connects.
- The scalp lab no longer fills the error log every minute while logged out; it waits quietly for a login.

## 1.25.1
- **Fix: practice option trades no longer lose (or win) money that was never there.**
  - While you're logged in, practice now buys real listed contracts at their real ask, from the option quotes OBF reads
    every 15 minutes. Before, it bought at a model price and then valued the contract at its real quote, which for
    far-out contracts was a small fraction of the model's: a "loss" of 80-90% within a minute that tripped the safety
    stop. If no listed contract fits (your contract price range, a tight enough bid/ask gap), the trade is skipped and
    the log says why. Not logged in, the model still prices them.
  - The model never walks a strike more than 25% away from the stock to fit your contract price range (a $0.60 limit
    used to reach strikes like AMD 760C).
- **Fix: contracts no longer jump in value after a restart.** Each contract remembers the volatility it was priced
  with and uses it until the market's own (implied) volatility is known again. Before, a few candles of measured
  volatility (226% for INTC once) could hand bots fake gains of hundreds of percent at a restart.

## 1.25.0
- **Proven bots are reachable now.** Almost no bot ever earned a vote, so the account never traded. Two reasons:
  bots were replaced faster than they could finish a record (about half the farm in two hours), and trades from Free
  roam's exams didn't count. Now:
  - Trades a bot makes in its exams (days it never trained on) count toward the finished trades it needs.
  - Bots on course to earn a vote (passed exams, or exams so far positive and not behind holding) aren't retired or
    dropped to make room, up to a third of the farm, so they live long enough to finish their record.
  - The rules themselves are unchanged: exams, lifetime profit and beating just holding are still required.
- **A rejected saved key no longer costs you the session.** When Alpaca rejects the key saved on this computer, OBF
  forgets it and opens the login (tick Remember with your current key). Loading history now waits for a login that's
  still connecting, and logging in after a start without history reloads it for the same farm.

## 1.24.2
- **Donate button**: a pink **Donate** button in the top right (and Tools > Donate) opens OBF's GitHub Sponsors page.
  OBF stays free; donations pay for new breeds, new tricks and more time to build them.
- **Fix: Free roam no longer logs errors when you aren't logged in.** It needs Alpaca's history, so it now waits
  quietly, says once in the log that it's waiting for a login, and starts studying as soon as you log in.
- **Start asks you to log in when you haven't**: Practice uses pretend money but real prices, and those come from
  Alpaca, so without a login the bots just waited. Start now offers to open the login (or start anyway).
- **Fix: "no history" isn't a crash any more.** When Free roam finds nothing to study (a holiday, a gap in the
  data) it notes it and moves on, instead of adding an entry to crash.log and the error counter.
- **New README and screenshots**: the page now explains how the farm trains, breeds and tests its dragons, with
  fresh dark-mode screenshots of the farm, the BEASTS den, Overview, a dragon's card, Free roam, Farm knowledge, the Library,
  Portfolio, Bot positions and Success.

## 1.24.1
- **An alert when no bot may trade.** While the bot runs and no bot is proven yet, an amber bar under the top line
  says so: the account won't trade, how many bots are training, and what the closest ones still need ("4 more
  finished trades", "passed exams (1 of at least 3 taken)"...). Its buttons: How to train them, Turn on Free roam
  (while it's off) and Settings. The first time it happens you also get a notification and the guide opens by itself.
  The bar goes away (with a note in the log) as soon as a bot is proven.
- **How to train your bots**: a short guide to getting bots proven: keep the bot running, turn on Free roam (it gives
  the exams), run the Training camp, give them room to trade (practice money and contract prices), or choose who
  trades yourself, with a button for each.
- **Proven kamikazes may trade the account** if you want: Settings > Wildcard (off by default). They need the same
  trades and lifetime record as other bots; Free roam doesn't examine kamikazes, so their record is their proof.

## 1.24.0
- **Only proven bots trade the account now.** Your practice account, Alpaca paper and LIVE only follow bots with a real
  track record: at least 8 finished trades, at least one full scoring window on the farm, money made over their
  lifetime and more than just holding, and passed exams on days they never trained on. Shaky and new bots no longer
  get any say, and kamikazes never do. Among the proven ones, the best lifetime records get the biggest say (up to 3x).
  Every other bot keeps training on its own pretend money, and a bot whose record slips loses its say again.
  - Settings > Wildcard: "Only proven bots trade the account" (on), the trades it needs (8), and whether passed
    exams are required (on). Bots you pick yourself for My team or Hall of Fame only aren't held back.
  - The log says how many bots are proven and who's leading. Expect the account to trade much less, especially at
    first: it waits until bots have proven themselves.
- **A fresh scoreboard, once.** Farms saved before 1.23 carry track records earned on practice prices that were far
  too generous (single trades of +46,000%), which would have counted as "proven". When such a farm loads, every bot's
  money, results and exams start again. Genes, rule evidence and everything the farm learned are kept.

## 1.23.7
- **OBF can manage Alpaca options no bot traded.** On the Alpaca account tab, pick positions and press "Let OBF
  manage selected": OBF then looks after them with your account's rules from Settings (safety stop, lock-in profit,
  trailing stop, and selling before expiry), checked every minute while the market is open, with the prices Alpaca
  shows. It works for any ticker, not just your session's. "Stop managing" hands them back (they stay open).
  - Settings > "Let OBF manage every untracked Alpaca option": picks up every option position in your Alpaca account
    that nothing in OBF follows, automatically. Off by default; it works with a LIVE key too, so it says so.
  - Positions an OBF session already follows are left to that session, and shares are never touched.
  - Copies kept from before a practice reset now follow the same rules (before, they were only sold before expiry).

## 1.23.6
- **Success tab: act on the bots it lists.** Pick one or more bots (Ctrl+click for several) and use the buttons under
  the chart: Save to Library, Add to Hall of Fame, Add to my Bot Farm (copies Slow farm or Scalp lab bots into your
  Bot Farm as eggs, with their rule evidence; a Slow farm bot's pace is turned into the nearest pace on your farm's
  candles), or Details (also by double-clicking). What you picked stays picked when the tab refreshes.
- **Fix: bots from the Slow farm or the Scalp lab couldn't be added to the Hall of Fame** (or saved to the Library,
  added to your team or exported from their card). Those actions only looked for the bot on the Bot Farm, found
  nothing, and still said it was added. They now work for bots on any farm, and their detail cards show their own
  farm's figures instead of "Removed".

## 1.23.5
- **Fix: restarting OBF made the bots "sell" for big fake profits.** After a restart, the market's own (implied)
  volatility wasn't known again until the next quote (up to 15 minutes), so contracts were priced with measured
  volatility instead. One report showed every INTC and AMZN contract repriced at once, and 34 bots "sold" for
  +122% to +283% in the first minute. Now:
  - the market's implied volatility is kept through a restart (for up to 20 hours), so nothing jumps;
  - measured volatility only counts moves from one candle to the next. A jump over a night, a weekend or an earnings
    gap isn't a one-minute move, and counting it as one read INTC at 226% when the market said 92% (on a test
    week with a 10% earnings gap: 89% before, 50% now, the true figure).
- Measured volatility is worked out every 30 candles (it hardly changes faster), so Free roam and the Training camp
  stay quick.

## 1.23.4
- **Contract price sliders**: "Contract price the bots may buy" on the left, under Practice money: a Min and a Max
  slider in dollars per contract. The bots move their strike nearer to or further from the price until a contract
  fits the range, and skip the trade if none does (practice, the farms and LIVE alike). Far left on Min means no
  minimum, far right on Max means no limit. It takes effect from the next trade, and it's the same setting as
  "Cheapest / Most expensive contract" in Settings, so changing either updates the other.

## 1.23.3
- **Bot picks chooses better tickers**: it used to rank tickers almost only by how much they moved today (up to 20
  times the weight of anything else), so index ETFs like SPY and QQQ hardly ever made it in. Now it weighs: trading
  volume; today's move (counted, but only up to 3x); whether a typical contract fits the bots' trade size (otherwise
  they skip that ticker or only buy the cheapest far-out contracts); and how tight its option prices are. One place
  is always kept for the best index ETF (SPY, QQQ, IWM or DIA) when it picks 3 or more. The log says why it picked
  each ticker.
- Tip: the bots' trade size is your practice money times Trade size %. With $1,000 at 10% they can spend about $100,
  which rules out most SPY, QQQ or AMZN contracts; $10,000 or more lets them trade those.

## 1.23.2
- **Default practice money**: a Default box next to Practice money. Tick it and that amount is filled in whenever OBF
  starts (and on the welcome screen), and used for new sessions and resets. Untick it to go back to $10,000. The box
  shows ticked only while the amount typed is your saved default.

## 1.23.1
- **Detailed reports for Claude**: Tools > Export a detailed report for Claude... (or tick "Detailed reports" in
  Settings to make every report detailed). On top of the usual report it adds:
  - every bot's recent trades with what explains them: the contract, how far out of the money, the stock's price, the
    volatility it was priced with and where that came from (the market's own, real past prices, or measured), how
    long it was held, and the result (detail.json, and bot_trades.csv to open as a table);
  - how the results spread out (by price source and by strategy), what a typical contract costs next to the bots'
    trade size, each farm's instinct records and departures, the feature tests, the full Free roam log, errors.log;
  - checks.txt: plain-English warnings for things that look wrong, such as trades over +1000%, farms where few bots
    can be judged, contracts the bots can't afford, or holes in today's prices.
- **Fix: charts had holes** when prices stopped for a while (the bot stopped or halted, the computer asleep, the
  connection down, or one ticker's price not coming back), and nothing filled them in afterwards. Now, when the feed
  sees the last candle is more than 3 candles old while the market is open, it fetches the missing candles from
  Alpaca's history and adds them, so the charts and the bots' indicators have the real prices. (The bots don't trade
  those minutes after the fact.)

## 1.23.0
- **Fix: practice option prices were wildly optimistic, and the farm learned to chase that.** When the market's own
  (implied) volatility isn't known (Free roam's days in the past, tickers outside your session, the first minutes
  after starting), practice contracts were priced with the volatility of the last 120 candles. On short candles that
  can jump from calm to wild in minutes, so a cheap contract bought as a stock started to move was repriced hundreds
  of times over on a move of a few percent: one report showed single trades of +46,000%, and scalp roams with
  estimated prices showing +6,000% while the days with real option prices came out between -35% and +28%. Breakout
  bots won every time, became BEASTS, and your account followed them into real losses.
  - Contracts are now priced with about a week of candles (a few months on daily ones), so a short burst barely moves
    the price of volatility. Live implied volatility is still used whenever it's known.
  - Contracts under $5 ($0.05 a share) can't be bought any more: real far-out options hardly ever sell that cheap.
  - Expect your bots' scores to drop a lot over the next ~100 decisions as their windows roll past the inflated
    trades. That's the farm seeing them as they really are. BEASTS may fall back to Rising, and that's correct.

## 1.22.4
- **Alpaca account tab**: what's really in your Alpaca account (paper or live, whichever your key belongs to), read
  straight from Alpaca, with a Refresh button (it also refreshes itself every 30 seconds while you look at it). Each
  position says which part of OBF looks after it: a copy of a practice trade, this session, a saved session, a copy kept
  from before a reset, or nothing. Positions nothing in OBF is following can be sold from the tab (at the bid, then at
  market), never more than Alpaca says you hold.
- **Resets no longer forget your Alpaca paper copies**: with "Both" on, resetting the practice account used to drop
  OBF's record of the copies on your Alpaca paper account while they stayed open there, so nothing sold them. Now they
  stay open and OBF keeps looking after them: they show in the Alpaca account tab, and each is sold the day before it
  expires, like every other contract OBF holds. The history of those copies stays in Trades too.

## 1.22.2
- **Resetting the practice account now clears Bot positions too**: the bots' own pretend contracts are closed at what
  they're worth now, from Reset account and from the account box in Reset... (Bot Farm and Slow farm). No trade is
  counted and every bot's money, score and learning stay as they were, so the farm carries on where it was.
- **Fix: after a restart, Bot positions showed every contract as worthless** (a huge pretend loss). A restarted farm
  didn't keep its last prices or the volatility it had measured, so contracts were valued at $0 (or at a rough guess)
  until it ran again. Both are saved with the farm now, and the tab uses today's prices first; a contract with no price
  yet says so instead of counting as a loss.
- The Bot positions total now says plainly that it adds up all the bots' separate pretend money. None of it is yours.

## 1.22.1
- **Instincts keep a lasting record**: Farm knowledge's "Main instincts" meter used to count only instincts with a bot
  winning right now, so it bounced around and never built up, however much the farm learned. Each instinct now keeps a
  record of how its bots do against just holding, review after review (saved with the farm, and passed on by practice
  farms). An instinct counts as proven when it's winning now or its record beats holding over 10+ reviews, and the
  farm keeps what it learned about an instinct (and its best bot) even after that family has died out.
- **Fix: kamikazes were crowding out the farm's eggs**: a kamikaze with a lucky win became a "winner" and laid eggs,
  which were then culled straight away because the farm already had enough kamikazes. In simulations that wasted 50 to
  400+ eggs per run, and each one could push out a normal bot to make room. Once the farm has its kamikazes, they no
  longer lay eggs, and a normal bot never picks up kamikaze genes from its mate. In tests over 21 simulated markets the
  farm then had more bots it could judge (more with a real track record), though their average results didn't change.

## 1.22.0
- **What learning is worth**: Free roam now measures what each learning switch in Settings is worth. About one study
  in seven, the same practice farm lives through the same stretch twice, with one switch on and then off (same bots,
  same luck), and its best bots, picked by how they trained, sit an exam on prices they never saw. Each switch builds
  up a record and gets a verdict once the difference is steady: helps, hurts, leans one way, or no clear effect. The
  bar is high on purpose: with about 30 switches, a few will look good by luck. Switches a practice farm never uses
  are marked as such instead of "no effect". See Free roam > What learning is worth, or Tools > What learning is
  worth. Nothing is changed for you; turn the tests off in Settings > Learning.

## 1.21.1
- **Free roam downloads much less**: each stretch of history it downloads is now studied 3 times before it
  fetches a new one (Settings > Learning, "Free roam studies each stretch..."; 1 = always new). Only the first
  visit is on prices the farm hasn't seen, so only it can promote bots (exams, graduates or hatched eggs); repeat visits still teach
  and show as "(again)" in the study log.
- **Orders are never sent twice**: every order now carries its own ID. If the answer from Alpaca gets lost (a timeout
  or a dropped connection), OBF asks Alpaca whether the order arrived before trying again. Before, a lost answer could
  place the same order a second time.
- **Leftover orders are really cancelled**: when a limit order doesn't fill in time, OBF cancels the rest, checks that
  it's gone, and tries again if not. If it still can't confirm it, it tells you (and the kill switch still cancels it).
  Before, a failed cancel was silent and the order could fill later without OBF knowing.
- **Updates come from finished releases only**, checked against a checksum published with each one, and the download
  must say it's the version you were offered. Before, Update installed whatever was on GitHub at that moment.
- **Updates install the add-ons a new version needs** (anything new in requirements.txt), and say so if one fails.
- **Restoring a backup can't be undone by an autosave anymore**: OBF restarts right after writing the restored files
  instead of saving the old farm and settings over them on the way out.
- Errors OBF recovers from (a failed save, a dropped connection) are now noted in `errors.log` in the data folder.
- Tidy-ups: OBF no longer calls itself CBBF in a few places (web requests, sleep blocking, bot files, sounds).

## 1.21.0
- **Free roam now studies your farm's own candle size.** It often tested 1-minute bots on 5-minute, hourly or daily
  candles. A bot that decides every 15 candles was being tested as if it decided every 15 days, so the lessons
  (self-tests, hindsight eggs, practice-farm graduates) didn't fit. Studies now use the farm's candle size (1-minute
  candles were added). Only tests on the bot's own candles count as exams; older mismatched self-test exams are
  dropped once, so bots that "failed" them get a fair new start.
- **The farm keeps to its size.** Free roam graduates and hindsight eggs could push a farm well past its size (one
  report showed 127 bots on a 60-bot farm). New bots now make room first, never by dropping a bot too young to judge.
  An overfull saved farm is trimmed back when it loads.
- **Think between candles**: a few times a minute, the bots also decide on the candle that's still forming (the live
  price), so they can get in or out without waiting for the minute to end. Their scores still move one candle at a
  time, and a bot that traded a ticker on the current candle leaves it alone until the next one. Half the farm thinks
  each time, so the screen stays smooth. On by default (Settings, and the Overview's feature list).
- **Success tab**: how every bot is doing, in five views: Live (fresh prices), Lifetime, Free roam tests, Exams and Day
  replays, for the Bot Farm, Slow farm or Scalp lab, with a chart of the best and worst.
- **Keep what Free roam learned**: the Free roam screen can now catch its best bots into your Library (the ones you
  pick, or every green one still on your farm), and **Export what Free roam learned...** saves its findings,
  hindsight book, exams, elders and best bots to a file that File > Import bots... can load.
- Each self-test now says what it taught (whose rule evidence and memory was updated, exams taken, new elders).

## 1.20.2
- **Fix: the farm was filling up with eggs that never got judged.** Free roam hatches eggs often (hindsight eggs,
  graduates), and every new egg made room by dropping the weakest bot that already had a score. Bots too new to have
  a score were never picked, so matured bots kept being dropped and the farm ended up almost all "warming up", with
  hardly anyone allowed to trade. Now:
  - bots still in their first window are never dropped to make room;
  - bots that have had a full window and still can't be scored (they hardly trade) go first;
  - when 40% of the farm is still too young to judge, Free roam keeps its new lessons in the book instead of hatching
    more eggs.
  In a test that copied what your farm was doing, the old rules left every bot warming up; the new ones left most
  bots judged and several winning.
- The report for Claude now lists every bot (age, trades, status) and recent departures, not just the scored ones.

## 1.20.1
- **Fix: saved farms didn't load after updating to 1.20.0** ("'Tournament' object has no attribute 'conds'"). Farms,
  the slow farm and the Scalp lab load again with all their bots.
- If a saved farm ever fails to load, a copy of its file is now kept first (`...couldnt-load-....json` in the data
  folder), so it can't be lost.
- Fix: a rare error when the farm replay window was rebuilt while playing.

## 1.20.0
- **Exams on unseen days**: every bot now builds a record of exams on prices it never trained on (Free roam
  self-tests, and day replays on held-back days). A bot passes when its exam results are positive, mostly winning and
  steady enough to beat luck. The bar rises with how many bots the farm has tried, because the best of many bots looks
  good by chance. Bots that fail can't be BEASTS, and passing gives a bigger say. Self-tests now go first to the BEASTS
  and top bots that haven't been examined. The scoreboard, each bot's card and the Overview show it.
- **Day replays in order, with held-back exam days**: one trading day in five is never trained on and is kept for
  exams. The other days are replayed in order, oldest first (from February 2024 with the Alpaca login), so every day
  gets its turn. Every third replay is an exam: no new tryouts, no graduates, nothing learned. Holidays are found and
  skipped.
- **Real bid/ask costs**: on replayed days with real option prices, every bot now buys at the ask and sells at the bid,
  using what that ticker's options really cost to trade (learned from live quotes, refreshed weekly during replays).
  The cost grows when a contract hasn't traded for a while.
- **New things bots can learn**: four new never-rules: skip gap days, skip one weekday, skip expensive options (when
  the ticker swings much more than usual) and sit out news days. Like the others, each is graded in hindsight.
- **The right bot for the moment**: each bot keeps a record of how it does in wild or calm markets, at each time of day,
  and on news days. Its say in the vote follows its record in today's conditions. Each bot's card shows what it's best at.
- **Hindsight lessons graded forward**: eggs hatched from "what would have worked" are graded on how they do afterwards
  (their exams, or how they did when they left). Lessons that keep failing are dropped, and fewer eggs come from
  hindsight while its eggs don't hold up (down to 20% from 60%).
- **Export a report for Claude** (File menu, the Overview tab and Diagnostics): saves a .zip of what every farm is
  doing and learning (top bots and their rules, exams, Free roam log, settings, recent trades, logs). Attach it in a chat
  for analysis. API keys, passwords and account numbers are left out.
- Two new settings switches: Exams, and Right bot for the moment (both on).

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
