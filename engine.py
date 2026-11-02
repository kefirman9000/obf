"""Core logic for OBF (Options Bot Farm): strategies, simulation, wildcard tournament,
historical candles and local storage. No GUI code lives here."""
import csv
import bisect
import json
import threading
import math
import os
import importlib
import importlib.util
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

HOME_DIR = os.path.join(os.path.expanduser("~"), ".obf")
OLD_HOME_DIR = os.path.join(os.path.expanduser("~"), ".obf-old")  # (no older data folder to bring across)


def migrate_home():
    """First start after the rename: copy the old data folder (sessions, trades, saved bots) across.
    The old folder is left in place untouched. Returns True if something was copied."""
    try:
        if not os.path.exists(HOME_DIR) and os.path.isdir(OLD_HOME_DIR):
            shutil.copytree(OLD_HOME_DIR, HOME_DIR)
            return True
    except OSError:
        pass
    return False
WARM = 30  # bars skipped at the start of a backtest so indicators have data
TIMEFRAMES = (1, 2, 3, 5, 10, 15, 30, 60)  # how many app bars a bot waits between decisions (x the Bar length setting)
BAR_CHOICES = (5 / 60, 10 / 60, 0.25, 0.5, 1, 5, 15, 60)  # decision speed in minutes: 5 s, 10 s, 15 s, 30 s, 1-60 min
CANDLE_GRANS = (60, 300, 900, 3600, 21600, 86400)  # candle sizes used (seconds)
LOOKBACK = 300  # most bars any strategy looks back; longer history is trimmed for speed


class View:
    """A read-only window onto the first `end` items of a list, without copying it. Bots read price history
    through these, which keeps replays and backtests fast even with hundreds of bots and long histories."""
    __slots__ = ("seq", "end")

    def __init__(self, seq, end):
        if isinstance(seq, View):
            end, seq = min(end, seq.end), seq.seq
        self.seq, self.end = seq, max(0, min(end, len(seq)))

    def __len__(self):
        return self.end

    def __getitem__(self, k):
        if isinstance(k, slice):
            a, b, s = k.indices(self.end)
            return self.seq[a:b:s]
        if k < 0:
            k += self.end
        if not 0 <= k < self.end:
            raise IndexError("view index out of range")
        return self.seq[k]

    def __iter__(self):
        return iter(self.seq[:self.end])


def candle_gran(bar_minutes):
    """Closest candle size for a bar length. Sub-minute bars use 1-minute candles (nothing shorter is offered),
    so their history is approximate until live bars replace it."""
    sec = float(bar_minutes) * 60
    return min(CANDLE_GRANS, key=lambda g: (abs(g - sec), g)) if sec >= 60 else 60


def fmt_bar(minutes):
    """'15 sec', '1 min', '1 hr' ..."""
    m = float(minutes)
    if m < 1:
        s = round(m * 60, 1)
        return f"{s:g} sec"
    if m >= 60 and m % 60 == 0:
        return f"{m / 60:g} hr"
    return f"{m:g} min"


def tail_series(p, tf=1, keep=LOOKBACK):
    """The last `keep` closes of tf-bar candles ending at the newest bar (cheap: never copies the whole history)."""
    if tf <= 1:
        return p[-keep:]
    last = len(p) - 1
    if last < 0:
        return []
    start = last - tf * min(keep - 1, last // tf)
    return p[start::tf]


_TX_CACHE = {}


def tail_extra(p, x, tf=1, keep=LOOKBACK):
    """Highs, lows and volumes matching tail_series(p, tf, keep): each tf-bar candle gets the highest
    high, lowest low and summed volume of its bars. None when the extra data doesn't line up.
    Many bots ask for the same summary on the same bar, so it's worked out once and shared (read-only)."""
    if not x or len(x.get("h", ())) != len(p) or len(x.get("l", ())) != len(p) or len(x.get("v", ())) != len(p):
        return None
    key = (id(x["h"]), id(x["v"]), len(p), tf, keep, p[-1] if len(p) else None, x["v"][-1] if len(p) else None)
    hit = _TX_CACHE.get(key)
    if hit is not None:
        return hit
    if len(_TX_CACHE) > 4096:
        _TX_CACHE.clear()
    out = _tail_extra(p, x, tf, keep)
    _TX_CACHE[key] = out
    return out


def _tail_extra(p, x, tf=1, keep=LOOKBACK):
    if tf <= 1:
        return dict(h=x["h"][-keep:], l=x["l"][-keep:], v=x["v"][-keep:])
    last = len(p) - 1
    start = last - tf * min(keep - 1, last // tf)
    a0 = max(0, start - tf + 1)
    H, Lo, V = x["h"][a0:last + 1], x["l"][a0:last + 1], x["v"][a0:last + 1]  # one copy each, then plain lists
    h, lo, v = [], [], []
    for j in range(start, last + 1, tf):
        a, b = max(0, j - tf + 1) - a0, j + 1 - a0
        h.append(max(H[a:b]))
        lo.append(min(Lo[a:b]))
        v.append(sum(V[a:b]))
    return dict(h=h, l=lo, v=v)


def strat_signal(name, p, n, params, tf=1, x=None):
    """One strategy's signal on the newest bar, using tf-bar candles. Strategies that need highs,
    lows or volume get them when available and stay quiet when not."""
    spec = STRATS[name]
    series = tail_series(p, tf, spec.get("keep", LOOKBACK))
    if spec.get("hlv"):
        return spec["fn"](series, n // tf if tf > 1 else n, params,
                          tail_extra(p, x, tf, spec.get("keep", LOOKBACK)))
    return spec["fn"](series, n // tf if tf > 1 else n, params)


def clamp_tf(tf):
    """Nearest allowed timeframe for any value (bad input falls back to 1)."""
    try:
        tf = float(tf)
    except (TypeError, ValueError):
        return 1
    return min(TIMEFRAMES, key=lambda t: abs(t - tf))


# ---------------- network helpers ----------------
def http_get(url, timeout=10, retries=0):
    """GET with a few automatic retries for brief network blips, rate limits (429) and server errors."""
    delay = 1.0
    for attempt in range(retries + 1):
        wait = delay
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cbbf"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 500, 502, 503, 504) or attempt >= retries:
                raise
            try:
                wait = min(max(float(ex.headers.get("Retry-After", delay)), delay), 10.0)
            except (TypeError, ValueError):
                pass
        except (urllib.error.URLError, OSError):  # timeouts, DNS, dropped connections
            if attempt >= retries:
                raise
        time.sleep(wait)
        delay *= 2


# ---------------- Alpaca: stock prices, history, market hours, option chains, orders ----------------
ALPACA = {"key": "", "secret": "", "paper": True}  # filled in when you log in (data needs a free Alpaca key too)
DATA_URL = "https://data.alpaca.markets"
FEED = "iex"  # the free real-time stock feed; "sip" with a paid data plan
HIST_SIP = True  # history older than 15 minutes from the full market feed (free); the newest bars stay on FEED
_PACE = {"calls": []}
_PACE_LOCK = threading.Lock()
DATA_PER_MIN = 190  # Alpaca's free plan allows 200 data calls a minute


def _pace():
    """Keeps data calls under the free plan's limit, so long downloads slow down instead of failing."""
    while True:
        with _PACE_LOCK:
            now = time.time()
            calls = [t for t in _PACE["calls"] if now - t < 60]
            _PACE["calls"] = calls
            if len(calls) < DATA_PER_MIN:
                calls.append(now)
                return
            wait = 60 - (now - calls[0]) + 0.05
        time.sleep(min(max(wait, 0.05), 5))


def trade_url():
    return "https://paper-api.alpaca.markets" if ALPACA.get("paper", True) else "https://api.alpaca.markets"


class NeedLogin(Exception):
    pass


def alp(method, url, body=None, timeout=12, retries=1, creds=None):
    """One Alpaca API call (JSON in, JSON out)."""
    cr = creds or ALPACA
    if not cr.get("key") or not cr.get("secret"):
        raise NeedLogin("Log in with your Alpaca API key first (Account > Log in). Paper keys are free.")
    data = None if body is None else json.dumps(body).encode()
    if url.startswith(DATA_URL):
        _pace()
    delay = 1.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "APCA-API-KEY-ID": cr["key"].strip(), "APCA-API-SECRET-KEY": cr["secret"].strip(),
            "Content-Type": "application/json", "User-Agent": "obf"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as ex:
            if ex.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            try:
                msg = json.loads(ex.read() or b"{}").get("message") or ex.reason
            except Exception:
                msg = ex.reason
            raise RuntimeError(f"Alpaca said {ex.code}: {msg}") from None
        except (urllib.error.URLError, OSError):
            if attempt >= retries:
                raise
            time.sleep(delay)
            delay *= 2


def spot(coin, quote="USD"):
    return spot_many([coin]).get(coin)


def spot_many(coins, quote="USD"):
    """Latest trade price for many tickers in one request. Missing ones are left out."""
    if not coins:
        return {}
    q = urllib.parse.quote(",".join(coins))
    data = alp("GET", f"{DATA_URL}/v2/stocks/trades/latest?symbols={q}&feed={FEED}")
    out = {}
    for c, t in (data.get("trades") or {}).items():
        try:
            if float(t["p"]) > 0:
                out[c] = float(t["p"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _tf(gran):
    return {60: "1Min", 300: "5Min", 900: "15Min", 3600: "1Hour", 21600: "6Hour", 86400: "1Day"}.get(int(gran), "1Min")


def _candle_cache_path(coin, quote, gran):
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", str(coin)):
        raise ValueError(f"not a ticker: {coin!r}")
    return os.path.join(HOME_DIR, "cache", f"{coin}-{int(gran)}.json")


def _iso_ts(s_):
    return datetime.fromisoformat(s_.replace("Z", "+00:00")).timestamp()


def fetch_ohlcv(coin, gran_seconds, count, quote="USD", cache=True):
    """{'c','h','l','v','t'} of the last `count` bars (oldest first). Stocks only trade ~6.5 hours a day, so the
    request reaches back far enough in calendar time. Bars are cached on disk; later calls only fetch what's new."""
    rows, newest = {}, None
    path = _candle_cache_path(coin, quote, gran_seconds)
    if cache:
        try:
            with open(path) as f:
                rows = {int(t): tuple(r) for t, r in json.load(f).items()}
            newest = max(rows) if rows else None
        except (OSError, ValueError, TypeError, AttributeError):
            rows, newest = {}, None
    per_day = max(1, int(6.5 * 3600 // gran_seconds)) if gran_seconds < 86400 else 1
    days = int(count / per_day * 7 / 5) + 5
    start = datetime.now(timezone.utc) - timedelta(days=days)
    if newest is not None and len(rows) >= count:
        start = datetime.fromtimestamp(newest, timezone.utc)
    base = (f"{DATA_URL}/v2/stocks/{urllib.parse.quote(coin)}/bars?timeframe={_tf(gran_seconds)}&limit=10000"
            f"&adjustment=split&start={start.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    # history from the full market (every exchange; free when it's older than 15 minutes), the newest bars from FEED.
    # The free real-time feed (IEX) only sees a few % of the volume, so its volumes are scaled up to match.
    cut = datetime.now(timezone.utc) - timedelta(minutes=16)
    legs = ([(f"&feed=sip&end={cut.strftime('%Y-%m-%dT%H:%M:%SZ')}", "sip"), ("&feed=" + FEED, FEED)]
            if HIST_SIP and FEED != "sip" and start < cut else [("&feed=" + FEED, FEED)])
    got = {}
    for extra_q, feed in legs:
        token, pages, part = None, 0, {}
        while pages < 60:
            try:
                data = alp("GET", base + extra_q + (f"&page_token={token}" if token else ""), timeout=20)
            except RuntimeError:
                if feed == "sip":  # not allowed on this account: everything from FEED instead
                    break
                raise
            for b in data.get("bars") or []:
                part[int(_iso_ts(b["t"]))] = (float(b["c"]), float(b["h"]), float(b["l"]), float(b["v"]))
            token = data.get("next_page_token")
            pages += 1
            if not token:
                break
        got[feed] = part
    sip, live = got.get("sip") or {}, got.get(FEED) or {}
    if sip and live and FEED != "sip":
        both = [t for t in live if t in sip and live[t][3] > 0]
        ratio = (sum(sip[t][3] for t in both) / max(1e-9, sum(live[t][3] for t in both))) if len(both) >= 5 else VOL_RATIO.get(coin, 0)
        if ratio > 0:
            VOL_RATIO[coin] = ratio
        live = {t: (r[0], r[1], r[2], r[3] * (VOL_RATIO.get(coin) or 1)) for t, r in live.items() if t not in sip}
    elif live and FEED != "sip" and VOL_RATIO.get(coin):
        live = {t: (r[0], r[1], r[2], r[3] * VOL_RATIO[coin]) for t, r in live.items()}
    rows.update(sip)
    rows.update(live)
    if gran_seconds < 86400:
        rows = {t: r for t, r in rows.items() if regular_hours(t, gran_seconds)}
    every = sorted(rows)
    keys = every[-count:]
    seq = [rows[t] for t in keys]
    if cache and seq:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({str(t): rows[t] for t in every[-max(count, 6000):]}, f)
            os.replace(tmp, path)
        except OSError:
            pass
    return dict(c=[r[0] for r in seq], h=[r[1] for r in seq], l=[r[2] for r in seq], v=[r[3] for r in seq], t=keys)


VOL_RATIO = {}  # ticker -> full-market volume / free-feed volume, learned from bars both feeds have
HIST_START = datetime(2016, 1, 4, tzinfo=timezone.utc).timestamp()  # the oldest stock history Alpaca serves
_SIP_OK = {"ok": True}


def regular_hours(t, gran):
    """True for a bar inside the regular session (9:30 to 4 pm New York, weekdays). Options only trade then, so the
    pre- and after-market bars Alpaca also sends are left out. Daily bars always count."""
    if gran >= 86400:
        return True
    d = datetime.fromtimestamp(t, timezone.utc)
    ny = d - timedelta(hours=_ny_offset(d))
    if ny.weekday() >= 5:
        return False
    m = ny.hour * 60 + ny.minute
    first = 9 * 60 if gran >= 3600 else 9 * 60 + 30  # the 9:00 hourly bar holds the 9:30 open
    return first <= m < 16 * 60


def _hist_path(coin, gran, year):
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", str(coin)):
        raise ValueError(f"not a ticker: {coin!r}")
    return os.path.join(HOME_DIR, "history", f"{coin}-{int(gran)}", f"{year}.json")


def _load_shard(coin, gran, year):
    try:
        with open(_hist_path(coin, gran, year)) as f:
            d = json.load(f)
        return dict(spans=[tuple(x) for x in d.get("spans") or []],
                    rows={int(t): tuple(r) for t, r in zip(d["t"], zip(d["c"], d["h"], d["l"], d["v"]))})
    except (OSError, ValueError, KeyError, TypeError):
        return dict(spans=[], rows={})


def _save_shard(coin, gran, year, sh):
    p = _hist_path(coin, gran, year)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    ts = sorted(sh["rows"])
    rows = [sh["rows"][t] for t in ts]
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dict(spans=sh["spans"], t=ts, c=[r[0] for r in rows], h=[r[1] for r in rows], l=[r[2] for r in rows],
                       v=[r[3] for r in rows]), f, separators=(",", ":"))
        n = f.tell()
    os.replace(tmp, p)
    note_write(p, n)


def _merge_spans(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _missing(spans, a, b):
    out, cur = [], a
    for s0, e0 in _merge_spans(spans):
        if e0 <= cur:
            continue
        if s0 >= b:
            break
        if s0 > cur:
            out.append((cur, s0))
        cur = max(cur, e0)
    if cur < b:
        out.append((cur, b))
    return [(x, y) for x, y in out if y - x > 60]


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_bars(coin, gran, a, b, feed):
    rows, token, pages = {}, None, 0
    url0 = (f"{DATA_URL}/v2/stocks/{urllib.parse.quote(coin)}/bars?timeframe={_tf(gran)}&limit=10000&adjustment=split"
            f"&feed={feed}&start={_iso(a)}&end={_iso(b)}")
    while pages < 400:
        data = alp("GET", url0 + (f"&page_token={token}" if token else ""), timeout=30, retries=2)
        for x in data.get("bars") or []:
            t = int(_iso_ts(x["t"]))
            if regular_hours(t, gran):
                rows[t] = (float(x["c"]), float(x["h"]), float(x["l"]), float(x["v"]))
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break
    return rows


def fetch_range(coin, gran, start, end, quote="USD", note=None):
    """Bars between two dates, any time back to 2016: {'c','h','l','v','t'}, regular trading hours only. History is
    stored on disk by year, so each stretch is downloaded once; the newest 15 minutes come live from the free feed."""
    start, end = max(float(start), HIST_START), min(float(end), time.time())
    rows = {}
    cut = time.time() - 16 * 60
    y0, y1 = datetime.fromtimestamp(start, timezone.utc).year, datetime.fromtimestamp(end, timezone.utc).year
    for y in range(y0, y1 + 1):
        ya = datetime(y, 1, 1, tzinfo=timezone.utc).timestamp()
        yb = datetime(y + 1, 1, 1, tzinfo=timezone.utc).timestamp()
        a, b = max(start, ya), min(end, yb, cut)
        if a >= b:
            continue
        sh = _load_shard(coin, gran, y)
        miss = _missing(sh["spans"], a, b)
        for ma, mb in miss:
            if note:
                note(f"Downloading {coin} {datetime.fromtimestamp(ma).strftime('%b %Y')}"
                     + (f" to {datetime.fromtimestamp(mb).strftime('%b %Y')}" if mb - ma > 40 * 86400 else ""))
            got = None
            if HIST_SIP and _SIP_OK["ok"] and FEED != "sip":
                try:
                    got = _fetch_bars(coin, gran, ma, mb, "sip")
                except RuntimeError as e:
                    if "403" in str(e) or "subscription" in str(e).lower():
                        _SIP_OK["ok"] = False
                    else:
                        raise
            if got is None:
                got = _fetch_bars(coin, gran, ma, mb, FEED)
            sh["rows"].update(got)
            sh["spans"] = _merge_spans(sh["spans"] + [(int(ma), int(mb))])
        if miss:
            try:
                _save_shard(coin, gran, y, sh)
            except OSError:
                pass
        rows.update({t: r for t, r in sh["rows"].items() if start <= t <= end})
    if end > cut:  # the newest minutes, live
        try:
            live = _fetch_bars(coin, gran, max(start, cut - 3600), end, FEED)
            k = VOL_RATIO.get(coin) or 1
            rows.update({t: (r[0], r[1], r[2], r[3] * k) for t, r in live.items() if t not in rows})
        except Exception:
            pass
    ts = sorted(rows)
    seq = [rows[t] for t in ts]
    return dict(c=[r[0] for r in seq], h=[r[1] for r in seq], l=[r[2] for r in seq], v=[r[3] for r in seq], t=ts)


class NoHistory(RuntimeError):
    """There is no (or too little) history for what was asked."""


_AVAIL = {}


def coin_days(coin, quote="USD", max_age=6 * 3600):
    """The days (UTC midnight timestamps) on which there are daily bars for this ticker (a few requests, then stored
    like any other history). Tickers listed late simply have no days before that."""
    key = (coin, quote)
    hit = _AVAIL.get(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    d = fetch_range(coin, 86400, HIST_START, time.time(), quote)
    days = sorted({int(t) // 86400 * 86400 for t in d["t"]})
    _AVAIL[key] = (time.time(), days)
    return days


def common_days(coins, quote="USD"):
    """Days every one of these coins has history (sorted)."""
    sets = [set(coin_days(c, quote)) for c in coins]
    return sorted(set.intersection(*sets)) if sets else []


def coverage(days_set, a, b):
    """Share of the weekdays between a and b that are in days_set (holidays make it a little under 1)."""
    d0, d1 = int(a) // 86400 * 86400, int(b) // 86400 * 86400
    wk = [d for d in range(d0, d1 + 1, 86400) if datetime.fromtimestamp(d, timezone.utc).weekday() < 5]
    return sum(1 for d in wk if d in days_set) / max(1, len(wk))


def history_text(coin, quote="USD"):
    """'BTC: Jul 2015 to now' style description of a coin's history, including any long gap."""
    days = coin_days(coin, quote)
    if not days:
        return f"{coin}: no history"
    gaps = [(days[i - 1], days[i]) for i in range(1, len(days)) if days[i] - days[i - 1] > 10 * 86400]
    fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%b %Y")
    txt = f"{coin}: {fmt(days[0])} to " + ("now" if time.time() - days[-1] < 3 * 86400 else fmt(days[-1]))
    if gaps:
        txt += " (missing " + ", ".join(f"{fmt(a + 86400)} to {fmt(b - 86400)}" for a, b in gaps[:2]) + ")"
    return txt


def longest_run(times, gran):
    """(start index, end index) of the longest stretch of these bar times with no gap over 5 days (weekends and
    holidays are normal for stocks)."""
    if not times:
        return 0, 0
    lim = max(6 * gran, 5 * 86400)
    best, start = (0, 1), 0
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > lim:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = i
    if len(times) - start > best[1] - best[0]:
        best = (start, len(times))
    return best


def bars_per_day(gran):
    """Regular-session candles in one trading day."""
    return 1 if gran >= 86400 else max(1, int(round(6.5 * 3600 / gran)))


def common_stretch(data):
    """Lines several tickers up on the bar times they all have. -> (closes, extra)"""
    keys = [c for c, d in data.items() if d.get("t")]
    if not keys:
        return {}, {}
    shared = set(data[keys[0]]["t"])
    for c in keys[1:]:
        shared &= set(data[c]["t"])
    ts = sorted(shared)
    closes, extra = {}, {}
    for c in keys:
        d = data[c]
        idx = {t: i for i, t in enumerate(d["t"])}
        ii = [idx[t] for t in ts]
        closes[c] = [d["c"][i] for i in ii]
        extra[c] = {k: [d[k][i] for i in ii] for k in ("h", "l", "v")}
        extra[c]["t"] = list(ts)
    return closes, extra


def latest_volume(coin, gran_seconds, quote="USD"):
    """Volume of the latest 1-minute bar (None if unavailable)."""
    data = alp("GET", f"{DATA_URL}/v2/stocks/bars/latest?symbols={urllib.parse.quote(coin)}&feed={FEED}")
    b = (data.get("bars") or {}).get(coin)
    return float(b["v"]) * max(1, gran_seconds // 60) if b else None


_CLOCK = {"at": 0.0, "data": None}


def market_clock(max_age=60):
    """{'is_open', 'next_open', 'next_close'} (timestamps), cached for a minute."""
    if _CLOCK["data"] is None or time.time() - _CLOCK["at"] > max_age:
        d = alp("GET", f"{trade_url()}/v2/clock")
        _CLOCK.update(at=time.time(), data=dict(is_open=bool(d.get("is_open")), next_open=_iso_ts(d["next_open"]),
                                                next_close=_iso_ts(d["next_close"])))
    return dict(_CLOCK["data"])


def parse_occ(sym):
    """'SPY261113C00450000' -> (underlying, expiry timestamp (4 pm New York), 'call'/'put', strike)."""
    m = re.fullmatch(r"([A-Z.]{1,6})(\d{6})([CP])(\d{8})", sym or "")
    if not m:
        return None
    d = datetime.strptime(m.group(2), "%y%m%d").replace(hour=20, tzinfo=timezone.utc)
    return m.group(1), d.timestamp(), "call" if m.group(3) == "C" else "put", int(m.group(4)) / 1000


def option_chain(under, exp_from=None, exp_to=None, typ=None, strike_lo=None, strike_hi=None):
    """Live option chain: [{symbol, type, K, exp, bid, ask, last, iv, delta, gamma, theta, vega}], from Alpaca's free
    'indicative' option feed (prices are close to, but not exactly, the real quotes; OPRA with a paid plan)."""
    q = [f"feed={'opra' if FEED == 'sip' else 'indicative'}", "limit=1000"]
    if exp_from:
        q.append(f"expiration_date_gte={exp_from}")
    if exp_to:
        q.append(f"expiration_date_lte={exp_to}")
    if typ:
        q.append(f"type={typ}")
    if strike_lo is not None:
        q.append(f"strike_price_gte={strike_lo:g}")
    if strike_hi is not None:
        q.append(f"strike_price_lte={strike_hi:g}")
    out, token, pages = [], None, 0
    while pages < 10:
        d = alp("GET", f"{DATA_URL}/v1beta1/options/snapshots/{urllib.parse.quote(under)}?" + "&".join(q)
                + (f"&page_token={token}" if token else ""), timeout=20)
        for sym, sn in (d.get("snapshots") or {}).items():
            p_ = parse_occ(sym)
            if not p_:
                continue
            lq, lt, g = sn.get("latestQuote") or {}, sn.get("latestTrade") or {}, sn.get("greeks") or {}
            out.append(dict(symbol=sym, under=p_[0], exp=p_[1], type=p_[2], K=p_[3], bid=float(lq.get("bp") or 0),
                            ask=float(lq.get("ap") or 0), last=float(lt.get("p") or 0), iv=sn.get("impliedVolatility"),
                            delta=g.get("delta"), gamma=g.get("gamma"), theta=g.get("theta"), vega=g.get("vega")))
        token = d.get("next_page_token")
        pages += 1
        if not token:
            break
    return sorted(out, key=lambda r: (r["exp"], r["K"], r["type"]))


def option_oi(under, exp_from=None, exp_to=None, typ=None):
    """{option symbol: open interest} from Alpaca's contract list (open interest is updated once a day)."""
    q = [f"underlying_symbols={urllib.parse.quote(under)}", "limit=10000", "status=active"]
    if exp_from:
        q.append(f"expiration_date_gte={exp_from}")
    if exp_to:
        q.append(f"expiration_date_lte={exp_to}")
    if typ:
        q.append(f"type={typ}")
    out, token = {}, None
    for _ in range(5):
        d = alp("GET", f"{trade_url()}/v2/options/contracts?" + "&".join(q) + (f"&page_token={token}" if token else ""))
        for r in d.get("option_contracts") or []:
            try:
                out[r["symbol"]] = int(float(r.get("open_interest") or 0))
            except (TypeError, ValueError, KeyError):
                continue
        token = d.get("next_page_token")
        if not token:
            break
    return out


def option_quotes(symbols):
    """{option symbol: (bid, ask, time)} for specific contracts."""
    out = {}
    syms = [x for x in symbols if x]
    for k in range(0, len(syms), 100):
        q = urllib.parse.quote(",".join(syms[k:k + 100]))
        d = alp("GET", f"{DATA_URL}/v1beta1/options/snapshots?symbols={q}&feed={'opra' if FEED == 'sip' else 'indicative'}")
        for sym, sn in (d.get("snapshots") or {}).items():
            lq = sn.get("latestQuote") or {}
            out[sym] = (float(lq.get("bp") or 0), float(lq.get("ap") or 0), time.time())
    return out


def liquid(r, max_spread_pct=15.0, min_oi=50):
    """Is this contract busy enough to trade? A narrow bid/ask gap and enough open contracts (when known)."""
    bid, ask = r.get("bid") or 0, r.get("ask") or 0
    if ask <= 0:
        return False
    if max_spread_pct and (bid <= 0 or (ask - bid) / ((ask + bid) / 2) * 100 > max_spread_pct):
        return False
    oi = r.get("oi")
    if min_oi and oi is not None and oi < min_oi:
        return False
    return True


def pick_contract(chain, S, typ, dte, otm_pct, now=None, min_sessions=1, max_spread_pct=0.0, min_oi=0):
    """The listed contract closest to what a bot wants: its type, about dte days out, about otm_pct% out of the money;
    only ones inside the price range, liquid enough, and with more than min_sessions trading days left."""
    now = now or time.time()
    want_exp = now + dte * 86400
    want_K = S * (1 + otm_pct / 100) if typ == "call" else S * (1 - otm_pct / 100)
    cands = [r for r in chain if r["type"] == typ and r["exp"] > now + 86400 and r["ask"] > 0 and prem_ok(r["ask"])
             and sessions_left(r["exp"], now) > min_sessions and liquid(r, max_spread_pct, min_oi)]
    if not cands:
        return None
    return min(cands, key=lambda r: (abs(r["exp"] - want_exp) / 86400 / max(3, dte)) + abs(r["K"] - want_K) / S * 10)


# ---------------- Economic calendar (release dates from FRED, the St. Louis Fed's free data service) ----------------
# kind: (FRED release id, name, release hour and minute in New York)
EVENT_KINDS = {
    "cpi":    (10, "CPI inflation", 8, 30),
    "jobs":   (50, "Jobs report", 8, 30),
    "fomc":   (101, "Fed decision", 14, 0),
    "gdp":    (53, "GDP", 8, 30),
    "pce":    (54, "PCE inflation", 8, 30),
    "retail": (9, "Retail sales", 8, 30),
}
BIG_EVENTS = ("cpi", "jobs", "fomc")
_EVENTS = {"data": None, "mtime": 0}


def _ny_offset(d):
    """Hours New York is behind UTC on date d (daylight saving: 2nd Sunday of March to 1st Sunday of November)."""
    def nth_sunday(y, m, nth):
        first = datetime(y, m, 1)
        return 1 + (6 - first.weekday()) % 7 + 7 * (nth - 1)
    start = datetime(d.year, 3, nth_sunday(d.year, 3, 2))
    end = datetime(d.year, 11, nth_sunday(d.year, 11, 1))
    return 4 if start <= datetime(d.year, d.month, d.day) < end else 5


def ny_time(date_str, hh, mm):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.replace(hour=hh, minute=mm, tzinfo=timezone.utc).timestamp() + _ny_offset(d) * 3600


def _events_path():
    return os.path.join(HOME_DIR, "cache", "events.json")


def fetch_events(fred_key, start="2015-01-01"):
    """Downloads past and scheduled release times for every EVENT_KINDS entry and saves them. -> {kind: [ts, ...]}"""
    out, errs = {}, []
    for kind, (rid, name, hh, mm) in EVENT_KINDS.items():
        url = ("https://api.stlouisfed.org/fred/release/dates?file_type=json&include_release_dates_with_no_data=true"
               f"&sort_order=asc&limit=10000&realtime_start={start}&release_id={rid}&api_key={urllib.parse.quote(fred_key.strip())}")
        try:
            d = json.loads(http_get(url, timeout=20, retries=2))
            out[kind] = sorted({ny_time(r["date"], hh, mm) for r in d.get("release_dates") or [] if r.get("date")})
        except Exception as e:
            errs.append(f"{name}: {e}")
    if not out:
        raise RuntimeError("; ".join(errs) or "no release dates came back")
    os.makedirs(os.path.dirname(_events_path()), exist_ok=True)
    tmp = _events_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dict(fetched=time.time(), events=out), f)
    os.replace(tmp, _events_path())
    _EVENTS["data"] = None
    return out, errs


def events():
    """{kind: [release times]} from the saved calendar ({} if it was never downloaded). Re-read when the file changes,
    so worker processes see it too."""
    try:
        mt = os.path.getmtime(_events_path())
    except OSError:
        return {}
    if _EVENTS["data"] is None or mt != _EVENTS["mtime"]:
        try:
            with open(_events_path()) as f:
                _EVENTS["data"] = {k: v for k, v in (json.load(f).get("events") or {}).items() if k in EVENT_KINDS}
        except (OSError, ValueError):
            _EVENTS["data"] = {}
        _EVENTS["mtime"] = mt
    return _EVENTS["data"]


def events_fetched():
    try:
        with open(_events_path()) as f:
            return float(json.load(f).get("fetched") or 0)
    except (OSError, ValueError):
        return 0.0


def next_event(ts, kinds=BIG_EVENTS):
    """(kind, time) of the next release after ts, or (None, None)."""
    best = (None, None)
    ev = events()
    for k in kinds:
        lst = ev.get(k) or []
        i = bisect.bisect_right(lst, ts)
        if i < len(lst) and (best[1] is None or lst[i] < best[1]):
            best = (k, lst[i])
    return best


def last_event(ts, kinds=BIG_EVENTS):
    best = (None, None)
    ev = events()
    for k in kinds:
        lst = ev.get(k) or []
        i = bisect.bisect_right(lst, ts) - 1
        if i >= 0 and (best[1] is None or lst[i] > best[1]):
            best = (k, lst[i])
    return best


def upcoming_events(now=None, days=14):
    now = now or time.time()
    ev = events()
    out = [(t, k) for k in EVENT_KINDS for t in ev.get(k) or [] if now - 3600 <= t <= now + days * 86400]
    return sorted(out)


def _bar_time(extra, c, sim=None):
    t = ((extra or {}).get(c) or {}).get("t")
    if t:
        return t[-1]
    return getattr(sim, "now", None) or time.time()


# ---------------- Interactive Brokers (through IB Gateway / Trader Workstation on your computer) ----------------
IB_PORTS = {"IB Gateway, paper (4002)": 4002, "IB Gateway, live (4001)": 4001,
            "Trader Workstation, paper (7497)": 7497, "Trader Workstation, live (7496)": 7496}


def ib_lib():
    """The IBKR library: ib_async (Python 3.10+) or the older ib_insync (same interface). None if neither is installed."""
    for name in ("ib_async", "ib_insync"):
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def ib_pip_spec():
    # pinned to known releases, so a future compromised upload can't sneak in
    return "ib_async==2.0.1" if sys.version_info >= (3, 10) else "ib_insync==0.9.86"


def is_local_host(h):
    return str(h or "").strip().lower() in ("127.0.0.1", "localhost", "::1", "")


class IBBridge:
    """Talks to IB Gateway / TWS. The IBKR library is asyncio-based, so all of it lives on one background thread
    (with its own event loop); the app hands it jobs with call(fn) and waits for the answer."""

    def __init__(self):
        import queue as _q
        self._q = _q.Queue()
        self.thread = None
        self.ib = None
        self.lib = None
        self.account = ""
        self.port = None
        self.error = ""

    def _run(self):
        import asyncio
        import queue as _q
        asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            self.lib = ib_lib()
            self.ib = self.lib.IB() if self.lib else None
        except Exception as e:
            self.error = str(e)
        while True:
            try:
                fn, box = self._q.get(timeout=0.25)
            except _q.Empty:
                try:
                    if self.ib is not None and self.ib.isConnected():
                        self.ib.sleep(0.05)  # keep the connection's messages flowing
                except Exception:
                    pass
                continue
            try:
                box.put((True, fn(self.ib)))
            except Exception as e:
                box.put((False, e))

    def call(self, fn, timeout=90):
        import queue as _q
        if self.thread is None or not self.thread.is_alive():
            import threading
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        box = _q.Queue()
        self._q.put((fn, box))
        ok, res = box.get(timeout=timeout)
        if not ok:
            raise res
        return res

    def connected(self):
        try:
            return self.ib is not None and self.ib.isConnected()
        except Exception:
            return False

    @property
    def paper(self):
        return self.account.startswith("DU") or self.port in (4002, 7497)

    def connect(self, host, port, client_id):
        if not is_local_host(host):
            raise RuntimeError(f"OBF only connects to IB Gateway / TWS on this computer (127.0.0.1), not {host}: the "
                               "connection isn't encrypted, so it should never cross a network.")

        def job(ib):
            if self.lib is None:
                raise RuntimeError("The Interactive Brokers add-on isn't installed yet (click 'Install the IBKR add-on').")
            if ib.isConnected():
                ib.disconnect()
            ib.connect(host, int(port), clientId=int(client_id), timeout=10)
            ib.reqMarketDataType(4)  # live quotes if you subscribe to them, otherwise delayed ones (free)
            self.realtime = None  # learned from the first quotes: True = live data subscription, False = delayed
            accts = ib.managedAccounts()
            self.account, self.port = (accts[0] if accts else ""), int(port)
            return self.account
        return self.call(job, 30)

    def disconnect(self):
        try:
            self.call(lambda ib: ib.disconnect() if ib and ib.isConnected() else None, 10)
        except Exception:
            pass

    def funds(self):
        """Money available to trade (AvailableFunds, in USD)."""
        def job(ib):
            vals = {v.tag: v.value for v in ib.accountSummary() if v.currency in ("USD", "BASE", "")}
            for tag in ("AvailableFunds", "BuyingPower", "TotalCashValue", "NetLiquidation"):
                try:
                    if vals.get(tag) is not None:
                        return float(vals[tag])
                except (TypeError, ValueError):
                    continue
            return 0.0
        return self.call(job, 30)

    def _option(self, under, exp_ts, typ, K):
        d = datetime.fromtimestamp(exp_ts, timezone.utc).strftime("%Y%m%d")
        return self.lib.Option(under, d, float(K), "C" if typ == "call" else "P", "SMART", currency="USD")

    @staticmethod
    def _num(x):
        try:
            x = float(x)
            return x if x == x and x > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    def quote(self, under, exp_ts, typ, K):
        """(bid, ask, IB contract) for one option (delayed quotes without a market-data subscription)."""
        def job(ib):
            c = self._option(under, exp_ts, typ, K)
            if not ib.qualifyContracts(c):
                raise RuntimeError(f"IBKR doesn't list {contract_text(dict(under=under, exp=exp_ts, type=typ, K=K))}")
            t = ib.reqTickers(c)[0]
            return self._num(t.bid), self._num(t.ask), c
        return self.call(job, 30)

    def quotes(self, contracts):
        """{option symbol: (bid, ask, time)} for [(under, exp_ts, typ, K), ...]. Also notes whether IBKR sent
        real-time quotes (you have an options data subscription) or delayed ones."""
        def job(ib):
            cs, keys = [], []
            for under, exp, typ, K in contracts:
                c = self._option(under, exp, typ, K)
                cs.append(c)
                keys.append(occ_symbol(under, exp, typ, K))
            ok = ib.qualifyContracts(*cs) or []
            okset = {id(c) for c in ok}
            pairs = [(k, c) for k, c in zip(keys, cs) if id(c) in okset or getattr(c, "conId", 0)]
            out = {}
            if pairs:
                for (k, _), t in zip(pairs, ib.reqTickers(*[c for _, c in pairs])):
                    b, a_ = self._num(t.bid), self._num(t.ask)
                    if b or a_:
                        out[k] = (b, a_, time.time())
                    mdt = getattr(t, "marketDataType", None)
                    if mdt in (1, 2):
                        self.realtime = True
                    elif mdt in (3, 4):
                        self.realtime = False
            return out
        return self.call(job, 60)

    def pick(self, under, S, typ, dte, otm_pct):
        """The listed IBKR contract closest to what the bots want (used when there's no Alpaca chain to choose from)."""
        def job(ib):
            stk = self.lib.Stock(under, "SMART", "USD")
            ib.qualifyContracts(stk)
            chains = ib.reqSecDefOptParams(stk.symbol, "", stk.secType, stk.conId)
            ch = next((x for x in chains if x.exchange == "SMART"), chains[0] if chains else None)
            if not ch:
                raise RuntimeError(f"no option chain for {under} at IBKR")
            now = time.time()
            exps = sorted(datetime.strptime(e, "%Y%m%d").replace(hour=20, tzinfo=timezone.utc).timestamp() for e in ch.expirations)
            exps = [e for e in exps if e > now + 86400] or exps
            exp = min(exps, key=lambda e: abs(e - (now + dte * 86400)))
            want = S * (1 + otm_pct / 100) if typ == "call" else S * (1 - otm_pct / 100)
            K = min(ch.strikes, key=lambda k: abs(k - want))
            return exp, float(K)
        return self.call(job, 60)

    def held(self, under, exp_ts, typ, K):
        """Contracts of this option the IBKR account holds right now (negative = short)."""
        d = datetime.fromtimestamp(exp_ts, timezone.utc).strftime("%Y%m%d")
        right = "C" if typ == "call" else "P"

        def job(ib):
            tot = 0.0
            for p in ib.positions():
                c = p.contract
                if (getattr(c, "secType", "") == "OPT" and c.symbol == under and str(c.lastTradeDateOrContractMonth)[:8] == d
                        and abs(float(c.strike) - float(K)) < 1e-6 and c.right == right):
                    tot += float(p.position)
            return tot
        return self.call(job, 30)

    def order(self, under, exp_ts, typ, K, qty, side, limit=None, wait=20, held=None):
        """Places a limit (or market) order and waits for the fill. -> (filled contracts, avg price per share)."""
        check_order(side, qty, held)

        def job(ib):
            c = self._option(under, exp_ts, typ, K)
            if not ib.qualifyContracts(c):
                raise RuntimeError("IBKR doesn't list that contract")
            o = (self.lib.LimitOrder(side.upper(), int(qty), round(float(limit), 2)) if limit
                 else self.lib.MarketOrder(side.upper(), int(qty)))
            tr = ib.placeOrder(c, o)
            until = time.time() + wait
            while not tr.isDone() and time.time() < until:
                ib.sleep(0.5)
            if not tr.isDone():
                ib.cancelOrder(tr.order)
                ib.sleep(1.5)
            st = tr.orderStatus
            return float(st.filled or 0), float(st.avgFillPrice or 0)
        return self.call(job, wait + 30)

    def lapse(self, under, exp_ts, typ, K, qty):
        """Tells IBKR NOT to exercise this long option at expiry (it expires worthless instead of turning into shares).
        A last resort when it couldn't be sold."""
        def job(ib):
            c = self._option(under, exp_ts, typ, K)
            if not ib.qualifyContracts(c):
                raise RuntimeError("IBKR doesn't list that contract")
            ib.exerciseOptions(c, 2, int(qty), self.account, 0)  # 2 = lapse
            return True
        return self.call(job, 30)

    def day_trades_left(self):
        """IBKR's own count of day trades left before the pattern-day-trader rule (None if it doesn't say)."""
        def job(ib):
            for v in ib.accountSummary():
                if v.tag == "DayTradesRemaining":
                    try:
                        return int(float(v.value))
                    except (TypeError, ValueError):
                        return None
            return None
        return self.call(job, 30)

    def equity(self):
        def job(ib):
            for v in ib.accountSummary():
                if v.tag == "NetLiquidation" and v.currency in ("USD", "BASE", ""):
                    return float(v.value)
            return None
        return self.call(job, 30)

    def cancel_all(self):
        try:
            self.call(lambda ib: ib.reqGlobalCancel(), 15)
        except Exception:
            pass


IB = IBBridge()


def alp_account(creds=None):
    return alp("GET", f"{trade_url() if not creds else ('https://paper-api.alpaca.markets' if creds.get('paper', True) else 'https://api.alpaca.markets')}/v2/account",
               creds=creds)


class UnsafeOrder(RuntimeError):
    pass


def check_order(side, qty, held=None):
    """The safety lock: OBF only BUYS options to open and SELLS to close contracts it holds, never more than it holds.
    No selling to open (naked / uncovered), so no trade can lose more than what was paid for it."""
    if side == "buy":
        return
    if side != "sell":
        raise UnsafeOrder(f"unknown order side {side!r}")
    if held is None or int(qty) > int(held) or int(qty) <= 0:
        raise UnsafeOrder(f"blocked: selling {qty} contract(s) while holding {held or 0} would open a short (uncovered) "
                          f"position. OBF only sells contracts it owns.")


def alp_order(symbol, qty, side, limit=None, tif="day", held=None):
    check_order(side, qty, held)
    body = dict(symbol=symbol, qty=str(int(qty)), side=side, type="limit" if limit else "market", time_in_force=tif)
    if limit:
        body["limit_price"] = f"{limit:.2f}"
    return alp("POST", f"{trade_url()}/v2/orders", body)


def alp_get_order(oid):
    return alp("GET", f"{trade_url()}/v2/orders/{oid}")


def alp_cancel(oid):
    return alp("DELETE", f"{trade_url()}/v2/orders/{oid}")


def alp_positions():
    return alp("GET", f"{trade_url()}/v2/positions")


def to_dict(r):
    return r if isinstance(r, dict) else r.to_dict()


# ---------------- strategies: fn(prices, bar_index, params) -> "buy"/"sell"/None ----------------
def _avg(p, n, off=0):
    seg = p[len(p) - n - off: len(p) - off]
    return sum(seg) / n


def sig_sma(p, n, a):
    f, s = int(a["fast"]), int(a["slow"])
    if f >= s or len(p) < s + 1:
        return None
    f0, s0, f1, s1 = _avg(p, f, 1), _avg(p, s, 1), _avg(p, f), _avg(p, s)
    if f0 <= s0 and f1 > s1:
        return "buy"
    if f0 >= s0 and f1 < s1:
        return "sell"


def sig_rsi(p, n, a):
    k = int(a["period"])
    if len(p) < k + 1:
        return None
    d = [p[i] - p[i - 1] for i in range(len(p) - k, len(p))]
    gain = sum(x for x in d if x > 0) / k
    loss = -sum(x for x in d if x < 0) / k
    rsi = 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return "buy" if rsi < a["lo"] else "sell" if rsi > a["hi"] else None


def sig_mom(p, n, a):
    k = int(a["n"])
    if len(p) < k + 1:
        return None
    ch = p[-1] / p[-1 - k] - 1
    thr = a["thr"] / 100
    return "buy" if ch > thr else "sell" if ch < -thr else None


def sig_boll(p, n, a):
    k = int(a["n"])
    if len(p) < k:
        return None
    w = p[-k:]
    m = sum(w) / k
    sd = (sum((x - m) ** 2 for x in w) / k) ** 0.5
    if p[-1] < m - a["k"] * sd:
        return "buy"
    if p[-1] > m + a["k"] * sd:
        return "sell"


def sig_breakout(p, n, a):
    k = int(a["n"])
    if len(p) < k + 1:
        return None
    prev = p[-k - 1:-1]
    return "buy" if p[-1] > max(prev) else "sell" if p[-1] < min(prev) else None


def _ema(vals, k):
    m, e, out = 2.0 / (k + 1), vals[0], [vals[0]]
    for v in vals[1:]:
        e = v * m + e * (1 - m)
        out.append(e)
    return out


def sig_macd(p, n, a):
    f, s, g = int(a["fast"]), int(a["slow"]), int(a["signal"])
    if f >= s or len(p) < s + g + 2:
        return None
    seg = p[-(s * 3 + g):]
    ef, es = _ema(seg, f), _ema(seg, s)
    macd = [x - y for x, y in zip(ef, es)]
    sig = _ema(macd, g)
    d0, d1 = macd[-2] - sig[-2], macd[-1] - sig[-1]
    if d0 <= 0 < d1:
        return "buy"
    if d0 >= 0 > d1:
        return "sell"


def sig_revert(p, n, a):
    k = int(a["n"])
    if len(p) < k:
        return None
    dev = (p[-1] / _avg(p, k) - 1) * 100
    return "buy" if dev < -a["thr"] else "sell" if dev > a["thr"] else None


def sig_dca(p, n, a):
    return "buy" if n % int(a["every"]) == 0 else None


def sig_ema(p, n, a):
    """Fast/slow exponential average crossover. Reacts quicker than SMA, good for short bars."""
    f, s = int(a["fast"]), int(a["slow"])
    if f >= s or len(p) < s + 2:
        return None
    seg = p[-(s * 3):]
    ef, es = _ema(seg, f), _ema(seg, s)
    d0, d1 = ef[-2] - es[-2], ef[-1] - es[-1]
    gap = abs(d1) / es[-1] * 100 if es[-1] else 0
    if gap < a.get("min_gap", 0):  # ignore crossings too small to beat fees
        return None
    if d0 <= 0 < d1:
        return "buy"
    if d0 >= 0 > d1:
        return "sell"


def sig_stoch(p, n, a):
    """Stochastic oscillator on closes: where the price sits in its recent range (0-100).
    Buys when it climbs back up out of the bottom zone, sells when it drops back out of the top zone."""
    k = int(a["n"])
    if len(p) < k + 1:
        return None

    def pos(w):
        lo, hi = min(w), max(w)
        return 50.0 if hi == lo else (w[-1] - lo) / (hi - lo) * 100
    k0, k1 = pos(p[-k - 1:-1]), pos(p[-k:])
    if k0 < a["lo"] <= k1:
        return "buy"
    if k0 > a["hi"] >= k1:
        return "sell"


def _rsi(p, k):
    d = [p[i] - p[i - 1] for i in range(len(p) - k, len(p))]
    gain = sum(x for x in d if x > 0) / k
    loss = -sum(x for x in d if x < 0) / k
    return 100 if loss == 0 else 100 - 100 / (1 + gain / loss)


def sig_volbreak(p, n, a, x=None):
    """Breakout that only counts when volume is well above normal (a real crowd behind the move)."""
    k = int(a["n"])
    if not x or len(p) < k + 2:
        return None
    vol = x["v"]
    base = vol[-k - 1:-1]
    avgv = sum(base) / k
    if avgv <= 0:
        return None
    if p[-1] > max(x["h"][-k - 1:-1]) and vol[-1] >= a["vmult"] * avgv:
        return "buy"
    if p[-1] < min(x["l"][-k - 1:-1]):
        return "sell"


def sig_vwap(p, n, a, x=None):
    """Volume-weighted average price over the lookback. Buys well below it, sells well above it."""
    k = int(a["n"])
    if not x or len(p) < k:
        return None
    h, lo, v = x["h"][-k:], x["l"][-k:], x["v"][-k:]
    tv = sum(v)
    if tv <= 0:
        return None
    vw = sum((h[i] + lo[i] + p[-k + i]) / 3 * v[i] for i in range(k)) / tv
    dev = (p[-1] / vw - 1) * 100
    return "buy" if dev < -a["thr"] else "sell" if dev > a["thr"] else None


def sig_atr(p, n, a, x=None):
    """ATR channel (Keltner style): buys a push above the average plus m x the typical bar range
    (true range, from highs and lows), sells a drop below the average minus that."""
    k, m = int(a["n"]), a["m"]
    if not x or len(p) < k + 2:
        return None
    h, lo = x["h"], x["l"]
    tr = [max(h[i] - lo[i], abs(h[i] - p[i - 1]), abs(lo[i] - p[i - 1])) for i in range(len(p) - k, len(p))]
    atr = sum(tr) / k
    mid = _ema(p[-(k * 3):], k)[-1]
    if p[-1] > mid + m * atr:
        return "buy"
    if p[-1] < mid - m * atr:
        return "sell"


def sig_supertrend(p, n, a, x=None):
    """Supertrend: a trailing band m x ATR away from the price that flips sides when the trend turns."""
    k, m = int(a["n"]), a["m"]
    if not x or len(p) < k * 3:
        return None
    h, lo = x["h"], x["l"]
    L = len(p)
    tr = [max(h[i] - lo[i], abs(h[i] - p[i - 1]), abs(lo[i] - p[i - 1])) for i in range(L - k * 3 + 1, L)]
    up, prev_up, start = None, None, L - k * 2
    for i in range(start, L):
        atr = sum(tr[i - start:i - start + k]) / k
        mid = (h[i] + lo[i]) / 2
        upper, lower = mid + m * atr, mid - m * atr
        if up is None:
            up = p[i] > mid
            band = lower if up else upper
            continue
        prev_up = up
        if up:
            band = max(band, lower) if prev_up else lower
            if p[i] < band:
                up, band = False, upper
        else:
            band = min(band, upper)
            if p[i] > band:
                up, band = True, lower
    if prev_up is None:
        return None
    if up and not prev_up:
        return "buy"
    if prev_up and not up:
        return "sell"


def sig_ichimoku(p, n, a, x=None):
    """Ichimoku-style cross: the fast midline ((highest high + lowest low) / 2 over a short window) crossing the
    slow midline over a long window, only buying with the price above the slow line."""
    f, s = int(a["fast"]), int(a["slow"])
    if not x or f >= s or len(p) < s + 2:
        return None
    h, lo = x["h"], x["l"]

    def mid(k, off):
        hh, ll = h[len(h) - k - off:len(h) - off], lo[len(lo) - k - off:len(lo) - off]
        return (max(hh) + min(ll)) / 2
    f0, s0, f1, s1 = mid(f, 1), mid(s, 1), mid(f, 0), mid(s, 0)
    if f0 <= s0 and f1 > s1 and p[-1] > s1:
        return "buy"
    if f0 >= s0 and f1 < s1:
        return "sell"


def sig_roc(p, n, a):
    """Rate of change: % change over a lookback, crossing its own short average (momentum turning)."""
    k, sm = int(a["n"]), int(a["smooth"])
    if len(p) < k + sm + 2:
        return None
    roc = [(p[i] / p[i - k] - 1) * 100 for i in range(len(p) - sm - 1, len(p))]
    s0, s1 = sum(roc[:-1]) / sm, sum(roc[1:]) / sm
    if roc[-2] <= s0 and roc[-1] > s1 and roc[-1] > 0:
        return "buy"
    if roc[-2] >= s0 and roc[-1] < s1 and roc[-1] < 0:
        return "sell"


def sig_ribbon(p, n, a):
    """Moving-average ribbon: three averages stacked in order (fast > mid > slow) means a healthy uptrend: buy
    when they line up, sell when the fast one drops below the middle one."""
    f, m, s = int(a["fast"]), int(a["mid"]), int(a["slow"])
    if not f < m < s or len(p) < s * 3:
        return None
    seg = p[-(s * 3):]
    ef, em, es = _ema(seg, f), _ema(seg, m), _ema(seg, s)
    now = ef[-1] > em[-1] > es[-1]
    before = ef[-2] > em[-2] > es[-2]
    if now and not before:
        return "buy"
    if ef[-1] < em[-1] and ef[-2] >= em[-2]:
        return "sell"


def sig_trend_dip(p, n, a):
    """Buys short dips (low RSI) only while the price is above its long average (an uptrend).
    Sells on a pop (high RSI) or when the uptrend breaks."""
    t, k = int(a["trend"]), int(a["period"])
    if len(p) < max(t, k + 1):
        return None
    up = p[-1] > _avg(p, t)
    r = _rsi(p, k)
    if up and r < a["lo"]:
        return "buy"
    if r > a["hi"] or not up:
        return "sell"


# ---- scalp instincts: fast, in-and-out signals for the scalp breed (seconds to minutes, never overnight) ----
def sig_micro_pullback(p, n, a, x=None):
    """Micro pullback: in a short-term trend (price above a rising fast EMA), wait for a pause of a few bars that
    holds above the EMA, then buy the first bar that closes above the previous bar's high. Mirror for puts."""
    k, pb = int(a["n"]), int(a["pull"])
    if not x or len(p) < k * 3 + pb + 2:
        return None
    h, lo = x["h"], x["l"]
    e = _ema(p[-(k * 3 + pb + 2):], k)
    rising, falling = e[-1] > e[-1 - pb - 1], e[-1] < e[-1 - pb - 1]
    pulled = all(p[-1 - i] <= p[-2 - i] for i in range(1, pb + 1))
    popped = all(p[-1 - i] >= p[-2 - i] for i in range(1, pb + 1))
    if rising and pulled and min(lo[-pb - 1:-1]) >= e[-2] * 0.999 and p[-1] > h[-2]:
        return "buy"
    if falling and popped and max(h[-pb - 1:-1]) <= e[-2] * 1.001 and p[-1] < lo[-2]:
        return "sell"


def sig_volume_burst(p, n, a, x=None):
    """Volume burst: one bar trades several times its usual volume, moves at least thr %, and closes near its own
    high (buy) or low (sell). Rides the first push of a sudden crowd."""
    k = int(a["n"])
    if not x or len(p) < k + 2:
        return None
    v, h, lo = x["v"], x["h"], x["l"]
    avg = sum(v[-k - 1:-1]) / k
    if avg <= 0 or v[-1] < a["vmult"] * avg or not p[-2]:
        return None
    mv = (p[-1] / p[-2] - 1) * 100
    rng = h[-1] - lo[-1]
    if rng <= 0:
        return None
    where = (p[-1] - lo[-1]) / rng  # 1 = closed at the bar's high, 0 = at its low
    if mv >= a["thr"] and where >= 0.7:
        return "buy"
    if mv <= -a["thr"] and where <= 0.3:
        return "sell"


def sig_vwap_reclaim(p, n, a, x=None):
    """VWAP reclaim: the price crosses back over its short volume-weighted average on above-normal volume. Crossing
    up buys, crossing down sells (the opposite of a snap-back: it trades the cross, not the stretch)."""
    k = int(a["n"])
    if not x or len(p) < k + 2:
        return None
    h, lo, v = x["h"][-k:], x["l"][-k:], x["v"][-k:]
    tv = sum(v)
    if tv <= 0:
        return None
    vw = sum((h[i] + lo[i] + p[-k + i]) / 3 * v[i] for i in range(k)) / tv
    if v[-1] < a["vmin"] * tv / k:
        return None
    if p[-2] <= vw < p[-1]:
        return "buy"
    if p[-2] >= vw > p[-1]:
        return "sell"


def sig_range_scalp(p, n, a, x=None):
    """Range scalp: when the last n bars sit in a tight box (no wider than maxw %), buy a turn up near the bottom
    edge and sell a turn down near the top edge."""
    k = int(a["n"])
    if not x or len(p) < k + 2:
        return None
    hh, ll = max(x["h"][-k - 1:-1]), min(x["l"][-k - 1:-1])
    if ll <= 0 or hh <= ll or (hh - ll) / ll * 100 > a["maxw"]:
        return None
    band = (hh - ll) * a["edge"]
    if p[-1] <= ll + band and p[-1] > p[-2]:
        return "buy"
    if p[-1] >= hh - band and p[-1] < p[-2]:
        return "sell"


def sig_quick_flip(p, n, a):
    """Quick flip: a run of closes all in one direction adding up to at least thr %. Jumps on the run."""
    k = int(a["run"])
    if len(p) < k + 2 or not p[-1 - k]:
        return None
    d = [p[-i] - p[-i - 1] for i in range(1, k + 1)]
    mv = (p[-1] / p[-1 - k] - 1) * 100
    if all(x > 0 for x in d) and mv >= a["thr"]:
        return "buy"
    if all(x < 0 for x in d) and mv <= -a["thr"]:
        return "sell"


STRATS = {
    "SMA crossover": dict(fn=sig_sma, params={"fast": 5, "slow": 20},
                          bounds={"fast": (2, 60), "slow": (10, 200)}, keep=420),
    "RSI": dict(fn=sig_rsi, params={"period": 14, "lo": 30, "hi": 70},
                bounds={"period": (2, 30), "lo": (5, 40), "hi": (60, 95)}),
    "Momentum": dict(fn=sig_mom, params={"n": 10, "thr": 0.5},
                     bounds={"n": (3, 40), "thr": (0.1, 3.0)}),
    "Bollinger bands": dict(fn=sig_boll, params={"n": 20, "k": 2.0},
                            bounds={"n": (10, 50), "k": (1.0, 3.0)}),
    "Breakout": dict(fn=sig_breakout, params={"n": 20}, bounds={"n": (5, 60)}),
    "MACD": dict(fn=sig_macd, params={"fast": 12, "slow": 26, "signal": 9},
                 bounds={"fast": (3, 20), "slow": (15, 50), "signal": (3, 15)}),
    "Mean reversion": dict(fn=sig_revert, params={"n": 20, "thr": 1.0},
                           bounds={"n": (5, 60), "thr": (0.2, 5.0)}),
    "EMA crossover": dict(fn=sig_ema, params={"fast": 4, "slow": 12, "min_gap": 0.05},
                          bounds={"fast": (2, 20), "slow": (5, 60), "min_gap": (0.0, 0.5)}),
    "Stochastic": dict(fn=sig_stoch, params={"n": 14, "lo": 20, "hi": 80},
                       bounds={"n": (5, 40), "lo": (5, 35), "hi": (65, 95)}),
    "Supertrend": dict(fn=sig_supertrend, params={"n": 10, "m": 3.0}, hlv=True, keep=120,
                       bounds={"n": (5, 30), "m": (1.0, 5.0)}),
    "Ichimoku cross": dict(fn=sig_ichimoku, params={"fast": 9, "slow": 26}, hlv=True, keep=120,
                           bounds={"fast": (4, 20), "slow": (15, 60)}),
    "Rate of change": dict(fn=sig_roc, params={"n": 12, "smooth": 4}, bounds={"n": (3, 50), "smooth": (2, 12)}),
    "MA ribbon": dict(fn=sig_ribbon, params={"fast": 5, "mid": 13, "slow": 34},
                      bounds={"fast": (2, 15), "mid": (8, 40), "slow": (20, 100)}),
    "Trend + dip": dict(fn=sig_trend_dip, params={"trend": 60, "period": 7, "lo": 30, "hi": 70},
                        bounds={"trend": (20, 150), "period": (3, 20), "lo": (15, 40), "hi": (60, 85)}),
    "Volume breakout": dict(fn=sig_volbreak, params={"n": 20, "vmult": 1.8}, hlv=True, keep=80,
                            bounds={"n": (8, 60), "vmult": (1.0, 4.0)}),
    "VWAP snap-back": dict(fn=sig_vwap, params={"n": 30, "thr": 0.8}, hlv=True, keep=120,
                           bounds={"n": (8, 100), "thr": (0.15, 4.0)}),
    "ATR channel": dict(fn=sig_atr, params={"n": 20, "m": 1.5}, hlv=True, keep=200,
                        bounds={"n": (5, 60), "m": (0.5, 4.0)}),
    "Dollar-cost averaging": dict(fn=sig_dca, params={"every": 24},
                                  bounds={"every": (6, 96)}),
    # the scalp breed (scalp=True): only ever hatched as scalpers, see scalp_shape()
    "Micro pullback": dict(fn=sig_micro_pullback, params={"n": 9, "pull": 2}, hlv=True, keep=80, scalp=True,
                           bounds={"n": (4, 21), "pull": (1, 4)}),
    "Volume burst": dict(fn=sig_volume_burst, params={"n": 20, "vmult": 2.5, "thr": 0.08}, hlv=True, keep=80, scalp=True,
                         bounds={"n": (8, 60), "vmult": (1.5, 6.0), "thr": (0.02, 0.6)}),
    "VWAP reclaim": dict(fn=sig_vwap_reclaim, params={"n": 30, "vmin": 1.2}, hlv=True, keep=150, scalp=True,
                         bounds={"n": (10, 120), "vmin": (0.6, 3.0)}),
    "Range scalp": dict(fn=sig_range_scalp, params={"n": 20, "edge": 0.2, "maxw": 0.4}, hlv=True, keep=80, scalp=True,
                        bounds={"n": (8, 60), "edge": (0.05, 0.35), "maxw": (0.08, 1.5)}),
    "Quick flip": dict(fn=sig_quick_flip, params={"run": 3, "thr": 0.06}, keep=20, scalp=True,
                       bounds={"run": (2, 6), "thr": (0.02, 0.5)}),
}


# Famous strategies, some historically popular, some controversial. With Wildcard on they are mixed into the
# eggs alongside random ones, hatch from silver eggs, and have to earn their place like everyone else.
CLASSICS = [
    dict(title="Golden cross", name="SMA crossover", params={"fast": 50, "slow": 200}, tf=1,
         note="The famous 50/200 moving-average cross. Slow, trend-following, popular with long-term investors."),
    dict(title="Turtle breakout", name="Breakout", params={"n": 20}, tf=1, risk={"sl": 2.0},
         note="The 1980s Turtle Traders' rule: buy a 20-bar high, sell a 20-bar low, with a tight stop."),
    dict(title="Wilder's RSI", name="RSI", params={"period": 14, "lo": 30, "hi": 70}, tf=1,
         note="J. Welles Wilder's original 1978 settings: buy oversold under 30, sell overbought over 70."),
    dict(title="Connors RSI-2", name="RSI", params={"period": 2, "lo": 10, "hi": 90}, tf=1,
         note="Larry Connors' very short RSI: buy sharp pullbacks, sell quick bounces."),
    dict(title="Classic MACD", name="MACD", params={"fast": 12, "slow": 26, "signal": 9}, tf=1,
         note="Gerald Appel's standard 12/26/9 MACD signal-line cross."),
    dict(title="Bollinger reversion", name="Bollinger bands", params={"n": 20, "k": 2.0}, tf=1,
         note="John Bollinger's 20-bar, 2-standard-deviation bands, traded as a snap-back."),
    dict(title="Day-trader EMA", name="EMA crossover", params={"fast": 9, "slow": 21, "min_gap": 0.0}, tf=1,
         note="The 9/21 EMA cross loved by day traders."),
    dict(title="Fibonacci ribbon", name="MA ribbon", params={"fast": 8, "mid": 13, "slow": 21}, tf=1,
         note="Averages on Fibonacci numbers lined up as a trend ribbon."),
    dict(title="Supertrend 10/3", name="Supertrend", params={"n": 10, "m": 3.0}, tf=1,
         note="The default Supertrend found on most charting sites."),
    dict(title="Ichimoku 9/26", name="Ichimoku cross", params={"fast": 9, "slow": 26}, tf=1,
         note="Goichi Hosoda's conversion / base line cross."),
    dict(title="Stochastic 14", name="Stochastic", params={"n": 14, "lo": 20, "hi": 80}, tf=1,
         note="George Lane's stochastic with the usual 20 / 80 levels."),
    dict(title="Buy the 5% dip", name="Mean reversion", params={"n": 50, "thr": 5.0}, tf=3,
         note="Buy when the price is 5% under its average, sell 5% over."),
    dict(title="Time-series momentum", name="Momentum", params={"n": 40, "thr": 1.0}, tf=10,
         note="Hold what has been rising, drop what has been falling (a staple of trend funds)."),
    dict(title="Average down", name="Mean reversion", params={"n": 30, "thr": 2.0}, tf=1, traits={"entries": 5, "exit": 1},
         risk={"tp": 4.0}, controversial=True,
         note="CONTROVERSIAL: keeps buying more as the price falls (martingale-style) with no stop, sells only at a "
              "profit target. Wins often, but one long slide can be painful."),
    dict(title="Pump chaser", name="Volume breakout", params={"n": 10, "vmult": 3.0}, tf=1, traits={"maxhold": 20},
         controversial=True, note="CONTROVERSIAL: jumps on sudden volume spikes and gets out fast. Often buys the top."),
    dict(title="Diamond hands", name="Trend + dip", params={"trend": 100, "period": 14, "lo": 35, "hi": 85}, tf=10,
         traits={"exit": 1}, risk={"tp": 15.0}, controversial=True,
         note="CONTROVERSIAL: buys dips in an uptrend and never sells at a loss, only at +15%."),
]


def fix_params(name, p):
    """Keeps related settings sensible (short average below long one, buy level below sell level)."""
    d = STRATS[name]["params"]
    if "fast" in p and "slow" in p and p["fast"] >= p["slow"]:
        p["slow"] = min(p["fast"] + 5, STRATS[name]["bounds"]["slow"][1])
        p["fast"] = min(p["fast"], p["slow"] - 1)
        if p["fast"] < STRATS[name]["bounds"]["fast"][0]:
            p["fast"], p["slow"] = d["fast"], d["slow"]
    if "lo" in p and "hi" in p and p["lo"] >= p["hi"] - 10:
        p["lo"], p["hi"] = d["lo"], d["hi"]
    if "mid" in p and not (p["fast"] < p["mid"] < p["slow"]):
        p["fast"], p["mid"], p["slow"] = d["fast"], d["mid"], d["slow"]
    return p
SCALP_STRATS = [n for n, s in STRATS.items() if s.get("scalp")]  # the scalp breed's own instincts
WILDCARD_STRATS = [n for n in STRATS if n != "Dollar-cost averaging" and n not in SCALP_STRATS]  # DCA never sells


def is_scalp(name):
    """Is this strategy one of the scalp breed's instincts?"""
    return bool(STRATS.get(name, {}).get("scalp"))


# The scalp breed's gene envelope. Whatever mutation or crossbreeding does, a scalper is always pulled back inside
# it: a fast pace, a tight stop AND target on the premium, a hard time limit, near-the-money contracts with little
# time left, and flat before the close (scalpers never hold overnight).
SCALP_TF = (1, 2)
SCALP_RISK = {"sl": (5.0, 60.0), "tp": (6.0, 300.0)}  # from quick 6% nips to 300% home runs on cheap contracts
SCALP_TRAITS = {"maxhold": (2, 60), "flatby": (5, 45), "odte": (1, 7), "otm": (0.25, 4.0), "cool": (1, 10),
                "minhold": (2, 5)}
SCALP_NEEDS = {"maxhold": (3, 20), "flatby": (10, 30), "odte": (1, 5)}  # always carried (random start when missing)


def scalp_shape(rng, tf, risk, traits):
    """(tf, risk, traits) pulled inside the scalp envelope. Idempotent: genes already inside it are left alone."""
    tf = clamp_tf(tf)
    if tf not in SCALP_TF:
        tf = rng.choice((1, 1, 2))
    r = dict(clean_risk(risk))
    for k, (lo, hi) in SCALP_RISK.items():
        # new ones start anywhere on a log scale, so small and big targets are tried about equally often
        val = float(r.get(k) or 0) or math.exp(rng.uniform(math.log(lo), math.log(hi)))
        r[k] = round(min(max(val, lo), hi), 2)
    t = dict(clean_traits(traits))
    t.pop("oexit", None)  # replaced by flatby: a scalper is out the same day
    for k, (lo, hi) in SCALP_NEEDS.items():
        if not t.get(k):
            t[k] = rng.randint(lo, hi)
    for k, (lo, hi) in SCALP_TRAITS.items():
        if k in t:
            t[k] = min(max(t[k], lo), hi)
    if t.get("minhold", 0) >= t["maxhold"]:
        t.pop("minhold")
    return tf, r, clean_traits(t)


# ---- what a scalper really pays to get in and out: the bid/ask gap, learned from live option quotes ----
SPREAD_FIT = {}            # ticker -> [a, b]: a full bid/ask gap of about $a + b x the price, per share
SPREAD_DEFAULT = (0.02, 0.03)
SCALP_SPREAD = [8.0]       # scalpers skip contracts whose bid/ask gap is wider than this % of the price
_SPREAD_LOADED = [False]


def _spreads_path():
    return os.path.join(HOME_DIR, "cache", "spreads.json")


def learn_spreads(c, rows, S=None):
    """Fits the bid/ask gap of one ticker's option chain as $a + b x price (contracts near the money, with real
    quotes) and saves it. Scalpers in Practice then pay that gap instead of a flat guess."""
    pts = [((r["bid"] + r["ask"]) / 2, r["ask"] - r["bid"]) for r in rows
           if r.get("bid", 0) > 0 and r.get("ask", 0) > r["bid"] and (not S or abs(r["K"] / S - 1) < 0.1)]
    if len(pts) < 8:
        return None
    n = len(pts)
    mx, my = sum(x for x, _ in pts) / n, sum(y for _, y in pts) / n
    vx = sum((x - mx) ** 2 for x, _ in pts)
    b = max(0.0, sum((x - mx) * (y - my) for x, y in pts) / vx) if vx > 0 else 0.0
    a = max(0.01, my - b * mx)
    _load_spreads()
    SPREAD_FIT[c] = [round(a, 4), round(min(b, 0.5), 4), time.time()]
    try:
        save_json(_spreads_path(), SPREAD_FIT)
    except Exception:
        pass
    return SPREAD_FIT[c]


def _load_spreads():
    if not _SPREAD_LOADED[0]:
        _SPREAD_LOADED[0] = True
        for k, v in (load_json(_spreads_path(), {}) or {}).items():
            if isinstance(v, list) and len(v) >= 2 and k not in SPREAD_FIT:
                SPREAD_FIT[k] = v


def half_spread(c, prem_share):
    """Half the bid/ask gap as a fraction of a contract's price (what one fill costs), 0..0.5."""
    if prem_share <= 0:
        return 0.5
    _load_spreads()
    a, b = (SPREAD_FIT.get(c) or SPREAD_DEFAULT)[:2]
    return min(0.5, (a + b * prem_share) / 2 / prem_share)


def minutes_to_close(ts):
    """Minutes from ts until 4 pm New York on that day (negative after the close, over 390 before the 9:30 open)."""
    d = datetime.fromtimestamp(ts, timezone.utc)
    ny = d - timedelta(hours=_ny_offset(d))
    return (ny.replace(hour=16, minute=0, second=0, microsecond=0) - ny).total_seconds() / 60


# ---------------- settings ----------------
DEFAULT_SETTINGS = {
    "trade_pct": 5.0, "stop_loss": 50.0, "take_profit": 100.0, "daily_loss": 10.0,
    "bar_minutes": 1, "refresh": 2, "fee_pct": 0.1, "evolve_every": 24, "notify": True,
    "sound": False,              # (old setting, no longer used: CBBF has its own chime now)
    "chime": True,               # play CBBF's own sounds with notifications (not the Windows system sound)
    "chime_volume": 60,          # 0-100
    "sounds_off": [],            # which of CBBF's sounds are switched off: trade, notify, hof, problem
    "notify_trades": False,      # also notify on every trade (off: only important events)
    "max_coin_pct": 25.0, "style": "Balanced", "keep_awake": True,
    "size_mult": {},  # manual-mode trade size per strategy name (1.0 = normal)
    # Wildcard: how winners and shaky strategies are treated
    "winners_trade_more": True,  # winners add to positions and get bigger trades
    "winner_boost": 2.5,         # biggest trade-size multiplier a top winner can earn
    "add_every": 3,              # decisions between add-on buys while a winner is holding
    "slow_every": 6,             # decisions between trades that only shaky strategies want
    "max_bots": 30,              # most strategies competing at once (14 to 200)
    "retire_hours": 12.0,        # replace a strategy that has not been winning for this long (0 = never)
    "fail_drop": 3.0,            # % drop from a strategy's recent peak that stops it at once (0 = off)
    "beat_hold": True,           # a strategy only counts as Winning if it also beats just holding
    "crossbreed": True,          # new strategies can mix the settings of two winners
    "regime_aware": True,        # favour strategies that do well in the current market mood
    # Hall of Fame: long-term winners are saved automatically
    "hof_hours": 6.0,            # hours a strategy must spend Winning (in total) to get in
    "hof_min_trades": 4,         # and at least this many finished (sold) trades
    "hof_load": True,            # bring the best Hall of Fame bots back when Wildcard starts
    "auto_catch": True,          # long-term winners are saved to your Bot Library automatically
    "auto_hof": False,           # ...and also put straight into the Hall of Fame (off: you choose who goes in)
    "animations": "Full",        # Full, Light (slower, lighter) or Off
    "characters": "Themed dragons",  # or "Classic dragons" (coloured by status)
    "egg_colors": "By dragon type",  # or "Purple"
    "auto_resume": True,         # resume the session that was running when the app closed
    "team_locked": True,         # trading with your team: keep exactly those bots (False = they may breed new ones)
    # Orders and costs
    "bot_stops": True,           # Wildcard: the account's safety stop / lock-in-profit follow what the winning bots learned
    "classics": True,            # mix famous strategies (golden cross, turtle, RSI-2...) into the eggs
    "classic_rate": 25,          # % of new eggs that are a famous strategy (when one isn't on the farm yet)
    "layers": True,              # bots can evolve extra rule layers: a confirming strategy, an exit strategy, a sizing rule
    "ctx_tickers": ["SPY", "VIXY", "TLT", "MSFT"],  # market context: watched (never traded); VIXY stands in for the VIX
    "ctx_studies": True,         # bots can evolve studies on the context tickers (VIX up = careful with calls...)
    "htf_studies": True,         # bots can evolve a slower-timeframe study (the bigger trend) that must agree before buying
    "lead_study": True,          # bots can evolve a "market leads" study: SPY's recent move votes on other tickers
    "time_habits": True,         # bots can learn to skip the opening / closing rush (never-rules graded in hindsight)
    "agree_sizing": True,        # the account trades bigger when several different strategies agree, smaller when split
    "learn_losses": True,        # a bot takes on a never-rule itself when that rule would have stopped several of its losses
    "post_review": True,         # after losing trades the farm notes which never-rule would have helped, and tries those more
    "islands": 3,                # separate sub-farms that only swap a champion now and then (1 = one big farm)
    "adapt_exits": True,         # bots can evolve stops and targets that widen in wild markets and tighten in calm ones
    "mut_memory": True,          # the farm remembers which kinds of change make winners and does more of those
    "multicore": True,           # warm up the islands on several processor cores at once
    "shadow_live": True,         # follow your Hall of Fame bots with pretend money in real time (Shadow Live)
    "retest_nightly": False,     # once a day, re-backtest the Hall of Fame on the latest prices; stale ones get a RUSTY badge
    "graduation": True,          # before real money: check each Hall of Fame / team bot has earned it
    "grad_hours": 24.0,          # ...hours it must have spent Winning
    "trade_hours": "",           # account trades only in these hours, like "9-17" or "22-6" (empty = any time; stops always run)
    "weekdays_only": False,      # ...and only Monday to Friday
    "tg_remote": False,          # control CBBF from Telegram: /status /pause /resume /report /kill
    "free_roam": False,          # (retired: Free roam only runs while its switch is ON)
    "free_roam_running": False,  # ...also while the bot runs (uses a little more computer power and network)
    "slow_trades_account": False,  # the slow farm (hourly candles) may also trade your account
    "slow_size": 30,             # bots on the slow farm
    "coin_prefs": True,          # bots learn which coins they're bad at and skip them (re-checked in hindsight)
    "confidence_sizing": True,   # bots buy bigger when many of their studies agree, smaller on a close vote
    "twin_test": True,           # winners are re-run on an older stretch of prices; lucky ones count for less
    "elders": True,              # good bots that leave pass their settings on as a nudge to future eggs
    "seasons": True,             # the farm remembers a champion for each market mood and wakes it when that mood returns
    "bot_allowance": 25.0,       # account: most of the starting money one bot's votes may have tied up (% , 0 = no limit)
    "why_popup": True,           # LIVE: show a small "why did it trade?" note for every real trade
    "weekly_report": True,       # write a weekly report (and send it to Discord / Telegram if set up)
    "bg_mode": True,             # minimized: skip all drawing and check prices less often
    "tray_autotrain": True,      # started in the background (icon by the clock): train on practice prices right away
    "daily_recap": True,         # once a day: how the bots did vs holding (log + icon note)
    "auto_backup": True,         # weekly copy of bots/farms/settings in auto-backups/ (last 4, no keys)
    "vetoes": True,              # bots can evolve never-rules, each graded by what the blocked trade would have done
    "prove_live": True,          # a bot can only be Winning after it also made money on prices it hadn't seen yet
    "risk_adjusted": True,       # rank winners by gain per unit of downside swing, not raw gain
    "luck_check": True,          # a bot's score counts for less when it rests on only a few trades
    "long_holds": True,          # include slow, longer-holding bots from the start
    "scalpers": True,            # the scalp breed: fast in-and-out bots (tight stop + target, time limit, flat by the close)
    "scalp_share": 25,
    "scalp_spread": 8.0,         # scalpers skip contracts whose bid/ask gap is wider than this % of the price           # % of the fast farm kept for scalpers (they can win up to twice that; needs 5-min bars or faster)
    "min_hold_min": 0.0,         # account: minutes to hold before a strategy signal may sell (stops still sell)
    "fee_aware": True,           # don't sell for a profit smaller than the round-trip fees (losses and stops still sell)
    "max_trades_hour": 30,       # brake: most signal trades the account may make in an hour (0 = no limit)
    "trail_stop": 0.0,           # % trailing stop: sell if a coin falls this far from its high since buying (0 = off)
    "_broker": "alpaca",         # (kept in step with Account > broker; sets the per-contract fee)
    "expiry_days": 2,            # sell every account contract this many trading days before it expires
    "pdt_guard": True,           # under $25k: never make a 4th day trade in 5 business days
    "contract_fee": -1.0,        # $ per contract per side; -1 = the broker's own (Alpaca ~$0.04, IBKR ~$0.69)
    "max_spread_pct": 15.0,      # LIVE: skip contracts whose bid/ask gap is wider than this % of the price (0 = off)
    "min_oi": 50,                # LIVE: skip contracts with fewer open contracts than this (0 = off)
    "prem_min": 0.0,             # contract price range the bots may buy, $ per share (0 = no limit)
    "prem_max": 0.0,
    "max_group_pct": 50,         # never more than this % of your money in calls (or puts) on tickers that move together
    "slippage": 2.0,             # % of the premium lost to the bid/ask spread on each option fill (Practice)
    "order_type": "market",      # (options always use limit orders at the bid / ask; kept for old settings files)
    "maker_fee_pct": 0.4,        # fee for limit orders that rest on the book (Practice)
    "limit_wait": 20,            # seconds a limit order may wait for a fill
    "limit_fallback": True,      # if a limit order does not fill in time, use a market order instead
    # Alerts
    "alert_discord": "", "alert_tg_token": "", "alert_tg_chat": "",
    "alert_trades": True, "alert_hof": True, "alert_problems": True,
    # Coins
    "extra_coins": [],           # more tickers added from the ticker browser
    "auto_coins": 0,             # Wildcard: let the bot pick this many coins at start (0 = use the ticked ones)
}
STYLES = {  # risk presets: trade size, stop / target on the premium, daily limit, max in one ticker (all %)
    "Cautious": dict(trade_pct=3.0, stop_loss=35.0, take_profit=60.0, daily_loss=5.0, max_coin_pct=15.0),
    "Balanced": dict(trade_pct=5.0, stop_loss=50.0, take_profit=100.0, daily_loss=10.0, max_coin_pct=25.0),
    "Adventurous": dict(trade_pct=10.0, stop_loss=70.0, take_profit=200.0, daily_loss=20.0, max_coin_pct=40.0),
}


def merge_settings(saved):
    s = dict(DEFAULT_SETTINGS)
    s["params"] = {n: dict(sp["params"]) for n, sp in STRATS.items()}
    for k, v in (saved or {}).items():
        if k == "params":
            for n, pp in (v or {}).items():
                if n in s["params"] and isinstance(pp, dict):
                    s["params"][n].update({pk: pv for pk, pv in pp.items() if pk in s["params"][n]})
        elif k in s:
            s[k] = v
    s["size_mult"] = dict(s.get("size_mult") or {})
    s["extra_coins"] = [c for c in (s.get("extra_coins") or []) if isinstance(c, str) and valid_coin(c)]
    if s["order_type"] not in ("market", "limit"):
        s["order_type"] = "market"
    try:
        s["bar_minutes"] = min(BAR_CHOICES, key=lambda b: abs(b - float(s["bar_minutes"])))
    except (TypeError, ValueError):
        s["bar_minutes"] = 1
    return s


def valid_coin(c):
    """A stock / ETF ticker like SPY, AAPL or BRK.B."""
    return bool(re.fullmatch(r"[A-Z][A-Z.]{0,5}", c or ""))


def cost_model(settings):
    """(fee, slippage) as fractions for simulated trades. Limit orders pay the maker fee and no spread."""
    if settings.get("order_type") == "limit":
        return float(settings.get("maker_fee_pct", 0.4)) / 100, 0.0
    return float(settings.get("fee_pct", 0.6)) / 100, float(settings.get("slippage", 0.0)) / 100


# ---------------- market mood ----------------
def market_mood(p, n=60):
    """-> (mood, efficiency 0..1, move %). Efficiency is how straight the price travelled: 1 = a clean
    one-way move, near 0 = lots of back and forth for little net change."""
    if len(p) < n + 1:
        return "unknown", 0.0, 0.0
    seg = p[-n - 1:]
    path = sum(abs(seg[i] - seg[i - 1]) for i in range(1, len(seg)))
    move = seg[-1] - seg[0]
    er = abs(move) / path if path else 0.0
    pct = move / seg[0] * 100 if seg[0] else 0.0
    if er >= 0.3:
        return ("trending up" if move > 0 else "trending down"), er, pct
    if path / seg[0] * 100 < 0.15 * n ** 0.5 / 4:  # barely moving at all
        return "quiet", er, pct
    return "choppy", er, pct


MOODS = ("trending up", "trending down", "choppy", "quiet")


# ---------------- simulated portfolio ----------------
class Sim:
    def __init__(self, cash, fee, pct, max_coin=None, slip=0.0):
        self.start, self.cash, self.fee, self.pct, self.max_coin = cash, cash, fee, pct, max_coin
        self.slip = slip      # spread + slippage: buys fill a bit higher, sells a bit lower
        self.fees = 0.0       # total fees paid
        self.pos, self.cost = {}, {}
        self.tbars = deque()  # bar indices of recent trades
        self.last = None      # details of the trade just made (read and cleared by the Tournament)

    def buy(self, c, px, n=0, mult=1.0):
        spend = min(self.start * self.pct * mult, self.cash)
        if self.max_coin:
            spend = min(spend, self.start * self.max_coin - self.cost.get(c, 0))
        if spend < 1:
            return False
        fill = px * (1 + self.slip)
        self.cash -= spend
        self.fees += spend * self.fee
        qty = spend * (1 - self.fee) / fill
        self.pos[c] = self.pos.get(c, 0) + qty
        self.cost[c] = self.cost.get(c, 0) + spend
        self.tbars.append(n)
        self.last = dict(side="buy", coin=c, qty=qty, price=fill, usd=spend, pl=None)
        return True

    def sell(self, c, px, n=0):
        q = self.pos.get(c, 0)
        if q <= 0:
            return False
        fill = px * (1 - self.slip)
        proceeds = q * fill * (1 - self.fee)
        self.fees += q * fill * self.fee
        self.cash += proceeds
        self.last = dict(side="sell", coin=c, qty=q, price=fill, usd=proceeds, pl=proceeds - self.cost.get(c, 0))
        self.pos[c], self.cost[c] = 0, 0
        self.tbars.append(n)
        return True

    def act(self, c, sig, px, n=0):
        if sig == "buy":
            self.buy(c, px, n)
        elif sig == "sell":
            self.sell(c, px, n)

    def equity(self, last):
        return self.cash + sum(q * last.get(c, 0) for c, q in self.pos.items())


# ---------------- options: pricing and a pretend options account ----------------
CONTRACT = 100            # shares per option contract
RATE = 0.04               # risk-free rate used for pricing
YEAR = 365.0 * 86400
IV_HINT = {}              # underlying -> implied volatility from the live option chain (used when known)
_VOL_CACHE = {}


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, vol, typ):
    """Black-Scholes price of one share's worth of a European option (T in years)."""
    if S <= 0 or K <= 0:
        return 0.0
    if T <= 0 or vol <= 0:
        return max(0.0, S - K) if typ == "call" else max(0.0, K - S)
    sq = vol * math.sqrt(T)
    d1 = (math.log(S / K) + (RATE + vol * vol / 2) * T) / sq
    d2 = d1 - sq
    if typ == "call":
        return S * _ncdf(d1) - K * math.exp(-RATE * T) * _ncdf(d2)
    return K * math.exp(-RATE * T) * _ncdf(-d2) - S * _ncdf(-d1)


def bs_greeks(S, K, T, vol, typ):
    """(delta, gamma, theta per day, vega per 1 vol point) for one share's worth."""
    if S <= 0 or K <= 0 or T <= 0 or vol <= 0:
        itm = (S > K) if typ == "call" else (S < K)
        return (1.0 if itm else 0.0) * (1 if typ == "call" else -1), 0.0, 0.0, 0.0
    sq = vol * math.sqrt(T)
    d1 = (math.log(S / K) + (RATE + vol * vol / 2) * T) / sq
    d2 = d1 - sq
    pdf = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    delta = _ncdf(d1) if typ == "call" else _ncdf(d1) - 1
    gamma = pdf / (S * sq)
    th = -S * pdf * vol / (2 * math.sqrt(T))
    th += (-RATE * K * math.exp(-RATE * T) * _ncdf(d2)) if typ == "call" else (RATE * K * math.exp(-RATE * T) * _ncdf(-d2))
    return delta, gamma, th / 365.0, S * pdf * math.sqrt(T) / 100


def implied_vol(price, S, K, T, typ):
    """Volatility that makes Black-Scholes match a market price (None if it can't)."""
    if price <= 0 or T <= 0:
        return None
    lo, hi = 0.01, 5.0
    if bs_price(S, K, T, hi, typ) < price:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, mid, typ) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def realized_vol(p, times=None, n=120):
    """Annualised volatility of the last n bars (uses the bar times when known)."""
    L = len(p)
    if L < 10:
        return 0.35
    key = (id(getattr(p, "seq", p)), L, n)
    v = _VOL_CACHE.get(key)
    if v is not None:
        return v
    seg = p[-min(n, L):] if not isinstance(p, View) else [p[i] for i in range(max(0, L - n), L)]
    rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0 and seg[i] > 0]
    if len(rets) < 5:
        return 0.35
    m = sum(rets) / len(rets)
    sd = (sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
    step = 60.0
    if times is not None and len(times) >= 3:
        diffs = [times[-k] - times[-k - 1] for k in range(1, min(20, len(times) - 1)) if times[-k] > times[-k - 1]]
        if diffs:
            step = max(1.0, sorted(diffs)[len(diffs) // 2])
    per_year = 252 * 6.5 * 3600 / step if step < 86400 else 252 * 86400 / step
    v = min(3.0, max(0.08, sd * math.sqrt(per_year)))
    if len(_VOL_CACHE) > 4000:
        _VOL_CACHE.clear()
    _VOL_CACHE[key] = v
    return v


CONTRACT_FEE = [0.04]    # $ per contract per side (commission + regulatory fees), set from the broker


def broker_contract_fee(broker, setting=-1.0):
    """Per-contract fee: the setting if you gave one, else the broker's usual (Alpaca: no commission, about $0.04 of
    regulatory fees; IBKR: about $0.65 commission plus the same fees)."""
    try:
        x = float(setting)
    except (TypeError, ValueError):
        x = -1.0
    if x >= 0:
        return x
    return 0.69 if broker == "ibkr" else 0.04


def ny_date(ts):
    d = datetime.fromtimestamp(ts, timezone.utc)
    return (d - timedelta(hours=_ny_offset(d))).date()


def sessions_left(exp, now=None):
    """Trading days from today until expiry day (expiry day counts, today doesn't): Wednesday for a Friday expiry = 2,
    Thursday = 1, expiry day itself = 0. Weekends are skipped (holidays aren't, so it errs on the early side)."""
    a, b = ny_date(now or time.time()), ny_date(exp)
    n, d = 0, a
    while d < b and n < 400:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


PREM_RANGE = [0.0, 0.0]  # contract price range bots may buy, $ per share; 0 = no limit on that side


def set_prem_range(lo, hi):
    try:
        lo, hi = max(0.0, float(lo or 0)), max(0.0, float(hi or 0))
    except (TypeError, ValueError):
        lo, hi = 0.0, 0.0
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    PREM_RANGE[:] = [lo, hi]


def prem_ok(p):
    """Is a premium ($ per share) inside the chosen contract price range?"""
    lo, hi = PREM_RANGE
    return (not lo or p >= lo) and (not hi or p <= hi)


def prem_range_text():
    lo, hi = PREM_RANGE
    if not lo and not hi:
        return ""
    if lo and hi:
        return f"${lo:,.2f} to ${hi:,.2f} a share (${lo * 100:,.0f} to ${hi * 100:,.0f} a contract)"
    return (f"at least ${lo:,.2f} a share" if lo else f"at most ${hi:,.2f} a share (${hi * 100:,.0f} a contract)")


def strike_step(S):
    return 0.5 if S < 25 else 1.0 if S < 200 else 5.0 if S < 1000 else 10.0


def next_expiry(now, dte):
    """The Friday (4 pm New York, 20:00 UTC) on or after now + dte days, as a timestamp."""
    t = now + dte * 86400
    d = datetime.fromtimestamp(t, timezone.utc)
    ahead = (4 - d.weekday()) % 7
    fri = (d + timedelta(days=ahead)).replace(hour=20, minute=0, second=0, microsecond=0)
    if fri.timestamp() <= now + 3600:
        fri += timedelta(days=7)
    return fri.timestamp()


def occ_symbol(under, exp_ts, typ, K):
    """OCC option symbol, e.g. SPY250117C00450000."""
    d = datetime.fromtimestamp(exp_ts, timezone.utc)
    return f"{under}{d:%y%m%d}{'C' if typ == 'call' else 'P'}{int(round(K * 1000)):08d}"


def contract_text(o):
    d = datetime.fromtimestamp(o["exp"], timezone.utc)
    return f"{o.get('under', '')} {d:%b %d} {o['K']:g} {'call' if o['type'] == 'call' else 'put'}".strip()


class OptionSim(Sim):
    """Pretend options account for one bot. A buy signal buys a call (or closes a put), a sell signal sells the call
    (or buys a put). The bot's genes (traits) choose calls / puts / both, days to expiry, how far out of the money,
    and how many days before expiry to get out. Contracts are priced with Black-Scholes from the stock's recent swings
    (or the live implied volatility), and every fill pays the spread."""

    def __init__(self, cash, fee, pct, max_coin=None, slip=0.0, genes=None):
        super().__init__(cash, fee, pct, max_coin, slip)
        self.slip = max(slip, 0.02)  # half the bid/ask spread on option premiums
        self.genes = genes if genes is not None else {}
        self.opt = {}               # underlying -> {type, K, exp}
        self.now = time.time()
        self.vol_src = {}

    def _vol(self, c, closes=None, times=None):
        iv = IV_HINT.get(c)
        if iv:
            return iv
        return self.vol_src.get(c, 0.35)

    def mark(self, c, S):
        """Value of one contract right now."""
        o = self.opt.get(c)
        if not o or not S:
            return 0.0
        T = max(0.0, o["exp"] - self.now) / YEAR
        return bs_price(S, o["K"], T, self._vol(c), o["type"]) * CONTRACT

    def value_of(self, c, S):
        return self.pos.get(c, 0) * self.mark(c, S)

    def _open(self, c, typ, S, n, mult=1.0):
        g = self.genes or {}
        mode = int(g.get("omode", 3) or 3)
        if (typ == "call" and mode == 2) or (typ == "put" and mode == 1):
            return False
        otm = float(g.get("otm", 0) or 0) / 100
        step = strike_step(S)
        K = round((S * (1 + otm) if typ == "call" else S * (1 - otm)) / step) * step
        exp = next_expiry(self.now, int(g.get("odte", 14) or 14))
        self.opt[c] = dict(type=typ, K=K, exp=exp, under=c)
        prem = self.mark_one(c, S)
        if (PREM_RANGE[0] or PREM_RANGE[1]) and not prem_ok(prem / CONTRACT):
            # outside the price range: walk the strike (further out of the money = cheaper, closer in = dearer)
            cheaper = 1 if typ == "call" else -1
            way = cheaper if (PREM_RANGE[1] and prem / CONTRACT > PREM_RANGE[1]) else -cheaper
            for _ in range(60):
                K = K + way * step
                if K <= 0:
                    break
                self.opt[c]["K"] = K
                prem = self.mark_one(c, S)
                if prem_ok(prem / CONTRACT):
                    break
                if (way == cheaper and PREM_RANGE[0] and prem / CONTRACT < PREM_RANGE[0]) or \
                        (way != cheaper and PREM_RANGE[1] and prem / CONTRACT > PREM_RANGE[1]):
                    break  # stepped right over the range: no contract fits
            if not prem_ok(prem / CONTRACT):
                self.opt.pop(c, None)
                return False
        if prem <= 0.5:
            self.opt.pop(c, None)
            return False
        slip = self.slip
        if g.get("flatby"):  # scalper: the real bid/ask gap for this contract, and only tight ones
            slip = half_spread(c, prem / CONTRACT)
            if 2 * slip * 100 > SCALP_SPREAD[0]:
                self.opt.pop(c, None)
                return False
        fill = prem * (1 + slip)
        spend = min(self.start * self.pct * mult, self.cash)
        qty = int(spend // fill)
        if qty < 1 and fill <= min(self.cash * 0.3, spend * 2.5):
            qty = 1  # one contract is the smallest trade there is
        if qty < 1:
            self.opt.pop(c, None)
            return False
        cost = qty * fill * (1 + self.fee) + qty * CONTRACT_FEE[0]
        if cost > self.cash:
            self.opt.pop(c, None)
            return False
        self.cash -= cost
        self.fees += qty * fill * self.fee + qty * prem * slip + qty * CONTRACT_FEE[0]
        self.pos[c] = qty
        self.cost[c] = cost
        self.tbars.append(n)
        self.last = dict(side="buy", coin=c, qty=qty, price=fill, usd=cost, pl=None, contract=dict(self.opt[c]))
        return True

    def mark_one(self, c, S):
        o = self.opt.get(c)
        if not o:
            return 0.0
        T = max(0.0, o["exp"] - self.now) / YEAR
        return bs_price(S, o["K"], T, self._vol(c), o["type"]) * CONTRACT

    def buy(self, c, px, n=0, mult=1.0):
        o = self.opt.get(c)
        if o and self.pos.get(c, 0) > 0:
            if o["type"] == "put":
                return self.sell(c, px, n)
            return False  # already holding a call: no adding to options
        return self._open(c, "call", px, n, mult)

    def sell(self, c, px, n=0):
        q = self.pos.get(c, 0)
        if q <= 0:
            return False
        o = dict(self.opt.get(c) or {})
        prem = self.mark_one(c, px)
        expired = o and self.now >= o["exp"]
        slip = half_spread(c, prem / CONTRACT) if (self.genes or {}).get("flatby") else self.slip
        fill = prem if expired else prem * (1 - slip)
        proceeds = q * fill * (1 - (0 if expired else self.fee)) - (0 if expired else q * CONTRACT_FEE[0])
        self.fees += 0 if expired else q * prem * slip + q * fill * self.fee + q * CONTRACT_FEE[0]
        self.cash += proceeds
        self.last = dict(side="sell", coin=c, qty=q, price=fill, usd=proceeds, pl=proceeds - self.cost.get(c, 0), contract=o)
        self.pos[c], self.cost[c] = 0, 0
        self.opt.pop(c, None)
        self.tbars.append(n)
        return True

    def act(self, c, sig, px, n=0):
        if sig == "buy":
            self.buy(c, px, n)
        elif sig == "sell":
            if self.pos.get(c, 0) > 0:
                o = self.opt.get(c) or {}
                if o.get("type") == "call":
                    self.sell(c, px, n)
            else:
                self._open(c, "put", px, n)

    def equity(self, last):
        return self.cash + sum(q * self.mark_one(c, last.get(c, 0)) for c, q in self.pos.items() if q > 0)


OPTIONS = True  # this app trades options: every bot gets an options account


def make_sim(cash, fee, pct, max_coin=None, slip=0.0, genes=None):
    return OptionSim(cash, fee, pct, max_coin, slip, genes) if OPTIONS else Sim(cash, fee, pct, max_coin, slip)


def align_ctx(times, ctx_times, ctx_closes):
    """A context ticker's prices lined up with another ticker's bar times (each bar gets the latest known price)."""
    out, j, last = [], 0, None
    for t in times:
        while j < len(ctx_times) and ctx_times[j] <= t:
            last = ctx_closes[j]
            j += 1
        out.append(last if last is not None else (ctx_closes[0] if ctx_closes else 0.0))
    return out


def lead_ticker(closes):
    """The market leader the 'follow the leader' study watches: SPY (or QQQ) when the farm trades it."""
    for t in ("SPY", "QQQ", "BTC"):
        if t in closes:
            return t
    return None


def data_now(extra, coins):
    """Time of the newest bar in this data (bar times travel with the highs/lows/volumes as 't')."""
    for c in coins:
        t = ((extra or {}).get(c) or {}).get("t")
        if t is not None and len(t):
            return t[-1]
    return time.time()


# ---------------- wildcard tournament ----------------
def tournament_opts(settings):
    """Picks the winner/shaky-strategy knobs out of the app settings."""
    fee, slip = cost_model(settings)
    set_prem_range(settings.get("prem_min", 0), settings.get("prem_max", 0))
    CONTRACT_FEE[0] = broker_contract_fee(settings.get("_broker", "alpaca"), settings.get("contract_fee", -1))
    return dict(trade_more=bool(settings.get("winners_trade_more", True)),
                winner_boost=float(settings.get("winner_boost", 2.5)),
                add_every=int(settings.get("add_every", 3)),
                slow_every=int(settings.get("slow_every", 6)),
                fail_drop=float(settings.get("fail_drop", 3.0)),
                beat_hold=bool(settings.get("beat_hold", True)),
                crossbreed=bool(settings.get("crossbreed", True)),
                regime_aware=bool(settings.get("regime_aware", True)),
                slip=slip, fee_aware=bool(settings.get("fee_aware", True)),
                prove_live=bool(settings.get("prove_live", True)), risk_adjusted=bool(settings.get("risk_adjusted", True)), luck_check=bool(settings.get("luck_check", True)),
                classics=bool(settings.get("classics", True)), classic_rate=float(settings.get("classic_rate", 25)) / 100,
                vetoes=bool(settings.get("vetoes", True)), layers=bool(settings.get("layers", True)),
                long_holds=bool(settings.get("long_holds", True)),
                scalp_share=scalp_share(settings),
                coin_prefs=bool(settings.get("coin_prefs", True)), confidence_sizing=bool(settings.get("confidence_sizing", True)),
                twin_test=bool(settings.get("twin_test", True)), elders=bool(settings.get("elders", True)),
                seasons=bool(settings.get("seasons", True)),
                htf_studies=bool(settings.get("htf_studies", True)), lead_study=bool(settings.get("lead_study", True)),
                ctx=[c for c in (settings.get("ctx_tickers") or []) if valid_coin(c)] if settings.get("ctx_studies", True) else [],
                post_review=bool(settings.get("post_review", True)), learn_losses=bool(settings.get("learn_losses", True)),
                time_habits=bool(settings.get("time_habits", True)), agree_sizing=bool(settings.get("agree_sizing", True)), islands=max(1, min(6, int(settings.get("islands", 3) or 1))),
                adapt_exits=bool(settings.get("adapt_exits", True)), mut_memory=bool(settings.get("mut_memory", True)),
                prem=list(PREM_RANGE), cfee=CONTRACT_FEE[0], sspread=_set_scalp_spread(settings))


def scalp_share(settings):
    """Share of the fast farm (0..0.6) kept for the scalp breed. 0 when switched off or when the bars are slower
    than 5 minutes (a scalper deciding once an hour isn't scalping)."""
    try:
        if not settings.get("scalpers", True) or float(settings.get("bar_minutes", 1)) > 5:
            return 0.0
        return min(0.6, max(0.0, float(settings.get("scalp_share", 25) or 0) / 100))
    except (TypeError, ValueError):
        return 0.0


def _set_scalp_spread(settings):
    try:
        SCALP_SPREAD[0] = max(1.0, float(settings.get("scalp_spread", 8.0) or 8.0))
    except (TypeError, ValueError):
        SCALP_SPREAD[0] = 8.0
    return SCALP_SPREAD[0]


def opts_for_bars(opts, gran_seconds):
    """Farm options for a farm running on candles of this size: no scalp breed on candles slower than 5 minutes."""
    return dict(opts, scalp_share=0.0) if float(gran_seconds or 0) > 300 else dict(opts)


RISK_BOUNDS = {"sl": (2.0, 95.0), "tp": (2.0, 500.0)}  # a bot's own stop / target on the PREMIUM it paid, % (0 = none)
FAST_RISK = {"sl": 80.0, "tp": 300.0}   # options move a lot: a 50% stop on a premium is ordinary
SLOW_RISK = {"sl": 90.0, "tp": 500.0}


def clean_risk(r):
    out = {}
    for k, (lo, hi) in RISK_BOUNDS.items():
        try:
            v = float((r or {}).get(k, 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        out[k] = 0.0 if v <= 0 else round(min(max(v, lo), hi), 2)
    return out


def risk_text(r):
    r = r or {}
    parts = ([f"stop {r['sl']:g}%"] if r.get("sl") else []) + ([f"target {r['tp']:g}%"] if r.get("tp") else [])
    return ", ".join(parts)


# Traits: extra habits every bot can evolve on top of its strategy. 0 / empty = off.
TRAITS = {
    "trail":   dict(lo=0.5, hi=12.0, kind=float, text=lambda v: f"trailing stop {v:g}%"),
    "maxhold": dict(lo=3, hi=200, kind=int, text=lambda v: f"sells after {v} decisions"),
    "minhold": dict(lo=2, hi=300, kind=int, text=lambda v: f"holds at least {v} decisions"),
    "cool":    dict(lo=1, hi=30, kind=int, text=lambda v: f"waits {v} decisions after selling"),
    "trend":   dict(lo=20, hi=250, kind=int, text=lambda v: f"buys only above its {v}-bar average"),
    "minvol":  dict(lo=0.02, hi=1.5, kind=float, text=lambda v: f"skips markets moving under {v:g}% a bar"),
    "rsicap":  dict(lo=55, hi=90, kind=int, text=lambda v: f"won't buy if RSI is over {v}"),
    "confirm": dict(lo=2, hi=3, kind=int, text=lambda v: f"waits for {v} signals in a row"),
    "entries": dict(lo=1, hi=5, kind=int, text=lambda v: f"buys at most {v}x per position"),
    "exit":    dict(lo=1, hi=1, kind=int, text=lambda v: "sells only through its stops"),
    "adapt":   dict(lo=1, hi=1, kind=int, text=lambda v: "stops widen in wild markets, tighten in calm ones"),
    "omode":   dict(lo=1, hi=3, kind=int, text=lambda v: {1: "calls only", 2: "puts only", 3: "calls and puts"}.get(int(v), "calls and puts")),
    "odte":    dict(lo=1, hi=60, kind=int, text=lambda v: f"buys contracts about {v} days from expiry"),
    "otm":     dict(lo=0.25, hi=12.0, kind=float, text=lambda v: f"strikes {v:g}% out of the money"),
    "oexit":   dict(lo=1, hi=10, kind=int, text=lambda v: f"gets out {v} day{'s' if v != 1 else ''} before expiry"),
    "flatby":  dict(lo=5, hi=45, kind=int, text=lambda v: f"scalper: flat {v} min before the close, never overnight"),
    "moods":   dict(lo=1, hi=14, kind=int, text=lambda v: "trades only when " + " / ".join(
        m for i, m in enumerate(MOODS) if v & (1 << i))),
}
TRAIT_NAMES = {"trail": "Trailing stop", "maxhold": "Max hold", "minhold": "Min hold", "cool": "Cooldown", "trend": "Trend filter",
               "minvol": "Min volatility", "rsicap": "Overbought guard", "confirm": "Confirmation",
               "entries": "Max entries", "exit": "Stops-only exit", "moods": "Mood gate", "adapt": "Adaptive stops",
               "omode": "Calls / puts (1 calls, 2 puts, 3 both)", "odte": "Days to expiry", "otm": "% out of the money",
               "oexit": "Exit days before expiry", "flatby": "Flat before the close (minutes, scalpers)"}


def clean_traits(t):
    out = {}
    for k, spec in TRAITS.items():
        try:
            v = float((t or {}).get(k, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        if v <= 0:
            continue
        v = min(max(v, spec["lo"]), spec["hi"])
        out[k] = int(round(v)) if spec["kind"] is int else round(v, 2)
    return out


def traits_text(t):
    return ", ".join(TRAITS[k]["text"](v) for k, v in sorted((t or {}).items()) if k in TRAITS)


# ---- "never" rules: things a bot refuses to do. Each one is graded by what the blocked trade would have done. ----
VETOES = {
    "knife":   dict(lo=1.0, hi=15.0, side="buy", name="No falling knives",
                    text=lambda x: f"never buys after a {x:g}% drop in the last 10 decisions"),
    "spike":   dict(lo=0.3, hi=5.0, side="buy", name="No spike buying",
                    text=lambda x: f"never buys right after a {x:g}%+ jump in one bar"),
    "chase":   dict(lo=1.0, hi=10.0, side="buy", name="No chasing",
                    text=lambda x: f"never buys more than {x:g}% above its 20-decision average"),
    "revenge": dict(lo=1, hi=50, side="buy", name="No revenge trades",
                    text=lambda x: f"never re-buys a ticker within {int(x)} decisions of losing on it"),
    "thin":    dict(lo=0.2, hi=1.0, side="buy", name="No thin markets",
                    text=lambda x: f"never buys when volume is under {x:g}x normal"),
    "mktdown": dict(lo=0.3, hi=5.0, side="buy", name="No buying into a sell-off",
                    text=lambda x: f"never buys while the market (SPY) is down {x:g}%+ over 10 decisions"),
    "preev":   dict(lo=2, hi=72, side="open", name="Quiet before big news",
                    text=lambda x: f"never opens a contract in the {x:g} hours before CPI, the jobs report or a Fed decision"),
    "prefed":  dict(lo=2, hi=72, side="open", name="Quiet before the Fed",
                    text=lambda x: f"never opens a contract in the {x:g} hours before a Fed decision"),
    "postev":  dict(lo=0.5, hi=24, side="open", name="Let the news settle",
                    text=lambda x: f"never opens a contract in the {x:g} hours after CPI, the jobs report or a Fed decision"),
    "opening": dict(lo=5, hi=90, side="open", name="Skip the opening rush",
                    text=lambda x: f"never opens a contract in the first {int(x)} minutes after the 9:30 open (New York)"),
    "closing": dict(lo=5, hi=90, side="open", name="Skip the closing rush",
                    text=lambda x: f"never opens a contract in the last {int(x)} minutes before the 4 pm close (New York)"),
    "panic":   dict(lo=0.5, hi=5.0, side="sell", name="No panic selling",
                    text=lambda x: f"never sells on its strategy right after a {x:g}%+ one-bar drop (stops still work)"),
}
MAX_VETOES = 3
EVENT_VETOES = ("preev", "prefed", "postev")  # only grown once the economic calendar is downloaded
TIME_VETOES = ("opening", "closing")  # time-of-day habits (only on bars shorter than a day)


def clean_vetoes(d):
    out = {}
    for k, spec in VETOES.items():
        try:
            x = float((d or {}).get(k, 0) or 0)
        except (TypeError, ValueError):
            x = 0
        if x > 0 and len(out) < MAX_VETOES:
            x = min(max(x, spec["lo"]), spec["hi"])
            out[k] = int(round(x)) if k in ("revenge", "opening", "closing") else round(x, 2)
    return out


def vetoes_text(d, stats=None):
    parts = []
    for k, x in (d or {}).items():
        if k in VETOES:
            t = VETOES[k]["text"](x)
            st = (stats or {}).get(k)
            if st and st[0]:
                t += f" ({'saved' if st[1] >= 0 else 'cost'} {abs(st[1]):.1f}% over {int(st[0])} vetoes)"
            parts.append(t)
    return "; ".join(parts)


def _veto(v, k, x, c, closes, n, extra, coins):
    """True if never-rule k (value x) blocks a trade on coin c right now."""
    p = closes[c]
    L = 10 * v.tf
    if len(p) < L + 2:
        return False
    if k == "knife":
        return (p[-1] / p[-1 - L] - 1) * 100 <= -x
    if k == "spike":
        return abs(p[-1] / p[-2] - 1) * 100 >= x
    if k == "chase":
        seg = tail_series(p, v.tf, 21)
        return len(seg) >= 20 and (seg[-1] / (sum(seg[-20:]) / 20) - 1) * 100 > x
    if k == "revenge":
        return n - v.lost_at.get(c, -10 ** 9) < x * v.tf
    if k == "thin":
        vol = ((extra or {}).get(c) or {}).get("v")
        if not vol or len(vol) < L + 1:
            return False
        base = sum(vol[-L - 1:-1]) / L
        return base > 0 and vol[-1] < x * base
    if k in TIME_VETOES:
        d = datetime.fromtimestamp(_bar_time(extra, c, v.sim), timezone.utc)
        ny = d - timedelta(hours=_ny_offset(d))
        m = ny.hour * 60 + ny.minute - (9 * 60 + 30)  # minutes since the open
        return (0 <= m < x) if k == "opening" else (0 <= 390 - m <= x)
    if k in ("preev", "prefed", "postev"):
        if not events():
            return False
        now = _bar_time(extra, c, v.sim)
        if k == "postev":
            _, t = last_event(now)
            return t is not None and now - t < x * 3600
        _, t = next_event(now, ("fomc",) if k == "prefed" else BIG_EVENTS)
        return t is not None and t - now < x * 3600
    if k == "mktdown":
        ref = "SPY" if "SPY" in coins else ("BTC" if "BTC" in coins else None)
        if ref:
            q = closes[ref]
            return len(q) > L and (q[-1] / q[-1 - L] - 1) * 100 <= -x
        moves = [closes[k2][-1] / closes[k2][-1 - L] - 1 for k2 in coins if len(closes[k2]) > L]
        return bool(moves) and sum(moves) / len(moves) * 100 <= -x
    if k == "panic":
        return (p[-1] / p[-2] - 1) * 100 <= -x
    return False


SCALP_JUDGE = 30   # a scalper is judged on its last this-many finished trades
SCALP_MIN = 8      # ...once it has at least this many


def scalp_record(v):
    """A scalper's (decision, equity) after each of its recent finished trades, when it has enough of them."""
    te = getattr(v, "trade_eq", None)
    return te if te is not None and len(te) > SCALP_MIN else None


def luck_factor(v):
    """0..1: how much to trust a bot's score given how many trades it rests on. 3 trades = mostly luck,
    40 trades = mostly skill. Slow bots trade rarely by design, so they need fewer."""
    te = scalp_record(v)
    n = len(te) - 1 if te else len(v.sim.tbars)
    k = 6 if v.tf < 10 else 2
    return n / (n + k) if n else 0.0


def _grade_vetoes(v, closes, n):
    """Settles blocked trades whose waiting time is up: how much did skipping them save (or cost)?"""
    keep = []
    for k, c, side, px, due in v.veto_wait:
        if n < due or c not in closes:
            keep.append((k, c, side, px, due))
            continue
        move = (closes[c][-1] / px - 1) * 100
        # a skipped buy saved money if the price fell (plus the fees it didn't pay); a skipped sell, if it rose
        saved = (-move + v.rt_cost * 100) if side == "buy" else move
        if k == "coin":  # a skipped coin: if it would have won, its bad record fades
            cp = v.coin_pl.setdefault(c, [0, 0.0])
            cp[1] = cp[1] * 0.9 + max(0.0, -saved)  # bad records also fade slowly, so it re-tries the coin one day
        st = (v.layer_stats if (k in ("plus", "minus", "confirm", "coin", "htf", "lead") or k.startswith("ctx:"))
              else v.veto_stats).setdefault(k, [0.0, 0.0])
        st[0] += 1
        st[1] += saved
    v.veto_wait = keep


# ---- rule layers: several positive studies, several negative studies, several exit studies, and a sizing rule ----
MAX_PLUS, MAX_MINUS, MAX_EXITS = 4, 3, 3
MAX_CTX = 3          # context studies per bot (on tickers it watches but never trades)
CTX_KEY = "__ctx__"  # where the context tickers' prices travel inside the extra data


def ctx_text(e):
    up = "for" if e["sign"] > 0 else "against"
    down = "against" if e["sign"] > 0 else "for"
    if e.get("kind") == "study":
        return f"{e['sym']} {e['name']} buy votes {up} buying, sell votes {down}"
    return f"{e['sym']} up {e['th']:g}%+ over {e['lb']} decisions votes {up} buying, down that much votes {down}"


def _ctx_votes(v, L, extra, n):
    """[(sym, vote)] from the bot's context studies: +1 for buying, -1 against, 0 no opinion (or no data)."""
    out = []
    ctx = (extra or {}).get(CTX_KEY) or {}
    for i, e in enumerate(L.get("ctx", [])):
        q = ctx.get(e["sym"])
        vote = 0
        if q is not None and len(q) > 5:
            if e.get("kind") == "study":
                sig = strat_signal(e["name"], q, n, e["params"], v.tf)
                k = f"ctx{i}"
                if sig:
                    v.conf_last[k] = sig
                st = v.conf_last.get(k)
                vote = (1 if st == "buy" else -1 if st == "sell" else 0) * e["sign"]
            else:
                lb = e["lb"] * v.tf
                if len(q) > lb and q[-1 - lb]:
                    mv = (q[-1] / q[-1 - lb] - 1) * 100
                    vote = (1 if mv >= e["th"] else -1 if mv <= -e["th"] else 0) * e["sign"]
        out.append((e["sym"], vote))
    return out
HTF_MULTS = (3, 4, 6, 8, 12)  # a slower-timeframe study looks at candles this many times longer than the bot's own


def _clean_sub(d):
    if not isinstance(d, dict) or d.get("name") not in STRATS or d.get("name") == "Dollar-cost averaging":
        return None
    spec, p = STRATS[d["name"]], {}
    for k, dv in spec["params"].items():
        lo, hi = spec["bounds"][k]
        try:
            val = min(max(float((d.get("params") or {}).get(k, dv)), lo), hi)
        except (TypeError, ValueError):
            val = dv
        p[k] = int(round(val)) if isinstance(dv, int) else round(val, 2)
    return dict(name=d["name"], params=fix_params(d["name"], p))


def clean_layers(d):
    """Validated rule layers:
      plus  = extra positive studies (the main strategy always counts as one), up to 4
      minus = negative studies: each one whose latest signal is a sell counts against buying, up to 3
      exits = exit studies: the position is sold when any of them signals sell (instead of the main strategy), up to 3
      need  = how many positive studies (main included) must currently be on 'buy', after negatives are subtracted
      size  = {target}: trade size scaled to the market's swing"""
    d = d if isinstance(d, dict) else {}
    out = {}
    plus = list(d.get("plus") or []) + ([d["confirm"]] if isinstance(d.get("confirm"), dict) else [])
    exits = list(d.get("exits") or []) + ([d["exit"]] if isinstance(d.get("exit"), dict) else [])
    for key, items, cap in (("plus", plus, MAX_PLUS), ("minus", d.get("minus") or [], MAX_MINUS), ("exits", exits, MAX_EXITS)):
        subs = [x for x in (_clean_sub(i) for i in items if isinstance(i, dict)) if x][:cap]
        if subs:
            out[key] = subs
    if out.get("plus") or out.get("minus"):
        try:
            need = int(d.get("need", 1 + (len(out.get("plus", [])) + 1) // 2 if "need" in d or d.get("plus") else 1))
        except (TypeError, ValueError):
            need = 1
        out["need"] = min(max(need, 1), 1 + len(out.get("plus", [])))
    h = d.get("htf")
    if isinstance(h, dict):
        sub = _clean_sub(h)
        if sub:
            try:
                sub["mult"] = int(min(max(int(h.get("mult", 6)), HTF_MULTS[0]), HTF_MULTS[-1]))
            except (TypeError, ValueError):
                sub["mult"] = 6
            out["htf"] = sub
    cx = []
    for e in (d.get("ctx") or [])[:MAX_CTX]:
        if not isinstance(e, dict) or not valid_coin(e.get("sym", "")):
            continue
        sign = -1 if int(e.get("sign", 1) or 1) < 0 else 1
        if e.get("kind") == "study":
            sub = _clean_sub(e)
            if sub:
                cx.append(dict(sub, sym=e["sym"], kind="study", sign=sign))
        else:
            try:
                cx.append(dict(sym=e["sym"], kind="move", sign=sign, lb=int(min(max(int(e.get("lb", 10)), 2), 60)),
                               th=round(min(max(float(e.get("th", 1.0)), 0.1), 10.0), 2)))
            except (TypeError, ValueError):
                pass
    if cx:
        out["ctx"] = cx
    ld = d.get("lead")
    if isinstance(ld, dict):
        try:
            out["lead"] = dict(lb=int(min(max(int(ld.get("lb", 10)), 3), 40)),
                               th=round(min(max(float(ld.get("th", 0.8)), 0.2), 4.0), 2))
        except (TypeError, ValueError):
            pass
    sz = d.get("size")
    if isinstance(sz, dict):
        try:
            out["size"] = dict(target=round(min(max(float(sz.get("target", 0.5)), 0.1), 3.0), 2))
        except (TypeError, ValueError):
            pass
    return out


def _sub_txt(s):
    return f"{s['name']} ({'/'.join(f'{x:g}' for x in s['params'].values())})"


def _stat_txt(st, what):
    if st and st[0]:
        return f" [{'saved' if st[1] >= 0 else 'cost'} {abs(st[1]):.1f}% over {int(st[0])} {what}]"
    return ""


def layers_text(L, stats=None):
    stats = stats or {}
    parts = []
    if L.get("plus") or L.get("minus"):
        n_pos = 1 + len(L.get("plus", []))
        t = f"buys when at least {L.get('need', 1)} of {n_pos} positive studies say buy"
        if L.get("plus"):
            t += " (main strategy + " + ", ".join(_sub_txt(s) for s in L["plus"]) + ")"
        if L.get("minus"):
            t += "; each of these saying sell counts against it: " + ", ".join(_sub_txt(s) for s in L["minus"])
        t += _stat_txt(stats.get("plus"), "buys held back by too little agreement")
        t += _stat_txt(stats.get("minus"), "buys blocked by negative studies")
        parts.append(t)
    if L.get("htf"):
        parts.append(f"only buys when the bigger trend agrees: {_sub_txt(L['htf'])} on {L['htf']['mult']}x longer candles"
                     + _stat_txt(stats.get("htf"), "buys blocked by the bigger trend"))
    if L.get("ctx"):
        parts.append("watches the market: " + "; ".join(ctx_text(e) + _stat_txt(stats.get(f"ctx:{e['sym']}"), "trades it held back")
                                                        for e in L["ctx"]))
    if L.get("lead"):
        parts.append(f"The market leads: SPY up {L['lead']['th']:g}%+ over {L['lead']['lb']} decisions votes for buying other "
                     f"tickers, down that much votes against" + _stat_txt(stats.get("lead"), "buys blocked by the market"))
    if L.get("exits"):
        parts.append("sells when any of these says sell: " + ", ".join(_sub_txt(s) for s in L["exits"]))
    if L.get("size"):
        parts.append(f"sizes trades to the market's swing (aims for {L['size']['target']:g}% moves per decision)")
    return "; ".join(parts)


def rule_stack(v_or_entry):
    """The bot's rules as five layers, in plain English (for cards and exports)."""
    g = (lambda k, d=None: getattr(v_or_entry, k, d)) if not isinstance(v_or_entry, dict) else (lambda k, d=None: v_or_entry.get(k, d))
    tr, L, ls = g("traits", {}) or {}, g("layers", {}) or {}, g("layer_stats", {}) or {}
    market = [traits_text({k: tr[k]}) for k in ("moods", "minvol", "trend") if k in tr]
    if L.get("htf"):
        market.append(f"bigger trend must agree ({_sub_txt(L['htf'])} on {L['htf']['mult']}x candles)"
                      + _stat_txt(ls.get("htf"), "blocked buys"))
    if L.get("ctx"):
        market.append("watches " + "; ".join(ctx_text(e) for e in L["ctx"]))
    if L.get("lead"):
        market.append(f"The market leads (SPY {L['lead']['th']:g}% over {L['lead']['lb']} decisions)")
    pos = [f"{g('name')} (main)"] + [_sub_txt(s) for s in L.get("plus", [])]
    entry = [f"positive studies: {', '.join(pos)}" + (f"; needs {L.get('need', 1)} of {len(pos)} saying buy" if len(pos) > 1 or L.get("minus") else "")
             + _stat_txt(ls.get("plus"), "held-back buys")]
    entry += [traits_text({k: tr[k]}) for k in ("confirm", "rsicap", "cool", "entries") if k in tr]
    neg = ([f"negative studies: {', '.join(_sub_txt(s) for s in L['minus'])} (each saying sell counts against buying)"
            + _stat_txt(ls.get("minus"), "blocked buys")] if L.get("minus") else [])
    nev = vetoes_text(g("vetoes", {}), g("veto_stats", {}))
    sizing = [layers_text({"size": L["size"]})] if L.get("size") else ["flat size"]
    exits = [x for x in (risk_text(g("risk", {})),) if x] + [traits_text({k: tr[k]}) for k in ("trail", "maxhold", "minhold", "exit", "adapt") if k in tr] + \
        ([f"exit studies: {', '.join(_sub_txt(s) for s in L['exits'])} (any saying sell)"] if L.get("exits") else [f"{g('name')} sell signals"])
    return [("1. Market filter", ", ".join(market) or "trades in any market"),
            ("2. Positive studies", "; ".join(entry)),
            ("3. Negative studies", "; ".join(neg + ([f"never-rules: {nev}"] if nev else [])) or "none"),
            ("4. Sizing", "; ".join(sizing)),
            ("5. Exits", "; ".join(exits))]


def _study_states(v, L, key, closes, c, n, xc):
    """Updates and returns each study's latest signal ('buy' / 'sell' / None) for this coin. Studies are judged by
    their most recent signal, so a crossover from a few decisions ago still counts as that study's opinion."""
    out = []
    for i, s in enumerate(L.get(key, [])):
        sig = strat_signal(s["name"], closes[c], n, s["params"], v.tf, xc)
        k = f"{key}{i}:{c}"
        if sig:
            v.conf_last[k] = sig
        out.append((sig, v.conf_last.get(k)))
    return out


def bot_step(v, closes, n, coins, extra=None):
    """One decision of one bot on every coin: its own exits first (stop-loss, take-profit, trailing stop,
    max hold), then its strategy signal filtered by its traits. Returns the trades made [(coin, trade)]."""
    last = {c: closes[c][-1] for c in coins}
    tr, made = v.traits, []
    opt = isinstance(v.sim, OptionSim)
    if opt:
        v.sim.now = data_now(extra, coins)
        v.sim.genes = tr
        for c in coins:  # each coin's recent swing (computed once per bar and shared by every bot)
            v.sim.vol_src[c] = realized_vol(closes[c], ((extra or {}).get(c) or {}).get("t"))
    if v.veto_wait:
        _grade_vetoes(v, closes, n)
    for c in coins:
        sim = v.sim
        sim.last = None
        q = sim.pos.get(c, 0)
        if q > 0:
            mk = sim.value_of(c, last[c]) / q if opt else last[c]  # options: judged on the contract's own value
            v.hi[c] = max(v.hi.get(c, mk), mk)
            r = (mk / (sim.cost[c] / q) - 1) * 100
            why = None
            if opt:
                o = sim.opt.get(c) or {}
                if o and sim.now >= o["exp"] - int(tr.get("oexit", 1) or 1) * 86400:
                    why = "expiry"
                elif tr.get("flatby") and minutes_to_close(sim.now) <= tr["flatby"]:
                    why = "flat"  # scalpers never hold into the close
            k_ = 1.0
            if tr.get("adapt") and n % v.tf == 0:  # adaptive stops: scaled by today's swing vs this bot's usual swing
                ser = tail_series(closes[c], v.tf, 21)
                if len(ser) > 5:
                    sw = sum(abs(ser[i] / ser[i - 1] - 1) for i in range(1, len(ser))) / (len(ser) - 1)
                    ref = v.swing_ref.get(c) or sw
                    v.swing_ref[c] = ref * 0.97 + sw * 0.03
                    v.adapt_k[c] = min(2.0, max(0.5, sw / ref)) if ref > 0 else 1.0
            if tr.get("adapt"):
                k_ = v.adapt_k.get(c, 1.0)
            if why is not None:
                pass
            elif v.risk["sl"] and r <= -v.risk["sl"] * k_:
                why = "stop"
            elif v.risk["tp"] and r >= v.risk["tp"] * k_:
                why = "target"
            elif why is None and tr.get("trail") and mk <= v.hi[c] * (1 - tr["trail"] * k_ / 100):
                why = "trail"
            elif tr.get("maxhold") and n - v.since.get(c, n) >= tr["maxhold"] * v.tf:
                why = "time"
            if why:
                sim.sell(c, last[c], n)
                v.sig[c] = "sell"
                v.why[c] = {"expiry": "its contract was close to expiry",
                            "stop": f"its own safety stop ({v.risk['sl']:g}%)", "target": f"its own profit target ({v.risk['tp']:g}%)",
                            "trail": f"its trailing stop ({tr.get('trail', 0):g}%)", "time": "it held as long as it allows",
                            "flat": f"scalpers are flat {tr.get('flatby', 0)} min before the close"}[why]
        if sim.last is None:
            if n % v.tf:  # between this bot's own decisions: no signal, no trade
                v.sig[c] = None
                continue
            s = strat_signal(v.name, closes[c], n, v.params, v.tf, (extra or {}).get(c))
            reason = f"{v.name} said {s}" if s else ""
            conf = 1.0
            L = v.layers
            if L:
                xc = (extra or {}).get(c)
                if L.get("exits"):  # exit studies: any of them saying sell closes the position (not the main strategy)
                    if s == "sell":
                        s = None
                    if any(fresh == "sell" for fresh, _ in _study_states(v, L, "exits", closes, c, n, xc)) and sim.pos.get(c, 0) > 0:
                        s = "sell"
                        reason = "an exit study said sell"
                lead_v = 0
                ldr = lead_ticker(closes)
                if L.get("lead") and ldr and c != ldr:
                    q_ = closes[ldr]
                    lb = L["lead"]["lb"] * v.tf
                    if len(q_) > lb:
                        mv = (q_[-1] / q_[-1 - lb] - 1) * 100
                        lead_v = 1 if mv >= L["lead"]["th"] else -1 if mv <= -L["lead"]["th"] else 0
                ctx_v = _ctx_votes(v, L, extra, n) if L.get("ctx") else []
                cpos = sum(1 for _, x in ctx_v if x > 0)
                cneg = sum(1 for _, x in ctx_v if x < 0)
                if opt and s == "sell" and sim.pos.get(c, 0) <= 0 and cpos > cneg:  # the market says up: no new put
                    sym_ = next(sy for sy, x in ctx_v if x > 0)
                    if not any(w[0] == f"ctx:{sym_}" and w[1] == c for w in v.veto_wait):
                        v.veto_wait.append((f"ctx:{sym_}", c, "sell", last[c], n + 10 * v.tf))
                    s = None
                if L.get("plus") or L.get("minus") or L.get("lead") or L.get("ctx"):
                    if s:
                        v.conf_last[f"main:{c}"] = s
                    plus = _study_states(v, L, "plus", closes, c, n, xc)
                    minus = _study_states(v, L, "minus", closes, c, n, xc)
                    trigger = s == "buy" or any(fresh == "buy" for fresh, _ in plus)
                    if trigger and sim.pos.get(c, 0) <= 0 or s == "buy":
                        votes = (v.conf_last.get(f"main:{c}") == "buy") + sum(1 for _, st_ in plus if st_ == "buy") + (lead_v > 0) + cpos
                        against = sum(1 for _, st_ in minus if st_ == "sell") + (lead_v < 0) + cneg
                        if votes - against >= L.get("need", 1):
                            if s != "sell":
                                s = "buy"
                                reason = (f"{votes} of its {1 + len(L.get('plus', []))} buy studies agreed"
                                          + (f", {against} said no" if against else "") + f" (needs {L.get('need', 1)})")
                                if v.conf_size:  # confidence: a clear vote buys bigger, a close one smaller
                                    margin = votes - against - L.get("need", 1)
                                    conf = min(1.6, 0.8 + 0.25 * margin) if (L.get("plus") or L.get("minus")) else 1.0
                        else:
                            why = ("lead" if lead_v < 0 and votes - against + 1 >= L.get("need", 1) else
                                   f"ctx:{next(sy for sy, x in ctx_v if x < 0)}" if cneg and votes - against + cneg >= L.get("need", 1) else
                                   "minus" if votes >= L.get("need", 1) else "plus")
                            if not any(w[0] == why and w[1] == c for w in v.veto_wait):
                                v.veto_wait.append((why, c, "buy", last[c], n + 10 * v.tf))
                            if s == "buy":
                                s = None
            if s == "buy" and L.get("htf") and sim.pos.get(c, 0) <= 0:  # the bigger trend must not be saying sell
                h_ = L["htf"]
                hs = strat_signal(h_["name"], closes[c], n, h_["params"], v.tf * h_["mult"], (extra or {}).get(c))
                if hs:
                    v.conf_last[f"htf:{c}"] = hs
                if v.conf_last.get(f"htf:{c}") == "sell":
                    if not any(w[0] == "htf" and w[1] == c for w in v.veto_wait):
                        v.veto_wait.append(("htf", c, "buy", last[c], n + 10 * v.tf))
                    s = None
            if tr.get("confirm"):
                v.run_sig[c] = (s, v.run_sig.get(c, (None, 0))[1] + 1) if s and s == v.run_sig.get(c, (None, 0))[0] else (s, 1 if s else 0)
                if s and v.run_sig[c][1] < tr["confirm"]:
                    s = None
            if s == "buy":
                ser = None
                if tr.get("cool") and n - v.sold_at.get(c, -10 ** 9) < tr["cool"] * v.tf:
                    s = None
                elif tr.get("entries") and v.entries.get(c, 0) >= tr["entries"]:
                    s = None
                else:
                    if tr.get("trend") or tr.get("minvol") or tr.get("rsicap"):
                        ser = tail_series(closes[c], v.tf)
                    if tr.get("trend") and (len(ser) < tr["trend"] or ser[-1] <= _avg(ser, tr["trend"])):
                        s = None
                    elif tr.get("minvol") and (len(ser) < 21 or sum(abs(ser[i] / ser[i - 1] - 1) for i in range(-20, 0)) / 20 * 100 < tr["minvol"]):
                        s = None
                    elif tr.get("rsicap") and len(ser) > 15 and _rsi(ser, 14) > tr["rsicap"]:
                        s = None
                    elif tr.get("moods") and not (tr["moods"] & (1 << MOODS.index(m)) if (m := market_mood(closes[c])[0]) in MOODS else False):
                        s = None
            elif s == "sell" and tr.get("exit") and (v.risk["sl"] or v.risk["tp"] or tr.get("trail") or tr.get("maxhold")):
                s = None  # this bot only leaves through its own exits
            elif s == "sell" and tr.get("minhold") and n - v.since.get(c, n) < tr["minhold"] * v.tf:
                s = None  # this bot holds for a while before its strategy may sell (its stops still work)
            elif s == "sell" and v.fee_guard and sim.pos.get(c, 0) > 0 and not opt:
                gain = last[c] / (sim.cost[c] / sim.pos[c]) - 1
                if 0 <= gain < v.fee_guard:
                    s = None  # fee-aware: a profit this small would be eaten by the fees, so keep holding
            if opt and s == "sell" and sim.pos.get(c, 0) <= 0 and int(tr.get("omode", 3) or 3) == 1:
                s = None  # calls-only bot with nothing to close
            if s and opt and tr.get("flatby") and sim.pos.get(c, 0) <= 0 \
                    and not (tr["flatby"] < minutes_to_close(sim.now) <= 390):
                s = None  # scalper: only opens during the trading day, and not in its last minutes
            if s and v.vetoes and (s == "buy" or sim.pos.get(c, 0) > 0 or opt):
                opening = sim.pos.get(c, 0) <= 0
                for k, x in v.vetoes.items():
                    side = VETOES[k]["side"]
                    if ((side == s or (side == "open" and opening)) and not (side == "sell" and opening)
                            and _veto(v, k, x, c, closes, n, extra, coins)):
                        if not any(w[0] == k and w[1] == c for w in v.veto_wait):  # one open what-if per rule and coin
                            v.veto_wait.append((k, c, s, last[c], n + 10 * v.tf))
                        s = None
                        break
            if s == "buy" and v.picky and sim.pos.get(c, 0) <= 0:
                cp = v.coin_pl.get(c)
                if cp and cp[0] >= 3 and cp[1] < -1.5:  # it keeps losing on this coin: skip it (graded in hindsight)
                    if not any(w[0] == "coin" and w[1] == c for w in v.veto_wait):
                        v.veto_wait.append(("coin", c, "buy", last[c], n + 10 * v.tf))
                    s = None
            v.sig[c] = s
            if s:
                v.why[c] = reason or f"{v.name} said {s}"
            if s == "buy" and (v.layers.get("size") or conf != 1.0):
                mult = conf
                if v.layers.get("size"):  # sizing layer: smaller in wild markets, bigger in calm ones
                    ser = tail_series(closes[c], v.tf, 22)
                    swing = sum(abs(ser[i] / ser[i - 1] - 1) for i in range(1, len(ser))) / max(1, len(ser) - 1) * 100
                    mult *= min(1.5, max(0.5, v.layers["size"]["target"] / swing)) if swing > 0 else 1.0
                sim.buy(c, last[c], n, mult)
            else:
                sim.act(c, s, last[c], n)
        t = sim.last
        if t:
            if t["side"] == "buy":
                if v.review and c not in v.entry_flags:  # which never-rules WOULD have blocked this buy (for the review)
                    v.entry_flags[c] = [k for k, spec in VETOES.items() if spec["side"] in ("buy", "open") and k not in v.vetoes
                                        and _veto(v, k, (spec["lo"] + spec["hi"]) / 2, c, closes, n, extra, coins)]
                v.entries[c] = v.entries.get(c, 0) + 1
                v.since.setdefault(c, n)
                v.hi[c] = max(v.hi.get(c, last[c]), last[c])
            else:
                v.entries.pop(c, None)
                v.since.pop(c, None)
                v.hi.pop(c, None)
                v.sold_at[c] = n
                if t.get("pl") is not None and t["pl"] < 0:
                    v.lost_at[c] = n
                if t.get("pl") is not None:  # per-coin record (recent results count most)
                    paid = t["usd"] - t["pl"]
                    cp = v.coin_pl.setdefault(c, [0, 0.0])
                    cp[0] = min(cp[0] + 1, 20)
                    cp[1] = cp[1] * 0.85 + (t["pl"] / paid * 100 if paid > 0 else 0.0)
            if t["side"] == "sell":
                t["flags"] = v.entry_flags.pop(c, [])
            t["why"] = v.why.get(c, "")
            made.append((c, t))
    return made


class Variant:
    def __init__(self, name, params, sim, maxlen, tf=1, risk=None, traits=None, vetoes=None, layers=None):
        self.name, self.params, self.sim = name, params, sim
        self.risk = clean_risk(risk)
        self.traits = clean_traits(traits)
        self.fee_guard = 0.0  # round-trip cost (fraction) when fee-aware: profits smaller than this aren't taken
        self.rt_cost = 0.0    # round-trip cost (fraction) of a trade, used to grade its never-rules
        self.vetoes = clean_vetoes(vetoes)
        self.veto_stats = {}  # rule -> [times it blocked a trade, total % saved (negative = cost)]
        self.veto_wait = []   # blocked trades waiting to be graded: (rule, coin, side, price, decision due)
        self.lost_at = {}
        self.layers = clean_layers(layers)
        self.layer_stats = {}  # "confirm" -> [buys it blocked, total % saved]
        self.conf_last = {}
        self.coin_pl = {}     # coin -> [closed trades (capped), recent % result]: the bot learns its bad coins
        self.picky = True     # skip coins it keeps losing on
        self.conf_size = True # size buys by how strongly its studies agree
        self.why = {}         # coin -> plain-English reason for its latest signal
        self.twin = None      # twin test: its edge over holding on an older stretch it was never scored on
        self.island = 0       # which sub-farm it lives on
        self.review = True    # note which never-rules would have stopped its losing buys (post-trade review)
        self.entry_flags = {} # coin -> never-rules that would have blocked the open position's first buy
        self.own_review = {}  # its own losses: never-rule -> [its losing buys it would have blocked, winning buys]
        self.swing_ref, self.adapt_k = {}, {}  # adaptive stops: usual swing per coin, current stop scale
        self.mut_kinds = []   # what changed from its parent (mutation memory)
        self.credited = False # counted as a winner in the mutation memory
        self.backtests = []   # summaries of backtests saved to its memory
        self.power = 0.0      # 0..10: grows only with real money made on fresh prices while beating holding
        self.live_high = None
        self.hi, self.since, self.entries, self.sold_at, self.run_sig = {}, {}, {}, {}, {}
        self.uid, self.parents, self.gen = 0, [], 0
        self.tf = clamp_tf(tf)  # decides once every tf bars, on tf-bar candles
        self.eq = deque(maxlen=maxlen)
        self.sig = {}
        self.strikes = 0
        self.size_mult = 1.0  # you can raise or lower this per strategy
        # lifetime track record (since this bot was created)
        self.born_px = None
        self.age = self.ntrades = self.wins = self.losses = 0
        self.win_steps = self.streak = 0
        self.peak, self.maxdd = 0.0, 0.0
        self.mood_gain = {}   # mood -> summed equity change (fraction) while that mood ruled
        self.mood_n = {}
        self.inducted = False
        self.origin = ""
        self.royal = False       # descends from a bot you saved (Library / Hall of Fame / team): hatches from a royal egg
        self.classic = ""        # name of the famous strategy it is (silver egg), or "" 
        self.live_n = 0          # decisions made on prices that came in after the bot was created
        self.live_eq0 = None     # its equity when it started trading live (after any replay)
        self.log = deque(maxlen=300)  # (decision number, coin, side, price) of this bot's own trades, for charts
        self.trade_eq = deque(maxlen=SCALP_JUDGE + 1)  # scalpers: (decision, equity) after each finished trade

    @property
    def label(self):
        rt = ", ".join(x for x in (risk_text(self.risk), traits_text(self.traits), vetoes_text(self.vetoes),
                                   layers_text(self.layers)) if x)
        return (f"{self.name} ({', '.join(f'{k}={v}' for k, v in self.params.items())})"
                + (f" on {self.tf}-bar candles" if self.tf > 1 else "") + (f" [{rt}]" if rt else ""))

    def key(self):
        """Identity of its genes (cached: genes never change after birth; restore() clears the cache)."""
        k = self.__dict__.get("_key")
        if k is None:
            k = self._key = (self.name, self.tf, tuple(sorted((k_, round(float(v), 4)) for k_, v in self.params.items())),
                             tuple(sorted(self.risk.items())), tuple(sorted(self.traits.items())),
                             tuple(sorted(self.vetoes.items())), json.dumps(self.layers, sort_keys=True))
        return k


def bot_key(d):
    return (d["name"], clamp_tf(d.get("tf", 1)),
            tuple(sorted((k, round(float(v), 4)) for k, v in d["params"].items())),
            tuple(sorted(clean_risk(d.get("risk")).items())),
            tuple(sorted(clean_traits(d.get("traits")).items())),
            tuple(sorted(clean_vetoes(d.get("vetoes")).items())),
            json.dumps(clean_layers(d.get("layers")), sort_keys=True))


class Tournament:
    """Runs many strategy variants as shadow portfolios on the same prices.

    Each variant is rated on recent return, how that compares to just holding the same coins,
    consistency (share of recent sub-periods that were profitable) and how far it has dropped
    from its recent peak.

      active   profitable, consistent and (with beat_hold) ahead of holding. The account follows it
               with bigger trades (up to winner_boost x for the strongest) and keeps adding while it holds.
      slowed   profitable but inconsistent, or not beating holding. Followed only with small trades
               and a cooldown between them.
      standby  qualifies as a winner but there is no room for it among the top few.
      benched  losing, not consistent at all, or dropped sharply. Zero trades. Variants that
               stay benched are retired and replaced by tweaked copies of the winners."""

    def __init__(self, coins, start_cash, fee, pct, evolve_every=24, window=100,
                 min_trades=2, max_active=5, cap=14, params=None, rng=None, retire_after=3, opts=None,
                 retire_steps=0, risk_caps=None):
        self.coins, self.start_cash, self.fee, self.pct = list(coins), start_cash, fee, pct
        self.risk_caps = dict(risk_caps or (opts or {}).get("risk_caps") or FAST_RISK)
        self.ctx_syms = [c for c in ((opts or {}).get("ctx") or []) if c not in coins]
        window = int((opts or {}).get("window", window))  # the slow farm judges over a different window
        self.evolve_every, self.W, self.min_trades = max(1, evolve_every), window, min_trades
        self.max_active, self.cap, self.retire_after = max_active, cap, retire_after
        self.family_cap = max(5, -(-self.cap // 4))
        self.retire_steps = max(0, int(retire_steps))  # decisions a bot may go without winning before it is replaced
        self.o = dict(trade_more=True, winner_boost=2.5, add_every=3, slow_every=6, fail_drop=3.0,
                      beat_hold=True, crossbreed=True, regime_aware=True, slip=0.0, fee_aware=True,
                      prove_live=True, risk_adjusted=True, long_holds=True, classics=True, classic_rate=0.25, vetoes=True,
                      layers=True)
        self.replaying = False
        self.o.update(opts or {})
        if self.o.get("prem"):  # worker processes get the contract price range this way
            set_prem_range(*self.o["prem"])
        if self.o.get("cfee") is not None:
            CONTRACT_FEE[0] = float(self.o["cfee"])
        if self.o.get("sspread"):  # worker processes get the scalpers' spread limit this way
            SCALP_SPREAD[0] = float(self.o["sspread"])
        self.slowed, self.cool, self.add_cool, self.kind = [], {}, {}, {}
        self.agree = {}  # coin -> (different strategies agreeing, size factor, how split the farm was)
        self.rng = rng or random.Random()
        self.n = 0
        self.events = []
        self.on_trade = None  # optional hook: fn(bot, ticker, trade, bar time), e.g. Free roam's live trade feed
        self.recording = False  # the app switches this on once live; history replays are never recorded
        self.shadow = []        # every bot's own pretend trades since the last pop_shadow()
        self.hold_ret = None    # what just holding the coins returned over the scoring window
        self.mood, self.moods = "unknown", {}
        self.last_px = {}
        self.xfull = None       # highs/lows/volumes lined up with the closes of the current step
        self.serial = 0
        self.lineage = {}       # uid -> family-tree record (kept after a bot is removed)
        self.elders = []        # genes of good bots that left the farm: they nudge future eggs (newest last)
        self.champions = {}     # mood -> genes and record of the best bot seen in that mood (seasons)
        self.season = None      # the market mood of the current season
        self.seasons_log = []   # (decision, mood) whenever the season changed
        self.review = {}        # never-rule -> [losing buys it would have blocked, winning buys it would have blocked]
        self.mut_stats = {}     # kind of change -> [children born with it, children that went on to win]
        self.births, self.deaths = deque(maxlen=3000), deque(maxlen=3000)  # decision numbers (farm pulse)
        self.evolves = 0
        self.spawn_i = 0
        self.vars = []
        self.info, self.active = {}, []
        if self.o.get("classics", True):  # a few famous strategies join the starters
            for cl in self.rng.sample(CLASSICS, min(4, len(CLASSICS))):
                v = self._new(cl["name"], dict(cl["params"]), cl.get("tf", 1), cl.get("risk"), cl.get("traits"))
                v.classic = cl["title"]
                self.vars.append(v)
        for name in WILDCARD_STRATS:
            p = dict((params or {}).get(name) or STRATS[name]["params"])
            self.vars.append(self._new(name, p))
        for name in WILDCARD_STRATS:  # a slower-paced copy of each, so different speeds compete from the start
            p = dict((params or {}).get(name) or STRATS[name]["params"])
            self.vars.append(self._new(name, p, tf=10 if self.o.get("long_holds", True) else 3))
        while len(self.vars) < min(self.cap, 24):  # a bigger, more varied field from the start
            name = self.rng.choice(WILDCARD_STRATS)
            self.vars.append(self._new(name, self._rand_params(name), tf=self.rng.choice(TIMEFRAMES),
                                       risk=self.rand_risk(), traits=self.rand_traits(), vetoes=self.rand_vetoes(),
                                       layers=self.rand_layers()))
        n_sc = self.scalp_target()
        del self.vars[max(self.cap, 14) - n_sc:]
        for i in range(n_sc):  # the scalp breed: one of each instinct at its usual settings, then random ones
            if i < len(SCALP_STRATS):
                self.vars.append(self._new(SCALP_STRATS[i], dict(STRATS[SCALP_STRATS[i]]["params"])))
            else:
                self.vars.append(self._rand_scalper())
        k_isl = int(self.o.get("islands", 1) or 1)
        for i, v in enumerate(self.vars):
            self._register(v, [], "classic" if v.classic else "starter")
            v.island = i % k_isl

    def window_for(self, tf):
        """How many bars a bot is judged over: slow bots get a longer window so they make enough decisions in it."""
        return self.W * min(max(1, clamp_tf(tf) // 2), 10)

    def _new(self, name, params, tf=1, risk=None, traits=None, vetoes=None, layers=None):
        if is_scalp(name):  # the scalp breed always stays inside its envelope, however it was bred
            tf, risk, traits = scalp_shape(self.rng, tf, risk, traits)
        elif traits and "flatby" in traits:
            traits = {k: x for k, x in traits.items() if k != "flatby"}
        v = Variant(name, params, make_sim(self.start_cash, self.fee, self.pct, slip=self.o.get("slip", 0.0)),
                    self.window_for(tf) + 1, tf, risk, traits, vetoes if self.o.get("vetoes", True) else None,
                    layers if self.o.get("layers", True) else None)
        v.sim.genes = v.traits
        v.picky = bool(self.o.get("coin_prefs", True))
        v.review = bool(self.o.get("post_review", True))
        if not self.o.get("adapt_exits", True):
            v.traits.pop("adapt", None)
        if not self.o.get("time_habits", True):
            for k in TIME_VETOES:
                (v.vetoes or {}).pop(k, None)
        if not self.o.get("htf_studies", True):
            v.layers.pop("htf", None)
        if not self.o.get("lead_study", True):
            v.layers.pop("lead", None)
        v.conf_size = bool(self.o.get("confidence_sizing", True))
        v.rt_cost = 2 * (self.fee + self.o.get("slip", 0.0))
        v.fee_guard = 2 * (self.fee + self.o.get("slip", 0.0)) if self.o.get("fee_aware", True) else 0.0
        return v

    # ---- the scalp breed ----
    def scalp_target(self):
        """How many scalpers this farm keeps at least (0 = the breed is switched off here)."""
        sh = float(self.o.get("scalp_share", 0) or 0)
        return 0 if sh <= 0 else max(2, int(round(self.cap * sh)))

    def scalpers(self):
        return [v for v in self.vars if is_scalp(v.name)]

    def _rand_scalper(self):
        name = self.rng.choice(SCALP_STRATS)
        return self._new(name, self._rand_params(name), self.rng.choice((1, 1, 2)), None, self.rand_traits(0.2),
                         self.rand_vetoes(), self.rand_layers(0.25))

    def spawn_scalp(self, closes=None):
        """Hatches one scalper: a tweaked copy of the best scalper (winners first), or a random one. Makes room by
        dropping the weakest long-term bot that isn't winning. Returns the new bot or None."""
        ranked = [v for v, _ in self.ranking() if is_scalp(v.name)]
        par = next((v for v in ranked if v in self.active), None)
        if par is None and ranked and self.rng.random() < 0.6:
            par = ranked[0]
        if len(self.vars) >= self.cap:
            cands = [v for v, _ in reversed(self.ranking()) if v not in self.active and not is_scalp(v.name)]
            cands = [v for v in cands if sum(1 for x in self.vars if x.name == v.name) > 1] or cands
            if not cands:
                return None
            self._remove(cands[0], "made room for a scalper")
        if par is not None:
            vt, vs = self.inherit_vetoes([par])
            ly, ls = self.inherit_layers([par], par.name)
            child = self._new(par.name, self.mutate(par.name, par.params, 0.25), self.mutate_tf(par.tf),
                              self.mutate_risk(par.risk), self.mutate_traits(par.traits), vt, ly)
            child.veto_stats, child.layer_stats = vs, ls
            self._register(child, [par], "scalp hatch")
            note = f"Scalp egg: {child.label} (from {par.label})"
        else:
            child = self._rand_scalper()
            self._register(child, [], "random scalper")
            note = f"Scalp egg: {child.label}"
        if closes:
            self.replay(child, closes)
        self.vars.append(child)
        self.events.append(note)
        return child

    def scalp_balance(self, closes):
        """Keeps the scalp breed between its share of the farm and twice that (never over 60%): enough scalpers to
        find the quick moves, never so many that the long-term bots are crowded out."""
        tgt, sc = self.scalp_target(), self.scalpers()
        if not tgt:
            for v in sc:
                self._remove(v, "scalpers switched off")
            if sc:
                self.events.append(f"Scalpers are off: {len(sc)} scalp bot{'s' if len(sc) != 1 else ''} left the farm")
            return
        for _ in range(min(2, tgt - len(sc))):  # a couple per round, so the farm isn't flooded at once
            self.spawn_scalp(closes)
        most = max(tgt, min(tgt * 2, int(self.cap * 0.6)))
        sc = self.scalpers()
        if len(sc) > most:
            weak = [v for v, _ in reversed(self.ranking()) if is_scalp(v.name) and v not in self.active]
            for v in weak[:len(sc) - most]:
                self._remove(v, "too many scalpers")
                self.events.append(f"Dropped {v.label} (the scalp den was full)")

    def rand_traits(self, chance=0.3):
        t = {}
        for k, spec in TRAITS.items():
            if self.rng.random() < chance:
                v = self.rng.uniform(spec["lo"], spec["hi"])
                if k == "moods":
                    v = self.rng.randint(1, 14)
                t[k] = v
        return clean_traits(t)

    def _rand_sub(self, avoid=None):
        name = self.rng.choice([n for n in WILDCARD_STRATS if n != avoid] or WILDCARD_STRATS)
        return dict(name=name, params=self._rand_params(name))

    def mut_bias(self, kind):
        """Mutation memory: how much more (or less) often this kind of change has produced winners than average
        (0.5 to 2). 1 when off or with too little evidence."""
        if not self.o.get("mut_memory", True):
            return 1.0
        st = self.mut_stats.get(kind)
        tb = sum(x[0] for x in self.mut_stats.values())
        if not st or st[0] < 8 or tb < 30:
            return 1.0
        avg = (sum(x[1] for x in self.mut_stats.values()) + 1) / (tb + 2)
        return min(2.0, max(0.5, ((st[1] + 1) / (st[0] + 2)) / avg))

    def rule_allowed(self, k):
        return (k not in EVENT_VETOES or events()) and (k not in TIME_VETOES or self.o.get("time_habits", True))

    def learn_from_losses(self, v, t):
        """A bot learns from its OWN losing trades while it lives: when one never-rule would have blocked at least
        3 of its losing buys and clearly fewer winners, the bot takes that rule on itself. The rule is then graded
        like any other, so it fades if it starts blocking good trades."""
        for k in t["flags"]:
            st = v.own_review.setdefault(k, [0, 0])
            st[0 if t["pl"] <= 0 else 1] += 1
        if len(v.vetoes) >= MAX_VETOES:
            return
        best = max(((st[0] - 2 * st[1], k) for k, st in v.own_review.items()
                    if k not in v.vetoes and st[0] >= 3 and st[0] > 2 * st[1] and self.rule_allowed(k)), default=None)
        if not best:
            return
        k = best[1]
        spec = VETOES[k]
        v.vetoes = clean_vetoes(dict(v.vetoes, **{k: (spec["lo"] + spec["hi"]) / 2}))
        v.own_review.pop(k, None)
        if k in v.vetoes:
            v.mut_kinds = list(v.mut_kinds) + ["self_review"]
            self.events.append(f"{v.label} learned from its losses: {spec['text'](v.vetoes[k])}")

    def review_pick(self, pool):
        """Post-trade review: a new never-rule is more likely to be one that would have stopped recent losing buys."""
        if not self.o.get("post_review", True) or not self.review:
            return self.rng.choice(pool)
        w = [(self.review.get(k, [0, 0])[0] + 1) / (self.review.get(k, [0, 0])[1] + 1) for k in pool]
        return self.rng.choices(pool, weights=w)[0]

    def rand_ctx(self):
        sym = self.rng.choice(self.ctx_syms)
        if self.rng.random() < 0.4:
            return dict(self._rand_sub(), sym=sym, kind="study", sign=self.rng.choice((1, -1)))
        return dict(sym=sym, kind="move", sign=self.rng.choice((1, -1)), lb=self.rng.randint(2, 30),
                    th=round(self.rng.uniform(0.2, 3.0), 2))

    def rand_layers(self, chance=0.35):
        """Extra rule layers for a new bot: a few positive studies, a few negative studies, exit studies, sizing."""
        if not self.o.get("layers", True):
            return {}
        out = {}
        if self.o.get("htf_studies", True) and self.rng.random() < chance * 0.6:
            out["htf"] = dict(self._rand_sub(), mult=self.rng.choice(HTF_MULTS))
        if self.ctx_syms and self.rng.random() < chance * 0.7:
            out["ctx"] = [self.rand_ctx() for _ in range(self.rng.randint(1, 2))]
        if self.o.get("lead_study", True) and self.rng.random() < chance * 0.4:
            out["lead"] = dict(lb=self.rng.randint(4, 30), th=round(self.rng.uniform(0.3, 2.5), 2))
        if self.rng.random() < chance:
            out["plus"] = [self._rand_sub() for _ in range(self.rng.randint(1, 3))]
        if self.rng.random() < chance:
            out["minus"] = [self._rand_sub() for _ in range(self.rng.randint(1, 2))]
        if self.rng.random() < chance * 0.7:
            out["exits"] = [self._rand_sub() for _ in range(self.rng.randint(1, 2))]
        if out.get("plus") or out.get("minus"):
            out["need"] = self.rng.randint(1, 1 + len(out.get("plus", [])))
        if self.rng.random() < chance * 0.6:
            out["size"] = dict(target=self.rng.uniform(0.15, 1.5))
        return clean_layers(out)

    def inherit_layers(self, parents, main_name):
        """Studies are pooled from the parents; each is usually kept (sometimes tweaked or swapped for another
        family), now and then dropped, and now and then a new one is tried. If negative studies have been costing
        money by blocking winning buys, they are more likely to be dropped; if they've been saving money, kept."""
        if not self.o.get("layers", True):
            return {}, {}
        out, stats = {}, {}
        caps = {"plus": MAX_PLUS, "minus": MAX_MINUS, "exits": MAX_EXITS}
        for key, cap in caps.items():
            pool = []
            for p in parents:
                for s in p.layers.get(key, []):
                    if all(json.dumps(s, sort_keys=True) != json.dumps(x, sort_keys=True) for x in pool):
                        pool.append(json.loads(json.dumps(s)))
            src_stats = [p.layer_stats.get(key) for p in parents if p.layer_stats.get(key)]
            st = max(src_stats, key=lambda x: x[0]) if src_stats else None
            bad = bool(st and st[0] >= 5 and st[1] < 0)
            good = bool(st and st[0] >= 5 and st[1] > 0)
            keep_p = 0.55 if bad else 0.92 if good else 0.8
            kept = []
            for s in pool:
                if self.rng.random() > keep_p:
                    continue
                roll = self.rng.random()
                if roll < 0.1:
                    s = self._rand_sub(avoid=s["name"])
                elif roll < 0.4:
                    s["params"] = self.mutate(s["name"], s["params"], 0.2)
                kept.append(s)
            self.rng.shuffle(kept)
            if len(kept) < cap and self.rng.random() < 0.12 * self.mut_bias("studies"):
                kept.append(self._rand_sub())
            if kept:
                out[key] = kept[:cap]
                if st and not bad and key in ("plus", "minus"):
                    stats[key] = [st[0] / 2, st[1] / 2]
        needs = [p.layers.get("need") for p in parents if p.layers.get("need")]
        if out.get("plus") or out.get("minus"):
            need = self.rng.choice(needs) if needs else 1 + len(out.get("plus", [])) // 2
            if self.rng.random() < 0.25:
                need += self.rng.choice((-1, 1))
            out["need"] = need
        if self.ctx_syms or any(p.layers.get("ctx") for p in parents):  # context studies, judged by their own evidence
            pool, seen = [], set()
            for p in parents:
                for e in p.layers.get("ctx", []):
                    k_ = json.dumps(e, sort_keys=True)
                    if k_ not in seen:
                        seen.add(k_)
                        pool.append(json.loads(k_))
            kept = []
            for e in pool:
                st = max((p.layer_stats.get(f"ctx:{e['sym']}") for p in parents if p.layer_stats.get(f"ctx:{e['sym']}")),
                         key=lambda x: x[0], default=None)
                bad, good = bool(st and st[0] >= 5 and st[1] < 0), bool(st and st[0] >= 5 and st[1] > 0)
                if self.rng.random() > (0.55 if bad else 0.92 if good else 0.8):
                    continue
                roll = self.rng.random()
                if roll < 0.06:
                    e["sign"] = -e["sign"]
                elif roll < 0.35:
                    if e.get("kind") == "study":
                        e["params"] = self.mutate(e["name"], e["params"], 0.2)
                    else:
                        e["lb"] = int(e["lb"] * self.rng.uniform(0.7, 1.4))
                        e["th"] = e["th"] * self.rng.uniform(0.75, 1.3)
                kept.append(e)
                if st and not bad:
                    stats[f"ctx:{e['sym']}"] = [st[0] / 2, st[1] / 2]
            if self.ctx_syms and len(kept) < MAX_CTX and self.rng.random() < 0.1 * self.mut_bias("studies"):
                kept.append(self.rand_ctx())
            if kept:
                out["ctx"] = kept[:MAX_CTX]
        for key, on in (("htf", self.o.get("htf_studies", True)), ("lead", self.o.get("lead_study", True))):
            if not on:
                continue
            have = [p.layers[key] for p in parents if p.layers.get(key)]
            st = max((p.layer_stats.get(key) for p in parents if p.layer_stats.get(key)), key=lambda x: x[0], default=None)
            bad = bool(st and st[0] >= 5 and st[1] < 0)
            if have and self.rng.random() < (0.55 if bad else 0.9):
                g = json.loads(json.dumps(self.rng.choice(have)))
                if self.rng.random() < 0.3:
                    if key == "htf":
                        if self.rng.random() < 0.5:
                            g["params"] = self.mutate(g["name"], g["params"], 0.2)
                        else:
                            g["mult"] = self.rng.choice(HTF_MULTS)
                    else:
                        g["lb"] = int(g["lb"] * self.rng.uniform(0.7, 1.4))
                        g["th"] = g["th"] * self.rng.uniform(0.75, 1.3)
                out[key] = g
                if st and not bad:
                    stats[key] = [st[0] / 2, st[1] / 2]
            elif not have and self.rng.random() < 0.06 * self.mut_bias("studies"):
                out[key] = (dict(self._rand_sub(), mult=self.rng.choice(HTF_MULTS)) if key == "htf"
                            else dict(lb=self.rng.randint(4, 30), th=round(self.rng.uniform(0.3, 2.5), 2)))
        sizes = [p.layers["size"] for p in parents if p.layers.get("size")]
        if sizes and self.rng.random() < 0.9:
            out["size"] = dict(target=self.rng.choice(sizes)["target"] * (self.rng.uniform(0.8, 1.25) if self.rng.random() < 0.4 else 1))
        elif not sizes and self.rng.random() < 0.06:
            out["size"] = dict(target=self.rng.uniform(0.15, 1.5))
        return clean_layers(out), stats

    def rand_vetoes(self, chance=0.35):
        if not self.o.get("vetoes", True) or self.rng.random() > chance:
            return {}
        out = {}
        for _ in range(self.rng.randint(1, 2)):
            k = self.review_pick([k for k in VETOES if k not in out and self.rule_allowed(k)])
            out[k] = self.rng.uniform(VETOES[k]["lo"], VETOES[k]["hi"])
        return clean_vetoes(out)

    def inherit_vetoes(self, parents):
        """Never-rules for a child: proven rules (saved money when they blocked trades) are very likely passed on,
        rules that keep blocking winners tend to be dropped, values get small tweaks, and now and then a new rule
        is tried. The child also inherits half of its parents' evidence for each rule."""
        if not self.o.get("vetoes", True):
            return {}, {}
        pool = {}
        for p in parents:
            for k, x in p.vetoes.items():
                st = p.veto_stats.get(k, [0.0, 0.0])
                avg = st[1] / st[0] if st[0] else 0.0
                if k not in pool or avg > pool[k][1]:
                    pool[k] = (x, avg, st)
        out, stats = {}, {}
        for k, (x, avg, st) in sorted(pool.items(), key=lambda kv: -kv[1][1]):
            proven_bad = st[0] >= 5 and avg < 0
            keep = 0.25 if proven_bad else 0.95 if avg > 0 and st[0] >= 5 else 0.8
            if self.rng.random() < keep and len(out) < MAX_VETOES:
                if self.rng.random() < 0.35:
                    x *= self.rng.uniform(0.8, 1.25)
                out[k] = x
                stats[k] = [st[0] / 2, st[1] / 2]
        if len(out) < MAX_VETOES and self.rng.random() < 0.15 * self.mut_bias("rules"):
            k = self.review_pick([k for k in VETOES if k not in out and self.rule_allowed(k)])
            out[k] = self.rng.uniform(VETOES[k]["lo"], VETOES[k]["hi"])
        out = clean_vetoes(out)
        return out, {k: s for k, s in stats.items() if k in out}

    def mutate_traits(self, t):
        out = dict(t)
        for k, spec in TRAITS.items():
            roll = self.rng.random()
            if roll < 0.08 * self.mut_bias("traits"):  # switch a trait on or off
                if k in out:
                    out.pop(k)
                else:
                    out[k] = self.rng.randint(1, 14) if k == "moods" else self.rng.uniform(spec["lo"], spec["hi"])
            elif k in out and roll < 0.35:
                if k == "moods":
                    out[k] = out[k] ^ (1 << self.rng.randrange(len(MOODS))) or out[k]
                else:
                    out[k] = out[k] * self.rng.uniform(0.75, 1.3)
        return clean_traits(out)

    def _register(self, v, parents, origin):
        """Gives a bot its id and family-tree entry."""
        self.serial += 1
        v.uid, v.parents, v.origin = self.serial, [p.uid for p in parents], origin
        v.royal = origin in ("hall of fame", "library", "team", "collection", "saved", "bred from your bots", "designed") or \
            any(getattr(p, "royal", False) for p in parents)
        v.gen = 1 + max((p.gen for p in parents), default=-1) if parents else 0
        k_isl = int(self.o.get("islands", 1) or 1)
        if parents:
            v.island = parents[0].island
        elif k_isl > 1 and self.vars:  # newcomers join the smallest island
            sizes = [sum(1 for x in self.vars if x.island == i) for i in range(k_isl)]
            v.island = sizes.index(min(sizes))
        if parents:
            p0 = parents[0]
            kinds = [k for k, same in (("pace", v.tf == p0.tf), ("stops", v.risk == p0.risk), ("traits", v.traits == p0.traits),
                                       ("rules", v.vetoes == p0.vetoes), ("studies", v.layers == p0.layers),
                                       ("settings", v.params == p0.params)) if not same]
            if len(parents) > 1:
                kinds.append("crossbreed")
            v.mut_kinds = kinds
            for k in kinds:
                self.mut_stats.setdefault(k, [0, 0])[0] += 1
        self.births.append(self.n)
        self.lineage[v.uid] = dict(uid=v.uid, label=v.label, name=v.name, tf=v.tf, parents=list(v.parents),
                                   gen=v.gen, origin=origin, born=self.n, died=None, why="", ret=None, inducted=False)

    def _remove(self, v, why):
        if v in self.vars:
            self.vars.remove(v)
            if self.o.get("elders", True) and v.ntrades >= 3 and v.eq:
                lf = self.life(v)
                if lf["ret"] > 0 and (lf["edge"] is None or lf["edge"] > 0):
                    self.elders.append(dict(name=v.name, params=dict(v.params), tf=v.tf, edge=lf["edge"] or lf["ret"]))
                    del self.elders[:-40]
        self.deaths.append(self.n)
        rec = self.lineage.get(v.uid)
        if rec:
            rec.update(died=self.n, why=why, ret=v.eq[-1] / v.sim.start - 1 if v.eq else None, inducted=v.inducted)
        dead = [u for u, r in self.lineage.items() if r["died"] is not None]
        for u in dead[:-400]:  # keep the tree from growing forever
            del self.lineage[u]

    def rand_risk(self):
        """About half of new random bots carry their own stop-loss and/or take-profit."""
        r = {}
        for k, (lo, hi) in RISK_BOUNDS.items():
            hi = self.risk_caps.get(k, hi)
            r[k] = round(self.rng.uniform(lo, hi * 0.5), 2) if self.rng.random() < 0.5 else 0.0
        return r

    def mutate_risk(self, r):
        out = {}
        for k, (lo, hi) in RISK_BOUNDS.items():
            hi = self.risk_caps.get(k, hi)
            v = float(r.get(k, 0) or 0)
            roll = self.rng.random()
            if roll < 0.1 * self.mut_bias("stops"):  # switch it on or off
                v = 0.0 if v else self.rng.uniform(lo, hi * 0.5)
            elif v and roll < 0.45:
                v *= self.rng.uniform(0.7, 1.3)
            out[k] = min(v, hi)
        return clean_risk(out)

    def mutate_tf(self, tf):
        """Usually keep the parent's pace; sometimes move one step faster or slower."""
        i = TIMEFRAMES.index(clamp_tf(tf))
        if self.rng.random() < min(0.8, 0.4 * self.mut_bias("pace")):
            i = min(max(i + self.rng.choice((-1, 1)), 0), len(TIMEFRAMES) - 1)
        return TIMEFRAMES[i]

    def _run(self, v, closes, n, mood=None, extra=None):
        last = {c: closes[c][-1] for c in self.coins}
        if v.born_px is None:
            v.born_px = dict(last)
        prev_eq = v.eq[-1] if v.eq else None
        x = extra if extra is not None else self.xfull
        made = bot_step(v, closes, n, self.coins, x)
        for c, t in made:
            v.log.append((n, c, t["side"], last[c]))
            v.ntrades += 1
            if t["side"] == "sell":
                if t["pl"] > 0:
                    v.wins += 1
                else:
                    v.losses += 1
                if t.get("flags") and not self.replaying:
                    for k in t["flags"]:
                        self.review.setdefault(k, [0, 0])[0 if t["pl"] <= 0 else 1] += 1
                    if self.o.get("learn_losses", True):
                        self.learn_from_losses(v, t)
            if self.recording:
                self.shadow.append(dict(t, name=v.name, params=dict(v.params), tf=v.tf, uid=v.uid))
            if self.on_trade:
                try:
                    self.on_trade(v, c, t, data_now(x, [c]) if x else None)
                except Exception:
                    pass
        e = v.sim.equity(last)
        if is_scalp(v.name) and (not v.trade_eq or any(t_["side"] == "sell" for _, t_ in made)):
            v.trade_eq.append((n, e))  # scalpers are judged trade by trade (the first entry is the starting point)
        if not self.replaying:
            if v.live_eq0 is None:
                v.live_eq0 = prev_eq if prev_eq else v.sim.start
            v.live_n += 1
        v.eq.append(e)
        v.age += 1
        v.peak = max(v.peak, e)
        if v.peak > 0:
            v.maxdd = max(v.maxdd, (v.peak - e) / v.peak)
        if mood and mood != "unknown" and prev_eq:
            v.mood_gain[mood] = v.mood_gain.get(mood, 0.0) + (e / prev_eq - 1)
            v.mood_n[mood] = v.mood_n.get(mood, 0) + 1
        while v.sim.tbars and v.sim.tbars[0] <= n - (v.eq.maxlen - 1):
            v.sim.tbars.popleft()

    def hold_over(self, k):
        """What just holding the coins (equal weight) returned over the last k decisions, or None."""
        hc = self.hold_curve
        return hc[-1] / hc[-1 - k] - 1 if len(hc) > k else None

    def _market(self, closes):
        if not hasattr(self, "hold_curve"):
            self.hold_curve = deque([1.0], maxlen=self.W * 10 + 2)
        if all(len(closes[c]) >= 2 and closes[c][-2] for c in self.coins):
            self.hold_curve.append(self.hold_curve[-1] * sum(closes[c][-1] / closes[c][-2] for c in self.coins) / len(self.coins))
        self.last_px = {c: closes[c][-1] for c in self.coins}
        L = min(len(closes[c]) for c in self.coins)
        self.hold_ret = (sum(closes[c][-1] / closes[c][-1 - self.W] for c in self.coins) / len(self.coins) - 1
                         if L > self.W else None)
        self.moods = {c: market_mood(closes[c])[0] for c in self.coins}
        known = [m for m in self.moods.values() if m != "unknown"]
        self.mood = max(set(known), key=known.count) if known else "unknown"

    def step(self, closes, extra=None):
        """closes: coin -> list of bar closes, newest last, same length per coin.
        extra (optional): coin -> {'h': highs, 'l': lows, 'v': volumes}, lined up with the closes."""
        self.n += 1
        self.xfull = extra
        self._market(closes)
        for c in self.coins:
            self.cool[c] = max(0, self.cool.get(c, 0) - 1)
            self.add_cool[c] = max(0, self.add_cool.get(c, 0) - 1)
        for v in self.vars:
            self._run(v, closes, self.n, self.mood)
        self._rate()
        for v in self.vars:
            if self.info[id(v)]["status"] == "active":
                v.win_steps += 1
                v.streak += 1
            else:
                v.streak = 0
        if self.retire_steps:
            self._rotate(closes)
        if self.n % self.evolve_every == 0:
            self.evolve(closes)

    def warmup(self, closes, start=WARM, progress=None, extra=None):
        L = min(len(closes[c]) for c in self.coins)
        for i in range(start, L):
            self.step({c: View(closes[c], i + 1) for c in self.coins}, slice_extra(extra, i + 1))
            if progress and (i - start) % 50 == 0:
                progress(i - start, L - start)

    def score(self, v):
        te = scalp_record(v)
        if te:  # a scalper: its gain over its last trades, however long it waited between them
            return te[-1][1] / te[0][1] - 1 if te[0][1] > 0 else None
        need = self.min_trades if v.tf < 10 else 1  # slow, long-holding bots trade rarely by design
        if len(v.eq) < v.eq.maxlen or len(v.sim.tbars) < need or v.eq[0] <= 0:
            return None
        return v.eq[-1] / v.eq[0] - 1

    def consistency(self, v):
        """Share of the 4 recent sub-periods in which the variant made money (0..1). Scalpers: 4 blocks of trades."""
        te = scalp_record(v)
        if te:
            eq = [x for _, x in te]
            size = (len(eq) - 1) // 4
            return sum(1 for k in range(4) if eq[(k + 1) * size] > eq[k * size]) / 4 if size >= 1 else 0.0
        eq = list(v.eq)
        size = (len(eq) - 1) // 4
        if len(eq) < v.eq.maxlen or size < 1:
            return 0.0
        return sum(1 for k in range(4) if eq[(k + 1) * size] > eq[k * size]) / 4

    @property
    def prove_n(self):
        """Decisions on fresh prices a bot needs before it may be followed as a winner."""
        return max(10, self.W // 4)

    def sortino(self, v):
        """Average gain per decision divided by the typical size of its losing decisions (higher = steadier)."""
        eq = list(v.eq)
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
        if len(rets) < 10:
            return 0.0
        mean = sum(rets) / len(rets)
        down = (sum(min(r, 0) ** 2 for r in rets) / len(rets)) ** 0.5
        if down <= 1e-12:
            return 5.0 if mean > 0 else 0.0
        return max(0.0, mean / down * (len(rets) ** 0.5) / 3)

    def drawdown(self, v):
        """How far the variant's equity sits below its recent peak (0..1)."""
        eq = list(v.eq)
        peak = max(eq) if eq else 0
        return (peak - eq[-1]) / peak if peak > 0 else 0.0

    def mood_fit(self, v, mood=None):
        """Average gain per decision while `mood` ruled, or None with too little evidence."""
        mood = mood or self.mood
        k = v.mood_n.get(mood, 0)
        return v.mood_gain.get(mood, 0.0) / k if k >= 30 else None

    def best_mood(self, v):
        fits = [(self.mood_fit(v, m), m) for m in MOODS]
        fits = [x for x in fits if x[0] is not None]
        return max(fits)[1] if fits and max(fits)[0] > 0 else None

    def health(self, v):
        """0..1: how the bot is doing right now. Falls with drawdown from its recent best; never-rules that keep
        saving money add a little, rules that keep blocking winners take some away. Very low health = it rests."""
        h = 1.0 - self.drawdown(v) * 8 if v.eq else 1.0
        bonus = 0.0
        for k in v.vetoes:
            st = v.veto_stats.get(k)
            if st and st[0] >= 3:
                bonus += max(-0.15, min(0.1, st[1] / st[0] / 20))
        return max(0.0, min(1.0, h + bonus))

    def update_power(self, v, edge):
        """Power grows only from real money made on fresh prices (not replays) while beating just holding, and
        fades slowly otherwise. It raises the bot's trade-size ceiling, its say in votes and its breeding odds."""
        if self.replaying or not v.eq:
            return
        e = v.eq[-1]
        if v.live_high is None:
            v.live_high = e
        if e > v.live_high and (edge is None or edge > 0):
            v.power = min(10.0, v.power + (e / v.live_high - 1) * 40)  # a slow, earned climb
            v.live_high = e
        elif e < v.live_high * 0.98:
            v.power = max(0.0, v.power - 0.02)

    def life(self, v):
        """Lifetime track record since the bot was created."""
        ret = v.eq[-1] / v.sim.start - 1 if v.eq and v.sim.start else 0.0
        hold = None
        if v.born_px and self.last_px:
            r = [self.last_px[c] / v.born_px[c] for c in self.coins if v.born_px.get(c) and c in self.last_px]
            hold = sum(r) / len(r) - 1 if r else None
        closed = v.wins + v.losses
        return dict(ret=ret, hold=hold, edge=None if hold is None else ret - hold, trades=v.ntrades,
                    wins=v.wins, losses=v.losses, winrate=v.wins / closed if closed else None,
                    maxdd=v.maxdd, age=v.age, win_steps=v.win_steps, streak=v.streak, best_mood=self.best_mood(v),
                    fees=v.sim.fees)

    def _rate(self):
        info, o = {}, self.o
        for v in self.vars:
            sc = self.score(v)
            if sc is None:
                info[id(v)] = dict(score=None, cons=None, weight=0.0, stake=0.0, status="warming up", failing=False,
                                   edge=None, behind=False)
                continue
            cons = self.consistency(v)
            te = scalp_record(v)
            span = (self.n - te[0][0]) if te else len(v.eq) - 1  # scalpers: holding over the stretch of their trades
            if hasattr(self, "hold_curve"):
                span = max(1, min(span, len(self.hold_curve) - 1))
            hold = self.hold_over(span) if hasattr(self, "hold_curve") else self.hold_ret
            edge = None if hold is None else sc - hold
            behind = bool(o["beat_hold"] and edge is not None and edge <= 0)
            failing = (o["fail_drop"] > 0 and self.drawdown(v) * 100 > o["fail_drop"]) or self.health(v) < 0.1
            self.update_power(v, None if self.hold_ret is None else sc - (self.hold_over(span)
                                                                          if hasattr(self, "hold_curve") else self.hold_ret))
            base = edge if (o["beat_hold"] and edge is not None and edge > 0) else sc
            proving = bool(o.get("prove_live", True)) and (
                v.live_n < max(10, (v.eq.maxlen - 1) // 4) or (v.eq and v.live_eq0 and v.eq[-1] < v.live_eq0))
            if failing or sc <= 0 or cons < 0.25:
                status, w = "benched", 0.0
            elif cons >= 0.5 and not behind and not proving:
                status, w = "active", base * cons ** 2
            else:
                status, w = "slowed", sc * cons ** 2
            if w > 0 and o.get("risk_adjusted", True):
                w *= 0.5 + min(self.sortino(v), 5.0) / 2  # steady gains count for more than bumpy ones
            if w > 0:
                w *= 1 + v.power / 10  # proven power: a bigger say
            if w > 0 and v.twin is not None and v.twin <= 0:
                w *= 0.6  # failed its twin test: probably lucky, so it counts for less
            if w > 0 and o.get("luck_check", True):
                w *= luck_factor(v)  # a great score from a handful of trades counts for less than one from many
            if w > 0 and o["regime_aware"]:
                fit = self.mood_fit(v)
                if fit is not None:
                    w *= 1.25 if fit > 0 else 0.8
            info[id(v)] = dict(score=sc, cons=cons, weight=w, stake=0.0, status=status, failing=failing,
                               edge=edge, behind=behind, proving=proving and status == "slowed" and not behind)
            if status == "active" and not v.credited:
                v.credited = True
                for k in v.mut_kinds:
                    self.mut_stats.setdefault(k, [0, 0])[1] += 1
        ranked = sorted((v for v in self.vars if info[id(v)]["status"] == "active"),
                        key=lambda v: -info[id(v)]["weight"])
        self.active = ranked[:self.max_active]
        top = info[id(self.active[0])]["weight"] if self.active else 0
        hi = max(1.0, o["winner_boost"] if o["trade_more"] else 2.0)
        for v in self.active:
            d = info[id(v)]
            d["stake"] = 0.5 + (hi * (1 + v.power / 20) - 0.5) * d["weight"] / top  # power lifts the size ceiling
        for v in ranked[self.max_active:]:
            info[id(v)].update(status="standby", weight=0.0)
        self.slowed = sorted((v for v in self.vars if info[id(v)]["status"] == "slowed"),
                             key=lambda v: -info[id(v)]["weight"])
        for v in self.slowed:
            info[id(v)]["stake"] = 0.25
        for v in self.vars:
            d = info[id(v)]
            if d["status"] in ("active", "slowed"):
                d["stake"] *= v.size_mult
        self.info = info

    def ranking(self):
        r = [(v, self.score(v)) for v in self.vars]
        if self.o.get("luck_check", True):  # breeding and culling also trust long records over short lucky ones
            return sorted([x for x in r if x[1] is not None],
                          key=lambda x: -(x[1] * luck_factor(x[0]) if x[1] > 0 else x[1]))
        return sorted([x for x in r if x[1] is not None], key=lambda x: -x[1])

    def drivers(self):
        return list(self.active)

    def summary(self):
        """(number of active winners, best variant or None, any variant scored yet)"""
        scored = any(d["score"] is not None for d in self.info.values())
        return len(self.active), (self.active[0] if self.active else None), scored

    @staticmethod
    def _holding(v, c):
        return v.sim.pos.get(c, 0) > 0

    def vote(self, c):
        """-> (signal, size multiplier). Winners vote at full weight, shaky strategies at a
        small weight. A vote that only shaky strategies want must wait out a cooldown, so they
        trade slowly. When nobody has a fresh signal but strong winners are holding the coin,
        the account adds to the position now and then (self.kind[c] == "add")."""
        self.kind[c] = None
        bw = sw = bs = ss = 0.0
        act_buy = act_sell = False
        for v in self.active + self.slowed:
            d, s = self.info[id(v)], v.sig.get(c)
            is_act = d["status"] == "active"
            if s == "buy":
                bw += d["weight"]
                bs += d["weight"] * d["stake"]
                act_buy = act_buy or is_act
            elif s == "sell":
                sw += d["weight"]
                ss += d["weight"] * d["stake"]
                act_sell = act_sell or is_act
        sig, mult, from_winner = None, 1.0, False
        if bw > sw:
            sig, mult, from_winner = "buy", bs / bw, act_buy
        elif sw > bw:
            sig, mult, from_winner = "sell", ss / sw, act_sell
        if sig == "buy" and self.o.get("agree_sizing", True):
            # several DIFFERENT strategies agreeing = more confidence; a split farm = less
            kinds = {v.name for v in self.active + self.slowed if v.sig.get(c) == "buy"}
            split = sw / (bw + sw) if bw + sw else 0.0
            agree = min(1.3, 0.85 + 0.15 * (len(kinds) - 1)) * (1 - 0.6 * split)
            self.agree[c] = (len(kinds), round(agree, 2), round(split, 2))
            mult *= agree
        if sig and not from_winner:  # only shaky strategies want this: slow it down
            if self.cool.get(c, 0) > 0:
                return None, 1.0
            self.cool[c] = self.o["slow_every"]
            self.kind[c] = "slow"
        if sig is None and self.o["trade_more"] and self.add_cool.get(c, 0) == 0:
            holders = [v for v in self.active if self._holding(v, c) and self.info[id(v)]["cons"] >= 0.75]
            hw = sum(self.info[id(v)]["weight"] for v in holders)
            tw = sum(self.info[id(v)]["weight"] for v in self.active)
            if holders and hw * 2 > tw:  # winners with most of the weight are still in this coin
                self.add_cool[c] = self.o["add_every"]
                self.kind[c] = "add"
                avg = sum(self.info[id(v)]["weight"] * self.info[id(v)]["stake"] for v in holders) / hw
                return "buy", 0.5 * avg
        return sig, mult

    def board(self):
        """Rows for the scoreboard / farm. Cached until the ratings change, so drawing never recomputes it."""
        key = (id(self.info), self.n, len(self.vars))
        if getattr(self, "_board_key", None) == key:
            return self._board_rows
        self._board_rows = self._board()
        self._board_key = key
        return self._board_rows

    def _board(self):
        blank = dict(score=None, cons=None, stake=0.0, status="warming up", failing=False, edge=None, behind=False, proving=False)
        order = {"active": 0, "slowed": 1, "standby": 2, "benched": 3, "warming up": 4}
        rows = [(v, self.info.get(id(v), blank)) for v in self.vars]
        rows.sort(key=lambda x: (order[x[1]["status"]], -(x[1]["score"] or 0)))
        return [dict(name=v.name, params=dict(v.params), label=v.label, score=d["score"], cons=d["cons"],
                     stake=d["stake"], status=d["status"], trades=len(v.sim.tbars), strikes=v.strikes, tf=v.tf,
                     failing=d.get("failing", False), driving=d["status"] == "active", v=v, size=v.size_mult,
                     edge=d.get("edge"), behind=d.get("behind", False), proving=d.get("proving", False),
                     life=self.life(v), origin=v.origin,
                     risk=dict(v.risk), traits=dict(v.traits), uid=v.uid, parents=list(v.parents), gen=v.gen,
                     classic=v.classic, vetoes=dict(v.vetoes), veto_stats={k: list(s) for k, s in v.veto_stats.items()},
                     health=self.health(v), power=v.power, layers=json.loads(json.dumps(v.layers)),
                     layer_stats={k: list(s) for k, s in v.layer_stats.items()}, twin=v.twin,
                     bad_coins=[c for c, x in v.coin_pl.items() if x[0] >= 3 and x[1] < -1.5], island=v.island)
                for v, d in rows]

    def mutate(self, name, params, scale=0.25):
        spec, new = STRATS[name], {}
        for k, val in params.items():
            lo, hi = spec["bounds"][k]
            nv = min(max(val * self.rng.uniform(1 - scale, 1 + scale), lo), hi)
            new[k] = int(round(nv)) if isinstance(spec["params"][k], int) else round(nv, 2)
        return fix_params(name, new)

    def crossover(self, name, a, b):
        """Child settings: each setting taken from one parent or the other, then lightly tweaked."""
        mix = {k: (a[k] if self.rng.random() < 0.5 else b.get(k, a[k])) for k in a}
        return self.mutate(name, mix, scale=0.1)

    def replay(self, v, closes):
        L = min(len(closes[c]) for c in self.coins)
        m = min(v.eq.maxlen, L - WARM)
        rec, self.recording = self.recording, False  # replayed history is not a new trade
        self.replaying = True
        try:
            x = self.xfull if self.xfull and all(len((self.xfull.get(c) or {}).get("h", ())) == len(closes[c])
                                                 for c in self.coins) else None
            for j in range(m):
                i = L - m + j
                self._run(v, {c: View(closes[c], i + 1) for c in self.coins}, self.n - (m - 1 - j),
                          extra=slice_extra(x, i + 1) if x else {})
        finally:
            self.recording = rec
            self.replaying = False

    def evolve(self, closes):
        for v in self.vars:  # strikes: checks spent benched (slowed counts half, standby none)
            st = self.info[id(v)]["status"]
            if st == "active":
                v.strikes = 0
            elif st == "benched":
                v.strikes += 1
            elif st == "slowed":
                v.strikes += 0.5
        retired = 0
        for v in sorted(self.vars, key=lambda x: -x.strikes):
            if v.strikes >= self.retire_after and sum(1 for x in self.vars if x.name == v.name) > 1:
                self._remove(v, "retired (kept losing)")
                retired += 1
                self.events.append(f"Retired {v.label} (kept losing)")
        strong = any(self.info[id(v)]["cons"] >= 0.75 and self.info[id(v)]["score"] > 0 for v in self.active)
        for _ in range(max(1, retired) + (1 if self.o["trade_more"] and strong else 0)):
            self._spawn(closes)  # strong winners get an extra tweaked copy
        for _ in range(min(3, self.cap - len(self.vars))):  # keep filling up to the limit
            self._spawn_or_random(closes)
        self.scalp_balance(closes)
        self.evolves += 1
        k_isl = int(self.o.get("islands", 1) or 1)
        if k_isl > 1 and self.evolves % 8 == 0:
            self.migrate(closes)
        if self.o.get("twin_test", True):
            for v in [x for x in self.active if x.twin is None][:2]:
                self.twin_test(v, closes)
        if self.o.get("seasons", True):
            self.seasons_tick(closes)
        self._rate()

    def migrate(self, closes):
        """Islands: each island's best bot sends a copy of itself to the next island."""
        k_isl = int(self.o.get("islands", 1) or 1)
        moved = 0
        for i in range(k_isl):
            best = next((v for v, _ in self.ranking() if v.island == i), None)
            if not best:
                continue
            if len(self.vars) >= self.cap:
                cands = [v for v, _ in reversed(self.ranking()) if v not in self.active and v is not best]
                if not cands:
                    continue
                self._remove(cands[0], "dropped to make room")
            child = self._new(best.name, dict(best.params), best.tf, best.risk, best.traits, best.vetoes, best.layers)
            self._register(child, [best], "migrant")
            child.island = (i + 1) % k_isl
            self.replay(child, closes)
            self.vars.append(child)
            moved += 1
        if moved:
            self.events.append(f"Migration: {moved} island champion{'s' if moved != 1 else ''} moved to the next island")

    # ---- elders, twins and seasons ----
    def elder_nudge(self, name, params):
        """Now and then pull a new egg's settings part of the way toward a good bot of its family that left."""
        if not self.o.get("elders", True) or self.rng.random() > 0.3:
            return params
        el = [e for e in self.elders if e["name"] == name]
        if not el:
            return params
        e = self.rng.choices(el, weights=[max(1e-4, x["edge"]) for x in el])[0]
        spec, out = STRATS[name], {}
        for k, val in params.items():
            t = e["params"].get(k, val)
            nv = val + (t - val) * self.rng.uniform(0.2, 0.6)
            out[k] = int(round(nv)) if isinstance(spec["params"][k], int) else round(nv, 2)
        return fix_params(name, out)

    def twin_test(self, v, closes):
        """Runs an exact copy of v on an older stretch of prices it was never scored on. Its edge over holding
        there is kept in v.twin: a winner whose twin loses to holding was probably just lucky."""
        L = min(len(closes[c]) for c in self.coins)
        m = v.eq.maxlen - 1
        end = L - m
        start = end - m
        if start < WARM:
            return None
        tw = self._new(v.name, dict(v.params), v.tf, v.risk, v.traits, v.vetoes, v.layers)
        x = self.xfull if self.xfull and all(len((self.xfull.get(c) or {}).get("h", ())) == len(closes[c])
                                             for c in self.coins) else None
        for i in range(start, end):
            bot_step(tw, {c: View(closes[c], i + 1) for c in self.coins}, i, self.coins, slice_extra(x, i + 1) if x else {})
        lastp = {c: closes[c][end - 1] for c in self.coins}
        ret = tw.sim.equity(lastp) / tw.sim.start - 1
        hold = sum(closes[c][end - 1] / closes[c][start - 1] for c in self.coins) / len(self.coins) - 1
        v.twin = ret - hold
        self.events.append(f"Twin test for {v.label}: {'passed' if v.twin > 0 else 'failed'} "
                           f"({v.twin * 100:+.1f}% vs holding on older prices)")
        return v.twin

    def seasons_tick(self, closes):
        """Keeps a champion per market mood. When the mood changes, the new season's champion is woken up
        (hatched again from its genes) if it's no longer on the farm."""
        for v in self.vars:
            for m in MOODS:
                fit = self.mood_fit(v, m)
                if fit is not None and fit > 0 and fit > self.champions.get(m, {}).get("fit", 0):
                    self.champions[m] = dict(name=v.name, params=dict(v.params), tf=v.tf, risk=dict(v.risk),
                                             traits=dict(v.traits), vetoes=dict(v.vetoes),
                                             layers=json.loads(json.dumps(v.layers)), fit=fit, uid=v.uid,
                                             label=v.label)
        mood = self.mood
        if mood == "unknown" or mood == self.season:
            self._season_cand = None
            return
        # a new season only starts once the new mood has held for a while (no flicker)
        cand = getattr(self, "_season_cand", None)
        if not cand or cand[0] != mood:
            self._season_cand = (mood, self.n)
            if self.season is not None:
                return
        elif self.n - cand[1] < max(20, self.evolve_every * 2):
            return
        old, self.season = self.season, mood
        self.seasons_log.append((self.n, mood))
        del self.seasons_log[:-50]
        if old is None:
            return
        ch = self.champions.get(mood)
        if not ch:
            self.events.append(f"Season change: {mood}. No champion for it yet")
            return
        if any(x.uid == ch["uid"] for x in self.vars):
            self.events.append(f"Season change: {mood}. Its champion {ch['label']} is already on the farm")
            return
        v = self.add_variant(ch["name"], ch["params"], closes, note=f"Season change: {mood}. Woke its champion",
                             tf=ch["tf"], origin="season champion", risk=ch["risk"], traits=ch["traits"],
                             vetoes=ch["vetoes"], layers=ch["layers"])
        if v:
            ch["uid"] = v.uid
            if len(self.vars) > self.cap:
                cands = [x for x, _ in reversed(self.ranking()) if x not in self.active and x is not v]
                if cands:
                    self._remove(cands[0], "dropped to make room")

    def _spawn_or_random(self, closes):
        before = len(self.vars)
        self._spawn(closes)
        if len(self.vars) == before and len(self.vars) < self.cap:
            self.spawn_random(closes)

    def _rotate(self, closes):
        """Replaces bots that have gone retire_steps decisions without winning (losing, or never trading)."""
        gone = []
        for v in self.vars:
            st = self.info.get(id(v), {}).get("status")
            v.bad = 0 if st in ("active", "slowed", "standby") else getattr(v, "bad", 0) + 1
            if v.bad >= self.retire_steps and len(self.vars) - len(gone) > 8:
                gone.append(v)
        for v in gone:
            self._remove(v, "rotated out (not winning for a long time)")
            self.events.append(f"Rotated out {v.label} (not winning for a long time)")
        for _ in gone:
            self._spawn_or_random(closes)
        if gone:
            self._rate()

    def _spawn(self, closes):
        k_isl = int(self.o.get("islands", 1) or 1)
        pool = self.active
        if k_isl > 1:  # islands take turns breeding, each from its own winners (or its own best)
            isl = self.spawn_i % k_isl
            self.spawn_i += 1
            pool = [v for v in self.active if v.island == isl]
            if not pool:
                own = [v for v, _ in self.ranking() if v.island == isl]
                pool = own[:1]
        if pool and (pool is not self.active or self.active):
            # fitness sharing: a family's weight is shared among its members, so one lucky family can't take over
            fam_n = {}
            for x in self.vars:
                fam_n[x.name] = fam_n.get(x.name, 0) + 1
            parent = self.rng.choices(pool, weights=[max(1e-9, self.info.get(id(v), {}).get("weight", 0)) / fam_n[v.name]
                                                     * (1 + v.power / 10) for v in pool])[0]
        else:
            r = self.ranking()
            if not r:
                return
            parent = r[0][0]
        fam = sum(1 for x in self.vars if x.name == parent.name)
        if fam >= self.family_cap or len(self.vars) >= self.cap:
            cands = [v for v, _ in reversed(self.ranking()) if v is not parent and v not in self.active
                     and sum(1 for x in self.vars if x.name == v.name) > 1]
            if fam >= self.family_cap:
                cands = [v for v in cands if v.name == parent.name]
            if not cands:
                return
            self._remove(cands[0], "dropped to make room")
            self.events.append(f"Dropped {cands[0].label}")
        mate = None
        if self.o.get("crossbreed", True) and self.rng.random() < 0.4:
            good = [v for v in self.vars if v is not parent and v.name == parent.name and v.island == parent.island
                    and self.info.get(id(v), {}).get("status") in ("active", "standby", "slowed")]
            if good:
                mate = self.rng.choice(good)
        if mate:
            risk = {k: self.rng.choice((parent.risk[k], mate.risk[k])) for k in RISK_BOUNDS}
            traits = {}
            for k in TRAITS:
                pick = self.rng.choice((parent, mate)).traits
                if k in pick:
                    traits[k] = pick[k]
            vt, vs = self.inherit_vetoes([parent, mate])
            ly, ls = self.inherit_layers([parent, mate], parent.name)
            child = self._new(parent.name, self.crossover(parent.name, parent.params, mate.params),
                              self.rng.choice((parent.tf, mate.tf)), self.mutate_risk(risk), self.mutate_traits(traits), vt, ly)
            child.veto_stats, child.layer_stats = vs, ls
            self._register(child, [parent, mate], "bred")
            note = f"Bred {child.label} from two winners"
        else:
            scale = 0.35 if not self.active else 0.15 if len(self.active) >= 3 else 0.25  # bolder when nothing works
            vt, vs = self.inherit_vetoes([parent])
            ly, ls = self.inherit_layers([parent], parent.name)
            child = self._new(parent.name, self.elder_nudge(parent.name, self.mutate(parent.name, parent.params, scale)),
                              self.mutate_tf(parent.tf),
                              self.mutate_risk(parent.risk), self.mutate_traits(parent.traits), vt, ly)
            child.veto_stats, child.layer_stats = vs, ls
            self._register(child, [parent], "tweaked")
            note = f"Spawned {child.label} (tweaked from {parent.label})"
        self.replay(child, closes)
        self.vars.append(child)
        self.events.append(note)

    def add_variant(self, name, params, closes=None, size=1.0, note="Added", tf=1, origin="added", risk=None, traits=None,
                    vetoes=None, layers=None):
        """Adds a strategy with the given settings (clamped to sane bounds) and replays recent prices."""
        if name not in STRATS:
            return None
        spec, p = STRATS[name], {}
        for k, dv in spec["params"].items():
            lo, hi = spec["bounds"][k]
            try:
                val = min(max(float(params.get(k, dv)), lo), hi)
            except (TypeError, ValueError):
                val = dv
            p[k] = int(round(val)) if isinstance(dv, int) else round(val, 2)
        fix_params(name, p)
        v = self._new(name, p, tf, risk, traits, vetoes, layers)
        self._register(v, [], origin)
        v.size_mult = min(max(float(size), 0.25), 3.0)
        if closes:
            self.replay(v, closes)
        self.vars.append(v)
        self.events.append(f"{note} {v.label}")
        self._rate()
        return v

    def _rand_params(self, name):
        spec, p = STRATS[name], {}
        for k, dv in spec["params"].items():
            lo, hi = spec["bounds"][k]
            val = self.rng.uniform(lo, hi)
            p[k] = int(round(val)) if isinstance(dv, int) else round(val, 2)
        if "fast" in p and "slow" in p:
            p["fast"], p["slow"] = sorted((p["fast"], p["slow"]))
            if p["fast"] == p["slow"]:
                p["slow"] += 5
        return fix_params(name, p)

    def breed_pair(self, a, b, closes=None):
        """A child of two given bots (same strategy family: mixes settings; different families: takes one
        parent's strategy and mixes the shared habits). Starts as an egg, like every new bot."""
        pa, pb = (a, b) if self.rng.random() < 0.5 else (b, a)
        params = self.crossover(pa.name, pa.params, pb.params) if pa.name == pb.name else self.mutate(pa.name, pa.params, 0.1)
        risk = {k: self.rng.choice((pa.risk[k], pb.risk[k])) for k in RISK_BOUNDS}
        traits = {k: self.rng.choice((pa.traits, pb.traits))[k] for k in TRAITS
                  if k in self.rng.choice((pa.traits, pb.traits))}
        vt, vs = self.inherit_vetoes([pa, pb])
        ly, ls = self.inherit_layers([pa, pb], pa.name)
        child = self._new(pa.name, params, self.rng.choice((pa.tf, pb.tf)), self.mutate_risk(risk), self.mutate_traits(traits), vt, ly)
        child.veto_stats, child.layer_stats = vs, ls
        self._register(child, [pa, pb], "bred from your bots")
        if closes:
            self.replay(child, closes)
        self.vars.append(child)
        if len(self.vars) > self.cap:
            self.cap = len(self.vars)
        self.events.append(f"Bred {child.label} from two of your bots")
        self._rate()
        return child

    def spawn_classic(self, closes=None):
        """Hatches one famous strategy that isn't on the farm yet (silver egg). None if all are already here."""
        have = {v.classic for v in self.vars}
        pool = [c for c in CLASSICS if c["title"] not in have]
        if not pool:
            return None
        cl = self.rng.choice(pool)
        v = self.add_variant(cl["name"], dict(cl["params"]), closes, note=f"Classic strategy hatched: {cl['title']}:",
                             tf=cl.get("tf", 1), origin="classic", risk=cl.get("risk"), traits=cl.get("traits"))
        if v:
            v.classic = cl["title"]
        return v

    def spawn_random(self, closes=None):
        """A brand new strategy with random settings, or now and then a famous one. Makes room by dropping the
        weakest duplicate."""
        name = self.rng.choice(WILDCARD_STRATS)
        p = self._rand_params(name)
        if len(self.vars) >= self.cap:
            cands = [v for v, _ in reversed(self.ranking()) if v not in self.active
                     and sum(1 for x in self.vars if x.name == v.name) > 1]
            if cands:
                self._remove(cands[0], "dropped to make room")
                self.events.append(f"Dropped {cands[0].label}")
            else:
                return None
        if self.o.get("classics", True) and self.rng.random() < float(self.o.get("classic_rate", 0.25)):
            v = self.spawn_classic(closes)
            if v:
                return v
        return self.add_variant(name, p, closes, note="Random new strategy:", tf=self.rng.choice(TIMEFRAMES),
                                origin="random", risk=self.rand_risk(), traits=self.rand_traits(0.35),
                                vetoes=self.rand_vetoes(), layers=self.rand_layers())

    def hall_of_fame_candidates(self, min_win_steps, min_trades):
        """Bots that have earned a place: enough time Winning, enough finished trades, and ahead of
        both zero and just holding over their whole life."""
        out = []
        for v in self.vars:
            if v.inducted or v.win_steps < min_win_steps:
                continue
            lf = self.life(v)
            if (v.wins + v.losses) >= min_trades and lf["ret"] > 0 and (lf["edge"] is None or lf["edge"] > 0):
                out.append(v)
        return out

    def export_lineup(self):
        """Strategies worth keeping (everything not stopped), as plain data for saving."""
        keep = [v for v in self.vars if self.info.get(id(v), {}).get("status") != "benched"] or list(self.vars)
        return [dict(name=v.name, params=dict(v.params), size=v.size_mult, tf=v.tf, risk=dict(v.risk), traits=dict(v.traits))
                for v in keep]

    def family(self):
        """Family-tree records for living and recently removed bots, with live stats for the living."""
        alive = {v.uid: v for v in self.vars}
        out = []
        for uid, rec in self.lineage.items():
            r = dict(rec)
            v = alive.get(uid)
            if v:
                r.update(label=v.label, alive=True, status=self.info.get(id(v), {}).get("status", "warming up"),
                         ret=v.eq[-1] / v.sim.start - 1 if v.eq else None, inducted=v.inducted)
            else:
                r.update(alive=False, status=rec["why"] or "removed")
            out.append(r)
        return out

    def pop_shadow(self):
        s, self.shadow = self.shadow, []
        return s

    def pop_events(self):
        e, self.events = self.events, []
        return e

    # ---- saving and restoring the whole farm, so it carries on where it left off ----
    _VFIELDS = ("name", "params", "tf", "risk", "traits", "size_mult", "uid", "parents", "gen", "origin", "royal",
                "classic", "inducted", "strikes", "born_px", "age", "ntrades", "wins", "losses", "win_steps", "streak",
                "peak", "maxdd", "mood_gain", "mood_n", "live_n", "live_eq0", "hi", "since", "entries", "sold_at",
                "fee_guard", "rt_cost", "vetoes", "veto_stats", "lost_at", "power", "live_high", "layers", "layer_stats",
                "conf_last", "coin_pl", "twin", "island", "entry_flags", "swing_ref", "mut_kinds", "credited",
                "backtests", "own_review")

    def to_state(self):
        """Everything needed to bring this farm back exactly as it is (plain data, JSON-ready)."""
        bots = []
        for v in self.vars:
            d = {k: getattr(v, k) for k in self._VFIELDS}
            d.update(eq=list(v.eq), eq_max=v.eq.maxlen, log=list(v.log), bad=getattr(v, "bad", 0),
                     sim=dict(cash=v.sim.cash, pos=v.sim.pos, cost=v.sim.cost, fees=v.sim.fees, tbars=list(v.sim.tbars),
                              opt=getattr(v.sim, "opt", {})))
            bots.append(d)
        lineage = dict(list(self.lineage.items())[-600:])
        return dict(version=1, n=self.n, serial=self.serial, cap=self.cap, coins=self.coins, start_cash=self.start_cash,
                    elders=self.elders[-40:], champions=self.champions, season=self.season,
                    review=self.review, mut_stats=self.mut_stats, evolves=self.evolves,
                    seasons_log=self.seasons_log[-50:],
                    hold_curve=list(getattr(self, "hold_curve", []))[-(self.W * 10 + 2):], bots=bots,
                    lineage={str(k): v for k, v in lineage.items()})

    def align_coins(self, coins, last=None):
        """Makes the farm trade exactly these coins (a safety net if they ever get out of step with the session).
        Positions in dropped coins are closed at their last price. Returns the new coin list."""
        last = dict(self.last_px, **(last or {}))
        gone = [c for c in self.coins if c not in coins]
        for v in self.vars:
            for c in gone:
                q = v.sim.pos.get(c, 0)
                if q > 0 and last.get(c):
                    v.sim.sell(c, last[c])
                v.sim.pos.pop(c, None)
                v.sim.cost.pop(c, None)
                v.sim.last = None
            if v.born_px:
                v.born_px = {c: x for c, x in v.born_px.items() if c in coins}
        self.coins = list(coins)
        return self.coins

    def restore(self, st):
        """Replaces this farm's bots with a saved farm (from to_state). Returns True on success."""
        if not isinstance(st, dict) or st.get("version") != 1 or set(st.get("coins") or []) != set(self.coins):
            return False
        vars_ = []
        for d in st.get("bots", []):
            try:
                if d["name"] not in STRATS:
                    continue
                v = self._new(d["name"], dict(d["params"]), d.get("tf", 1), d.get("risk"), d.get("traits"), d.get("vetoes"),
                              d.get("layers"))
                for k in self._VFIELDS:
                    if k in d and k not in ("name", "params", "tf", "risk", "traits"):
                        setattr(v, k, d[k])
                v.eq = deque(d.get("eq", []), maxlen=int(d.get("eq_max") or v.eq.maxlen))
                v.log = deque([tuple(x) for x in d.get("log", [])], maxlen=300)
                v.bad = d.get("bad", 0)
                s = d.get("sim") or {}
                v.sim.cash = float(s.get("cash", v.sim.cash))
                v.sim.pos = {c: float(q) for c, q in (s.get("pos") or {}).items()}
                v.sim.cost = {c: float(q) for c, q in (s.get("cost") or {}).items()}
                v.sim.fees = float(s.get("fees", 0))
                v.sim.tbars = deque(s.get("tbars", []))
                if isinstance(v.sim, OptionSim):
                    v.sim.opt = {c: dict(o) for c, o in (s.get("opt") or {}).items()}
                    v.sim.genes = v.traits
                v.vetoes = clean_vetoes(v.vetoes)
                v.veto_stats = {k: list(s) for k, s in (v.veto_stats or {}).items() if k in v.vetoes}
                v.lost_at = dict(v.lost_at or {})
                v.layers = clean_layers(v.layers)
                v.layer_stats = {k: list(s) for k, s in (v.layer_stats or {}).items()}
                v.conf_last = dict(v.conf_last or {})
                v.coin_pl = {c: list(x) for c, x in (v.coin_pl or {}).items()}
                v.entry_flags = {c: list(x) for c, x in (v.entry_flags or {}).items()}
                v.own_review = {k: list(x) for k, x in (v.own_review or {}).items() if k in VETOES}
                v.swing_ref = dict(v.swing_ref or {})
                v.mut_kinds = list(v.mut_kinds or [])
                v.island = int(v.island or 0) % max(1, int(self.o.get("islands", 1) or 1))
                v.mood_gain = dict(v.mood_gain or {})
                v._key = None
                v.mood_n = dict(v.mood_n or {})
                vars_.append(v)
            except (KeyError, TypeError, ValueError):
                continue
        if not vars_:
            return False
        self.vars = vars_
        self.n = int(st.get("n", 0))
        self.serial = max(int(st.get("serial", 0)), max(v.uid for v in vars_))
        self.cap = max(self.cap, len(vars_))
        self.lineage = {int(k): v for k, v in (st.get("lineage") or {}).items()}
        self.elders = list(st.get("elders") or [])
        self.review = {k: list(x) for k, x in (st.get("review") or {}).items()}
        self.mut_stats = {k: list(x) for k, x in (st.get("mut_stats") or {}).items()}
        self.evolves = int(st.get("evolves", 0) or 0)
        self.champions = dict(st.get("champions") or {})
        self.season = st.get("season")
        self.seasons_log = [tuple(x) for x in st.get("seasons_log") or []]
        hc = st.get("hold_curve") or [1.0]
        self.hold_curve = deque(hc, maxlen=self.W * 10 + 2)
        self._rate()
        return True


# ---------------- backtesting ----------------
def simulate(closes, sigfn, start_cash, fee, pct, stop=0.0, take=0.0, warm=WARM, max_coin=None, slip=0.0, trail=0.0,
             extra=None):
    """sigfn(i, prefixes, extra_prefixes) -> {coin: signal}. Returns (equity_curve, trade_count)."""
    coins = list(closes)
    n = min(len(v) for v in closes.values())
    sim = Sim(start_cash, fee, pct, max_coin, slip)
    eq, trades = [start_cash], 0
    high = {}
    for i in range(n):
        pre = {c: View(closes[c], i + 1) for c in coins}
        sigs = sigfn(i, pre, slice_extra(extra, i + 1) if extra else None)
        if i < warm:
            continue
        px = {c: closes[c][i] for c in coins}
        for c in coins:
            q = sim.pos.get(c, 0)
            if q > 0:
                high[c] = max(high.get(c, px[c]), px[c])
                r = px[c] / (sim.cost[c] / q) - 1
                if (stop > 0 and r <= -stop) or (take > 0 and r >= take) or \
                        (trail > 0 and px[c] <= high[c] * (1 - trail)):
                    sim.sell(c, px[c], i)
                    high.pop(c, None)
                    trades += 1
                    continue
            s, m = sigs.get(c), 1.0
            if isinstance(s, tuple):
                s, m = s
            if s == "buy" and sim.buy(c, px[c], i, m):
                high[c] = max(high.get(c, px[c]), px[c])
                trades += 1
            elif s == "sell" and sim.sell(c, px[c], i):
                high.pop(c, None)
                trades += 1
        eq.append(sim.equity(px))
    return eq, trades


def metrics(eq):
    peak, dd = eq[0], 0.0
    for x in eq:
        peak = max(peak, x)
        dd = max(dd, (peak - x) / peak if peak else 0)
    return eq[-1] / eq[0] - 1, dd


def replay_bot(v, closes, extra, start, start_cash, fee, pct, slip=0.0):
    """A frozen copy of bot v trading on its own from bar `start` to the end, exactly as it would in the
    tournament (strategy, pace, own stops and traits). Returns (equity curve, trade count)."""
    coins = list(closes)
    b = Variant(v.name, dict(v.params), make_sim(start_cash, fee, pct, slip=slip), 2, v.tf, dict(v.risk), dict(v.traits),
                dict(v.vetoes), json.loads(json.dumps(v.layers)))
    b.fee_guard, b.rt_cost = v.fee_guard, v.rt_cost
    L = min(len(x) for x in closes.values())
    eq, trades = [start_cash], 0
    for i in range(start, L):
        pre = {c: View(closes[c], i + 1) for c in coins}
        ex = slice_extra(extra, i + 1)
        trades += len(bot_step(b, pre, i, coins, ex))
        eq.append(b.sim.equity({c: closes[c][i] for c in coins}))
    return eq, trades


def _bt_bot(g, coins, start_cash, fee, pct, slip, picky=True):
    """A fresh bot built from genes g (a farm bot or a saved entry), ready to backtest."""
    gg = (lambda k, d=None: g.get(k, d)) if isinstance(g, dict) else (lambda k, d=None: getattr(g, k, d))
    b = Variant(gg("name"), dict(gg("params")), make_sim(start_cash, fee, pct, slip=slip), 2, gg("tf", 1), dict(gg("risk") or {}),
                dict(gg("traits") or {}), dict(gg("vetoes") or {}), json.loads(json.dumps(gg("layers") or {})))
    b.rt_cost = 2 * (fee + slip)
    b.fee_guard = b.rt_cost
    b.picky = picky
    return b


def backtest_bot(g, closes, extra=None, start_cash=1000.0, fee=0.006, pct=0.1, slip=0.0005, segments=4, progress=None,
                 on_trade=None):
    """Full backtest of one bot (its exact genes) on past prices. Returns a dict with:
    ret, hold, edge, maxdd, trades, winrate, sortino, eq (equity curve), hold_eq, marks [(bar, coin, side, price)],
    by_coin {coin: [trades, P/L $]}, by_mood {mood: [decisions, summed gain]}, layer_stats, veto_stats, coin_pl,
    segments [(ret, hold, edge)] (walk-forward: the same bot on each quarter of the history),
    mc_dd95 (shuffled-trade stress: the drawdown you'd see in a bad-luck ordering, 95th percentile),
    fees2x (return with double fees and slippage), review {never-rule: [losing buys it would have stopped, winners]}."""
    coins = list(closes)
    L = min(len(closes[c]) for c in coins)
    start = max(WARM, min(L - 2, max(60, LOOKBACK // 2)))
    b = _bt_bot(g, coins, start_cash, fee, pct, slip)
    eq, marks, rets = [start_cash], [], []
    by_coin, by_mood, review = {}, {}, {}
    mood = "unknown"
    hold_eq = [1.0]
    for i in range(start, L):
        pre = {c: View(closes[c], i + 1) for c in coins}
        if (i - start) % 10 == 0:
            ms = [market_mood(pre[c])[0] for c in coins]
            known = [m for m in ms if m != "unknown"]
            mood = max(set(known), key=known.count) if known else "unknown"
        for c, t in bot_step(b, pre, i, coins, slice_extra(extra, i + 1) if extra else None):
            marks.append((i, c, t["side"], closes[c][i]))
            if on_trade:
                tt = ((extra or {}).get(c) or {}).get("t")
                on_trade(c, t, tt[i] if tt and i < len(tt) else None)
            bc = by_coin.setdefault(c, [0, 0.0])
            bc[0] += 1
            if t["side"] == "sell" and t.get("pl") is not None:
                bc[1] += t["pl"]
                paid = t["usd"] - t["pl"]
                rets.append(t["pl"] / paid if paid > 0 else 0.0)
                for k in t.get("flags", []):
                    review.setdefault(k, [0, 0])[0 if t["pl"] <= 0 else 1] += 1
        e = b.sim.equity({c: closes[c][i] for c in coins})
        if mood != "unknown":
            bm = by_mood.setdefault(mood, [0, 0.0])
            bm[0] += 1
            bm[1] += e / eq[-1] - 1 if eq[-1] else 0
        eq.append(e)
        hold_eq.append(hold_eq[-1] * sum(closes[c][i] / closes[c][i - 1] for c in coins) / len(coins))
        if progress and (i - start) % 200 == 0:
            progress(i - start, L - start)
    ret, dd = metrics(eq)
    hold = hold_eq[-1] - 1
    steps = [eq[k] / eq[k - 1] - 1 for k in range(1, len(eq)) if eq[k - 1] > 0]
    mean = sum(steps) / len(steps) if steps else 0
    down = (sum(min(r, 0) ** 2 for r in steps) / len(steps)) ** 0.5 if steps else 0
    sortino = (mean / down * len(steps) ** 0.5 / 3) if down > 1e-12 else (5.0 if mean > 0 else 0.0)
    segs = []
    n = len(eq) - 1
    for k in range(segments):  # walk-forward: does it hold up in every part of the history?
        a, z = start + k * n // segments, start + (k + 1) * n // segments
        if z - a < 30:
            continue
        sub = backtest_simple(g, closes, extra, a, z, start_cash, fee, pct, slip)
        hr = sum(closes[c][z - 1] / closes[c][a - 1] for c in coins) / len(coins) - 1
        segs.append((sub, hr, sub - hr))
    rng = random.Random(7)
    dds = []
    if len(rets) >= 5:  # shuffled-trade stress: same trades, random order
        for _ in range(200):
            r = rets[:]
            rng.shuffle(r)
            x, pk, md = 1.0, 1.0, 0.0
            for q in r:
                x *= 1 + q * pct
                pk = max(pk, x)
                md = max(md, (pk - x) / pk)
            dds.append(md)
        dds.sort()
    f2 = backtest_simple(g, closes, extra, start, L, start_cash, fee * 2, pct, slip * 2)
    wins = sum(1 for r in rets if r > 0)
    return dict(
        ret=ret, hold=hold, edge=ret - hold, maxdd=dd, trades=len(marks), winrate=wins / len(rets) if rets else None,
        closed=len(rets), sortino=sortino, eq=eq, hold_eq=[x * start_cash for x in hold_eq], marks=marks, start=start,
        by_coin=by_coin, by_mood=by_mood, layer_stats={k: list(v) for k, v in b.layer_stats.items()},
        veto_stats={k: list(v) for k, v in b.veto_stats.items()}, coin_pl={k: list(v) for k, v in b.coin_pl.items()},
        segments=segs, mc_dd95=dds[int(len(dds) * 0.95)] if dds else None, fees2x=f2, review=review,
        bars=L - start, fees=b.sim.fees)


def backtest_simple(g, closes, extra, a, z, start_cash, fee, pct, slip):
    """Return of bot genes g traded from bar a to bar z (exclusive)."""
    coins = list(closes)
    b = _bt_bot(g, coins, start_cash, fee, pct, slip)
    for i in range(a, z):
        bot_step(b, {c: View(closes[c], i + 1) for c in coins}, i, coins, slice_extra(extra, i + 1) if extra else None)
    return b.sim.equity({c: closes[c][z - 1] for c in coins}) / start_cash - 1


def backtest_summary(r):
    """Small record of a backtest, kept with the bot (its memory) and in its saved file."""
    return dict(date=datetime.now().strftime("%Y-%m-%d %H:%M"), bars=r["bars"], ret=round(r["ret"] * 100, 2),
                edge=round(r["edge"] * 100, 2), maxdd=round(r["maxdd"] * 100, 2), trades=r["trades"],
                winrate=None if r["winrate"] is None else round(r["winrate"] * 100, 1),
                segments_passed=sum(1 for s in r["segments"] if s[2] > 0), segments=len(r["segments"]),
                fees2x=round(r["fees2x"] * 100, 2), mc_dd95=None if r["mc_dd95"] is None else round(r["mc_dd95"] * 100, 2))


def _merge_stats(dst, src):
    for k, x in (src or {}).items():
        d = dst.setdefault(k, [0.0, 0.0])
        d[0] += x[0]
        d[1] += x[1]


def remember_backtest(target, r, tourn=None):
    """Saves what a backtest learned into a bot's memory: how each of its studies and never-rules did (they then
    breed on with that evidence), which coins it does badly on, how it does in each market mood, and a record of
    the test. target is a farm bot (Variant) or a saved bot entry (dict). With tourn, the farm learns too: the
    post-trade review gets the losing buys, and a bot that beat holding becomes an elder and a season candidate."""
    rec = backtest_summary(r)
    if isinstance(target, dict):
        target.setdefault("backtests", []).append(rec)
        del target["backtests"][:-10]
        ls, vs = target.setdefault("layer_stats", {}), target.setdefault("veto_stats", {})
        _merge_stats(ls, r["layer_stats"])
        _merge_stats(vs, r["veto_stats"])
    else:
        target.backtests = (getattr(target, "backtests", None) or [])[-9:] + [rec]
        _merge_stats(target.layer_stats, r["layer_stats"])
        _merge_stats(target.veto_stats, {k: x for k, x in r["veto_stats"].items() if k in target.vetoes})
        for c, x in r["coin_pl"].items():
            cp = target.coin_pl.setdefault(c, [0, 0.0])
            cp[0] = min(20, cp[0] + x[0])
            cp[1] = cp[1] * 0.5 + x[1] * 0.5
        for m, (k, gsum) in r["by_mood"].items():
            target.mood_n[m] = target.mood_n.get(m, 0) + k
            target.mood_gain[m] = target.mood_gain.get(m, 0.0) + gsum
    if tourn is not None:
        for k, x in r.get("review", {}).items():
            d = tourn.review.setdefault(k, [0, 0])
            d[0] += x[0]
            d[1] += x[1]
        gg = target if isinstance(target, dict) else dict(name=target.name, params=target.params, tf=target.tf)
        if r["edge"] > 0 and r["trades"] >= 4 and gg["name"] in STRATS:
            tourn.elders.append(dict(name=gg["name"], params=dict(gg["params"]), tf=gg.get("tf", 1), edge=r["edge"]))
            del tourn.elders[:-40]
    return rec


class TrainingStopped(Exception):
    pass


def _genes(v):
    return dict(name=v.name, params=dict(v.params), tf=v.tf, risk=dict(v.risk), traits=dict(v.traits),
                vetoes=dict(v.vetoes), layers=json.loads(json.dumps(v.layers)))


def _fresh_money(t):
    """Training passes: every bot keeps its genes and what it learned (rule evidence, coin and mood records),
    but starts the next pass with fresh money and a fresh scoreboard."""
    for v in t.vars:
        v.sim = make_sim(t.start_cash, t.fee, t.pct, slip=t.o.get("slip", 0.0), genes=v.traits)
        v.eq.clear()
        v.hi, v.since, v.entries, v.sold_at, v.run_sig, v.sig = {}, {}, {}, {}, {}, {}
        v.veto_wait, v.lost_at, v.entry_flags, v.conf_last = [], {}, {}, {}
        v.log.clear()
        v.born_px = None
        v.age = v.ntrades = v.wins = v.losses = v.win_steps = v.streak = 0
        v.peak, v.maxdd, v.strikes, v.live_n, v.live_eq0 = 0.0, 0.0, 0, 0, None
        v.inducted = False
    t.hold_curve = deque([1.0], maxlen=t.W * 10 + 2)
    t.info, t.active, t.slowed = {}, [], []


def train_farm(closes, extra, opts, cap=40, passes=2, exam_frac=0.25, seed_genes=None, start_cash=1000.0, fee=0.006,
               pct=0.1, evolve=24, params=None, retire_steps=0, progress=None, stop=None, seed=None, on_trade=None):
    """Training camp: a whole farm lives through a stretch of history, `passes` times over, breeding and learning as it
    goes (bots keep their genes and lessons between passes, with fresh money each time). The last exam_frac of the
    history is held back: afterwards the best bots are frozen and sent through it as a final exam on prices they never
    saw. Returns dict(tourn, results=[...best first], train_bars, exam_bars, passes_done).
    progress(done, total, text) is called now and then; stop() returning True ends it early (TrainingStopped)."""
    coins = list(closes)
    L = min(len(closes[c]) for c in coins)
    cut = int(L * (1 - exam_frac)) if exam_frac > 0 else L
    if cut - WARM < 100:
        raise ValueError("not enough history: pick a longer stretch or smaller candles")
    train = {c: closes[c][:cut] for c in coins}
    tx = {c: {k: x[:cut] for k, x in extra[c].items()} for c in coins} if extra else None
    if extra and extra.get(CTX_KEY):
        tx[CTX_KEY] = {k: x[:cut] for k, x in extra[CTX_KEY].items()}
    t = Tournament(coins, start_cash, fee, pct, evolve, params=params, opts=opts, cap=cap, retire_steps=retire_steps,
                   rng=random.Random(seed))
    t.on_trade = on_trade
    for g in seed_genes or []:
        if g.get("name") in STRATS:
            t.add_variant(g["name"], g.get("params") or {}, None, g.get("size", 1.0), note="Training seed:", tf=g.get("tf", 1),
                          origin="seeded", risk=g.get("risk"), traits=g.get("traits"), vetoes=g.get("vetoes"), layers=g.get("layers"))
    while len(t.vars) > max(cap, len(seed_genes or [])):
        drop = next((v for v in t.vars if v.origin != "seeded"), None)
        if drop is None:
            break
        t._remove(drop, "made room for your bots")
    total = passes * (cut - WARM)
    done = 0
    for p_ in range(passes):
        if p_:
            _fresh_money(t)
        for i in range(WARM, cut):
            t.step({c: View(train[c], i + 1) for c in coins}, slice_extra(tx, i + 1))
            done += 1
            if done % 100 == 0:
                if stop and stop():
                    raise TrainingStopped()
                if progress:
                    best = t.active[0] if t.active else None
                    progress(done, total, f"pass {p_ + 1} of {passes}, generation {max((v.gen for v in t.vars), default=0)}, "
                                          f"{len(t.vars)} bots" + (f", leading: {best.name}" if best else ""))
    def rank_key(v):  # bots that actually traded first, then by how far they beat holding
        lf = t.life(v)
        return (lf["trades"] < 3, -(lf["edge"] if lf["edge"] is not None else lf["ret"]))
    ranked = sorted(t.vars, key=rank_key)
    results = []
    exam_hold = (sum(closes[c][L - 1] / closes[c][cut - 1] for c in coins) / len(coins) - 1) if cut < L else None
    seen, picked = set(), []
    for v in ranked:  # identical twins count once
        if v.key() not in seen:
            seen.add(v.key())
            picked.append(v)
    for v in picked[:max(12, cap // 3)]:
        lf = t.life(v)
        r = dict(v=v, genes=_genes(v), train_ret=lf["ret"], train_edge=lf["edge"], trades=lf["trades"], winrate=lf["winrate"],
                 exam_ret=None, exam_edge=None, passed=None, layer_stats={k: list(x) for k, x in v.layer_stats.items()},
                 veto_stats={k: list(x) for k, x in v.veto_stats.items()})
        if cut < L:
            er = backtest_simple(r["genes"], closes, extra, cut, L, start_cash, fee, pct, t.o.get("slip", 0.0))
            r.update(exam_ret=er, exam_edge=er - exam_hold,
                     passed=er - exam_hold > 0 and (lf["edge"] or 0) > 0 and lf["trades"] >= 3)
        results.append(r)
        if stop and stop():
            break
    results.sort(key=lambda r: (not r["passed"], -(r["exam_edge"] if r["exam_edge"] is not None else r["train_edge"] or 0)))
    return dict(tourn=t, results=results, train_bars=cut, exam_bars=L - cut, passes_done=passes, exam_hold=exam_hold)


def teach_from(dst, src):
    """Passes a trained farm's memory to another farm: elders, post-trade review, mutation memory and season champions."""
    dst.elders = (dst.elders + [e for e in src.elders])[-40:]
    for k, x in src.review.items():
        d = dst.review.setdefault(k, [0, 0])
        d[0] += x[0]
        d[1] += x[1]
    for k, x in src.mut_stats.items():
        d = dst.mut_stats.setdefault(k, [0, 0])
        d[0] += x[0]
        d[1] += x[1]
    for m, ch in src.champions.items():
        if ch.get("fit", 0) > dst.champions.get(m, {}).get("fit", 0):
            dst.champions[m] = dict(ch, uid=-1)  # not on this farm: woken up from its genes when its season comes


def _warm_island(args):
    """One island's warmup in its own process (multi-core). Returns its farm as plain data."""
    (coins, start_cash, fee, pct, evolve, params, opts, cap, retire_steps, hist, hx, seed, island) = args
    t = Tournament(coins, start_cash, fee, pct, evolve, params=params, opts=dict(opts, islands=1), cap=cap,
                   retire_steps=retire_steps, rng=random.Random(seed))
    t.warmup(hist, extra=hx)
    st = t.to_state()
    for b in st["bots"]:
        b["island"] = island
    return st


def warm_islands(coins, start_cash, fee, pct, evolve, params, opts, cap, retire_steps, hist, hx, workers=None, log=None):
    """Multi-core warmup: each island learns on its own processor core, then the islands join into one farm (they
    keep their island and only swap champions from then on). Falls back to one core if anything goes wrong."""
    k = max(1, int(opts.get("islands", 1) or 1))
    cpus = os.cpu_count() or 1
    if k < 2 or cpus < 2:
        return None
    per = max(6, -(-cap // k))
    jobs = [(coins, start_cash, fee, pct, evolve, params, opts, per, retire_steps, hist, hx, 1000 + i, i) for i in range(k)]
    try:
        import concurrent.futures as cf
        import multiprocessing as mp
        # "spawn" everywhere: forking a busy app (with threads running) can leave the helpers stuck on Linux
        ctx = mp.get_context("spawn")
        ex = cf.ProcessPoolExecutor(max_workers=min(k, workers or cpus), mp_context=ctx)
        try:
            states = list(ex.map(_warm_island, jobs, timeout=900))
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    except Exception as e:  # e.g. a locked-down computer: warm up on one core instead
        if log:
            log(f"Multi-core warmup unavailable ({e}); using one core.")
        return None
    t = Tournament(coins, start_cash, fee, pct, evolve, params=params, opts=opts, cap=cap, retire_steps=retire_steps)
    merged = dict(states[0])
    bots, lineage, off = [], {}, 0
    for st in states:
        top = max([b["uid"] for b in st["bots"]] + [int(u) for u in st.get("lineage", {})] + [0])
        for b in st["bots"]:
            b = dict(b, uid=b["uid"] + off, parents=[p + off for p in b.get("parents", [])])
            bots.append(b)
        for u, rec in st.get("lineage", {}).items():
            lineage[str(int(u) + off)] = dict(rec, uid=int(u) + off, parents=[p + off for p in rec.get("parents", [])])
        off += top
    merged.update(bots=bots, lineage=lineage, serial=off, n=max(st["n"] for st in states),
                  elders=[e for st in states for e in st.get("elders", [])][-40:])
    rv, ms = {}, {}
    for st in states:
        _merge_stats(rv, st.get("review"))
        _merge_stats(ms, st.get("mut_stats"))
        for m, ch in (st.get("champions") or {}).items():
            if ch["fit"] > merged.get("champions", {}).get(m, {}).get("fit", -1):
                merged.setdefault("champions", {})[m] = ch
    merged.update(review=rv, mut_stats=ms)
    if not t.restore(merged):
        return None
    t.cap = cap
    while len(t.vars) > cap:
        worst = [v for v, _ in reversed(t.ranking()) if v not in t.active] or \
            [v for v in t.vars if t.info.get(id(v), {}).get("status") == "warming up"]
        if not worst:
            break
        t._remove(worst[0], "farm made smaller")
    t._rate()
    return t


def slice_extra(extra, i):
    """The extra data (highs/lows/volumes) cut to the first i bars (as views, nothing is copied)."""
    if not extra:
        return None
    return {c: {k: View(v, i) for k, v in d.items()} for c, d in extra.items() if d}


# ---------------- Bot Lab: evolve on old prices, test on newer unseen prices ----------------
# ---------------- popular tickers ----------------
POPULAR = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "PLTR",
           "COIN", "MSTR", "SMCI", "AVGO", "BA", "JPM", "BAC", "XOM", "INTC", "UBER", "SOFI", "RIVN", "GME", "SNOW",
           "SHOP", "DIS", "NIO", "F", "GLD", "SLV", "TLT", "XLF", "XLE", "ARKK", "SOXL", "TQQQ"]


def list_products(quote="USD", symbols=None):
    """[{coin, price, change_24h, volume_usd}] for popular optionable tickers (or the ones given), busiest first."""
    syms = list(symbols or POPULAR)
    out = []
    for k in range(0, len(syms), 100):
        q = urllib.parse.quote(",".join(syms[k:k + 100]))
        d = alp("GET", f"{DATA_URL}/v2/stocks/snapshots?symbols={q}&feed={FEED}")
        for sym, sn in (d or {}).items():
            try:
                px = float((sn.get("latestTrade") or {}).get("p") or (sn.get("dailyBar") or {}).get("c") or 0)
                prev = float((sn.get("prevDailyBar") or {}).get("c") or 0)
                vol = float((sn.get("dailyBar") or {}).get("v") or 0)
                out.append(dict(coin=sym, price=px, change_24h=(px / prev - 1) * 100 if prev else None, volume_usd=vol * px))
            except (TypeError, ValueError, AttributeError):
                continue
    return sorted(out, key=lambda r: -(r["volume_usd"] or 0))


STABLES = {"USDC", "USDT", "DAI", "PYUSD", "EURC", "GUSD", "USDS", "PAX", "TUSD", "FDUSD", "RLUSD"}


def scout_coins(products, n, min_volume=5_000_000):
    """The bot's own coin pick: liquid coins (enough daily volume to trade without big spreads)
    that are actually moving, skipping stablecoins. Ranked by volume x size of the 24h move."""
    pool = [d for d in products if d["coin"] not in STABLES and (d["volume_usd"] or 0) >= min_volume
            and d["change_24h"] is not None]
    pool.sort(key=lambda d: -((d["volume_usd"] or 0) ** 0.5 * (0.5 + min(abs(d["change_24h"]), 20))))
    return [d["coin"] for d in pool[:n]]


# ---------------- alerts (Discord / Telegram) ----------------
def send_alert(settings, text):
    """Posts a short message to a Discord webhook and/or a Telegram chat. Returns a list of problems."""
    problems = []
    hook = (settings.get("alert_discord") or "").strip()
    if hook:
        if not re.match(r"^https://(discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)/api/webhooks/", hook):
            problems.append("Discord: that is not a Discord webhook link.")
        else:
            try:
                req = urllib.request.Request(hook, data=json.dumps({"content": text[:1900]}).encode(),
                                             headers={"Content-Type": "application/json", "User-Agent": "cbbf"})
                urllib.request.urlopen(req, timeout=10).read()
            except Exception as ex:
                problems.append(f"Discord: {ex}")
    tok, chat = (settings.get("alert_tg_token") or "").strip(), (settings.get("alert_tg_chat") or "").strip()
    if tok and chat:
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", tok):
            problems.append("Telegram: the bot token doesn't look right (it looks like 123456:ABC...).")
        else:
            try:
                body = urllib.parse.urlencode({"chat_id": chat, "text": text[:3500]}).encode()
                req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                             headers={"User-Agent": "cbbf"})
                urllib.request.urlopen(req, timeout=10).read()
            except Exception as ex:
                problems.append(f"Telegram: {ex}")
    return problems


def tg_updates(token, offset=None, timeout=20):
    """New Telegram messages to your bot: ([(chat id, text, sent at, private chat?, sender id)], next offset)."""
    url = f"https://api.telegram.org/bot{token.strip()}/getUpdates?timeout={int(timeout)}" + (f"&offset={offset}" if offset else "")
    data = json.loads(http_get(url, timeout + 10))
    out, nxt = [], offset
    for u in data.get("result", []):
        nxt = u["update_id"] + 1
        m = u.get("message") or {}
        if m.get("text"):
            ch = m.get("chat") or {}
            out.append((ch.get("id"), m["text"], float(m.get("date") or 0), ch.get("type") == "private",
                        (m.get("from") or {}).get("id")))
    return out, nxt


def alerts_configured(settings):
    return bool((settings.get("alert_discord") or "").strip()
                or ((settings.get("alert_tg_token") or "").strip() and (settings.get("alert_tg_chat") or "").strip()))

# ---------------- keep the computer awake while the bot runs ----------------
class AwakeLock:
    """Asks the operating system not to go to sleep while the bot is running (the screen may still
    turn off). A sleeping computer stops the bot and cuts its internet connection, which looks like
    the app 'disconnecting' after the idle timer runs out. Closing a laptop lid can still sleep it."""

    def __init__(self):
        self.proc, self.held = None, False

    def on(self):
        if self.held:
            return
        try:
            if sys.platform.startswith("win"):
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # CONTINUOUS | SYSTEM_REQUIRED
            elif sys.platform == "darwin" and shutil.which("caffeinate"):
                self.proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            elif shutil.which("systemd-inhibit"):
                self.proc = subprocess.Popen(["systemd-inhibit", "--what=sleep:idle", "--who=CBBF",
                                              "--why=Trading bot is running", "--mode=block", "sleep", "infinity"])
            else:
                return
            self.held = True
        except Exception:
            self.proc, self.held = None, False

    def off(self):
        if not self.held:
            return
        try:
            if sys.platform.startswith("win"):
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            elif self.proc:
                self.proc.terminate()
        except Exception:
            pass
        self.proc, self.held = None, False


# ---------------- storage ----------------
def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


DISK_WRITES = {}  # what OBF has written since it started: kind -> [times, bytes]
DISK_T0 = time.time()


def note_write(path, nbytes):
    base = os.path.basename(path)
    kind = ("Farm saves" if base.startswith("farm-") else "Session saves" if base.startswith("state-") else
            "Price history" if os.sep + "history" + os.sep in path or os.sep + "cache" + os.sep in path else
            "Slow farm" if "slow" in base else "Settings and other")
    w = DISK_WRITES.setdefault(kind, [0, 0])
    w[0] += 1
    w[1] += nbytes


def save_json(path, obj):
    if os.path.basename(path) == "config.json":
        obj = scrub_config(obj)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
        n = f.tell()
    os.replace(tmp, path)
    note_write(path, n)


def state_path(live):
    return os.path.join(HOME_DIR, f"state-{'live' if live else 'paper'}.json")


def farm_path(live):
    return os.path.join(HOME_DIR, f"farm-{'live' if live else 'paper'}.json")


def strategies_path():
    return os.path.join(HOME_DIR, "saved-strategies.json")


def save_strategies(lineup):
    save_json(strategies_path(), lineup)


def load_strategies():
    data = load_json(strategies_path(), [])
    if not isinstance(data, list):
        return []
    return [dict(d, risk=clean_risk(d.get("risk") if isinstance(d.get("risk"), dict) else None),
                 traits=clean_traits(d.get("traits") if isinstance(d.get("traits"), dict) else None))
            for d in data if isinstance(d, dict) and d.get("name") in STRATS and isinstance(d.get("params"), dict)]


# ---------------- sharing bots (export / import) ----------------
BOT_FORMAT = "obf-bots"
BOT_FORMATS = ("obf-bots", "cbbf-bots")  # dragons from the crypto farm can be imported too
BOT_FORMAT_VERSION = 1
MAX_BOT_FILE = 1024 * 1024  # bytes; a bot file is tiny, anything bigger is not one


STRAT_DOCS = {  # plain-English rules for every strategy, for people and other programs reading a bot file
    "SMA crossover": ("Simple moving averages of the close over `fast` and `slow` bars.",
                      "Buy when the fast average crosses above the slow one; sell when it crosses below."),
    "EMA crossover": ("Exponential moving averages over `fast` and `slow` bars.",
                      "Buy when the fast EMA crosses above the slow EMA by at least `min_gap` %; sell on the opposite cross."),
    "MACD": ("MACD line = EMA(`fast`) - EMA(`slow`); signal line = EMA(`signal`) of the MACD line.",
             "Buy when MACD crosses above its signal line; sell when it crosses below."),
    "Momentum": ("Change in % over the last `n` bars.", "Buy when it is above +`thr` %; sell when below -`thr` %."),
    "RSI": ("Relative Strength Index over `period` bars (0-100).", "Buy when RSI < `lo`; sell when RSI > `hi`."),
    "Stochastic": ("Where the close sits in its `n`-bar high-low range of closes (0-100).",
                   "Buy when it rises back above `lo`; sell when it falls back below `hi`."),
    "Bollinger bands": ("`n`-bar average +/- `k` standard deviations.", "Buy below the lower band; sell above the upper band."),
    "Mean reversion": ("% distance of the close from its `n`-bar average.", "Buy when below -`thr` %; sell when above +`thr` %."),
    "VWAP snap-back": ("Volume-weighted average price over `n` bars (typical price = (high+low+close)/3).",
                       "Buy when the close is `thr` % below VWAP; sell when `thr` % above."),
    "Breakout": ("Highest and lowest close of the previous `n` bars.", "Buy above the high; sell below the low."),
    "Volume breakout": ("Highest high / lowest low of the previous `n` bars, and average volume.",
                        "Buy above the high when volume >= `vmult` x average; sell below the low."),
    "ATR channel": ("EMA(`n`) of the close +/- `m` x ATR(`n`) (average true range from highs and lows).",
                    "Buy above the upper line; sell below the lower line."),
    "Supertrend": ("Band at (high+low)/2 -/+ `m` x ATR(`n`) that trails the price and flips with the trend.",
                   "Buy when the trend flips up; sell when it flips down."),
    "Ichimoku cross": ("Midlines (highest high + lowest low)/2 over `fast` and `slow` bars.",
                       "Buy when the fast midline crosses above the slow one with the close above it; sell on the opposite cross."),
    "Rate of change": ("ROC = % change over `n` bars, and its `smooth`-bar average.",
                       "Buy when ROC crosses above its average while positive; sell when it crosses below while negative."),
    "MA ribbon": ("EMAs over `fast`, `mid` and `slow` bars.",
                  "Buy when they line up fast > mid > slow; sell when the fast EMA drops below the mid EMA."),
    "Trend + dip": ("SMA over `trend` bars and RSI over `period` bars.",
                    "Buy when the close is above the SMA and RSI < `lo`; sell when RSI > `hi` or the close drops below the SMA."),
    "Dollar-cost averaging": ("A counter of decisions.", "Buy every `every` decisions; never sells by itself."),
    # the scalp breed (always with a tight stop and target, a time limit, and flat before the 4 pm close)
    "Micro pullback": ("EMA(`n`) of the close, the last `pull` bars, and the previous bar's high and low.",
                       "Buy when the EMA is rising, the last `pull` closes eased back without breaking the EMA, and the "
                       "close tops the previous bar's high; sell (put) on the mirror image."),
    "Volume burst": ("This bar's volume vs the `n`-bar average, its % move, and where it closed in its own range.",
                     "Buy when volume >= `vmult` x average, the bar rose >= `thr` % and closed in its top 30%; sell on the "
                     "mirror image."),
    "VWAP reclaim": ("Volume-weighted average price over `n` bars, and this bar's volume vs average.",
                     "Buy when the close crosses up through VWAP on volume >= `vmin` x average; sell on a cross down."),
    "Range scalp": ("Highest high / lowest low of the previous `n` bars (a box at most `maxw` % tall).",
                    "Inside a tight box only: buy a tick up within `edge` of the bottom; sell a tick down within `edge` of the top."),
    "Quick flip": ("The last `run` closes.", "Buy when all `run` closes rose and add up to >= `thr` %; sell when all fell."),
}


def describe_bot(b, bar_minutes=None):
    """Plain-English rules for one bot-file entry: what it reads, when it buys and sells, its pace, exits and habits."""
    calc, rule = STRAT_DOCS.get(b["name"], ("", ""))
    for k, v in b.get("params", {}).items():
        calc, rule = calc.replace(f"`{k}`", f"{v:g}"), rule.replace(f"`{k}`", f"{v:g}")
    pace = (f"every {fmt_bar(b.get('tf', 1) * bar_minutes)}" if bar_minutes
            else f"every {b.get('tf', 1)} bar(s) of your chosen bar length")
    exits = risk_text(b.get("risk"))
    habits = traits_text(b.get("traits"))
    nevers = vetoes_text(b.get("vetoes"))
    return (f"{b['name']}: {calc} {rule} It decides {pace}, on candles of that length."
            + (f" Own exits: {exits}." if exits else "") + (f" Habits: {habits}." if habits else "")
            + (f" Never-rules: it {nevers}." if nevers else "")
            + (f" Rule layers: {layers_text(b.get('layers') or {})}." if b.get("layers") else "")
            + " Each buy spends a fixed share of the starting money times its trade size; a sell closes the whole position.")


SCHEMA_NOTE = (
    "CBBF bot file. Each item in `bots` is one trading bot. `name` is the strategy family (see `rules` for what it does), "
    "`params` its numbers, `tf` its pace in bars (multiply by `lifetime.bar_minutes` for minutes), `risk.sl` / `risk.tp` "
    "its own stop-loss / take-profit in % (0 = none), `traits` extra habits (trail = trailing stop %, minhold / maxhold = "
    "decisions, cool = decisions to wait after selling, trend = only buy above that many-bar average, minvol = minimum "
    "average move % per bar, rsicap = no buying above that RSI, confirm = signals in a row needed, entries = most buys "
    "per position, exit = 1 sells only through its own exits, moods = bitmask of allowed markets: 1 trending up, "
    "2 trending down, 4 choppy, 8 quiet), `vetoes` its never-rules (knife = no buying after that % drop over 10 "
    "decisions, spike = no buying after a one-bar jump of that %, chase = no buying that % above the 20-decision "
    "average, revenge = no re-buying a coin within that many decisions of a loss on it, thin = no buying under that "
    "x normal volume, mktdown = no buying while SPY is down that % over 10 decisions, panic = no strategy selling "
    "after a one-bar drop of that %), `layers` extra rule layers (plus = extra positive studies: each study's most recent "
    "signal is its vote, the main strategy is always one of them, and the bot buys when the number of positive studies "
    "voting buy minus the number of `minus` (negative) studies whose latest signal is sell is at least `need`; a buy "
    "is attempted when the main strategy or any positive study signals buy; exits = exit studies, any of which "
    "signalling sell closes the position instead of the main strategy's own sells; size.target = trade size scaled so "
    "target / average % move per decision, between 0.5x and 1.5x), `size` its trade-size multiplier. `stats` and `lifetime` are its results, "
    "after fees. Signals use bar closes (some families also highs, lows and volume). Results were simulated with fees "
    "and spread; past results do not predict future ones.")


def export_bots(rows, app_version="", note=""):
    """rows: tournament.board() entries to share. Returns plain data (strategy name, settings,
    trade size, and how it was doing) so someone else can load it and see how it behaves on
    their own prices. No keys, balances or trade history are included."""
    bots = []
    for r in rows:
        if r.get("stats") and "score" not in r:  # already a bot-file entry (Hall of Fame, Bot Lab)
            b = dict(name=r["name"], params=dict(r["params"]), size=round(float(r.get("size", 1.0)), 2),
                     tf=int(r.get("tf", 1)), risk=clean_risk(r.get("risk")), traits=clean_traits(r.get("traits")),
                     vetoes=clean_vetoes(r.get("vetoes")), layers=clean_layers(r.get("layers")), stats=dict(r["stats"]),
                     notes=r.get("notes", note))
            if r.get("lifetime"):
                b["lifetime"] = dict(r["lifetime"])
            for k in MEMORY_FIELDS:
                if r.get(k) is not None:
                    b[k] = json.loads(json.dumps(r[k]))
            bots.append(b)
            continue
        b = dict(
            name=r["name"], params=dict(r["params"]), size=round(float(r.get("size", 1.0)), 2), tf=int(r.get("tf", 1)),
            risk=clean_risk(r.get("risk")), traits=clean_traits(r.get("traits")), vetoes=clean_vetoes(r.get("vetoes")),
            layers=clean_layers(r.get("layers")), stats=dict(recent_gain_pct=None if r.get("score") is None else round(r["score"] * 100, 2),
                       consistency_pct=None if r.get("cons") is None else int(r["cons"] * 100),
                       trades=int(r.get("trades", 0)), status=r.get("status", "")),
            notes=note)
        lf = r.get("life")
        if lf:
            b["lifetime"] = lifetime_record(lf, r.get("bar_minutes"))
        if r.get("twin") is not None:
            b["twin_test_pct"] = round(r["twin"] * 100, 2)
        v = r.get("v")
        if v is not None and getattr(v, "backtests", None):
            b["backtests"] = json.loads(json.dumps(v.backtests))
        if r.get("layer_stats"):
            b["layer_stats"] = {k: [round(x, 3) for x in st] for k, st in r["layer_stats"].items()}
        if r.get("veto_stats"):
            b["veto_stats"] = {k: [round(x, 3) for x in st] for k, st in r["veto_stats"].items()}
        bots.append(b)
    for b in bots:
        b["rules"] = describe_bot(b, (b.get("lifetime") or {}).get("bar_minutes"))
    return dict(format=BOT_FORMAT, version=BOT_FORMAT_VERSION, app_version=app_version,
                exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), how_to_read=SCHEMA_NOTE,
                strategies={n: dict(calculation=c, rules=r, settings=list(STRATS[n]["params"]))
                            for n, (c, r) in STRAT_DOCS.items() if n in {b["name"] for b in bots}},
                bots=bots)


def lifetime_record(lf, bar_minutes=None):
    """Plain-number lifetime stats for a bot file."""
    def pct(x):
        return None if x is None else round(x * 100, 2)
    out = dict(return_pct=pct(lf.get("ret")), vs_holding_pct=pct(lf.get("edge")), win_rate_pct=pct(lf.get("winrate")),
               wins=lf.get("wins", 0), losses=lf.get("losses", 0), trades=lf.get("trades", 0),
               worst_drop_pct=pct(lf.get("maxdd")), decisions_alive=lf.get("age", 0),
               decisions_winning=lf.get("win_steps", 0), best_market=lf.get("best_mood"),
               fees_paid=round(float(lf.get("fees") or 0), 2))
    if bar_minutes:
        out["bar_minutes"] = bar_minutes
        out["hours_winning"] = round(lf.get("win_steps", 0) * float(bar_minutes) / 60, 2)
    return out


# ---------------- Bot Collection (catch bots, give them names, rarities and levels, pick a team) ----------------
MEMORY_FIELDS = ("twin_test_pct", "backtests", "retest", "layer_stats", "veto_stats")  # what a saved bot remembers
COLLECT_FIELDS = ("nickname", "rarity", "level", "xp", "caught_at", "source", "team", "shiny")
TEAM_MAX = 6
RARITIES = ("Common", "Uncommon", "Rare", "Epic", "Legendary")
RARITY_COLORS = {"Common": "#9ca3af", "Uncommon": "#22c55e", "Rare": "#3b82f6", "Epic": "#a855f7", "Legendary": "#f59e0b"}
_ADJ = ("Swift", "Silent", "Lucky", "Iron", "Golden", "Shadow", "Turbo", "Patient", "Crimson", "Frosty", "Clever", "Bold",
        "Sneaky", "Mighty", "Cosmic", "Thunder", "Velvet", "Rusty", "Neon", "Stormy", "Quiet", "Brave", "Jade", "Solar",
        "Lunar", "Atomic", "Wild", "Steady", "Nimble", "Electric", "Mystic", "Copper")
_BEAST = ("Falcon", "Otter", "Badger", "Lynx", "Mantis", "Viper", "Panda", "Heron", "Wolf", "Gecko", "Raven", "Bison",
          "Fox", "Shark", "Owl", "Tiger", "Moth", "Yak", "Cobra", "Koala", "Puma", "Hawk", "Beetle", "Marten", "Orca",
          "Ibex", "Lemur", "Jackal", "Stoat", "Kestrel", "Tapir", "Walrus")


def bot_nickname(key):
    """A stable, friendly name for a bot (the same settings always get the same name)."""
    import hashlib
    h = hashlib.sha1(repr(key).encode()).digest()
    return f"{_ADJ[h[0] % len(_ADJ)]} {_BEAST[h[1] % len(_BEAST)]}"


def is_shiny(key):
    import hashlib
    return hashlib.sha1(("shiny" + repr(key)).encode()).digest()[0] < 5  # about 1 in 50


def rarity_for(lt):
    """Rarity from a bot's track record (lifetime dict from a bot file): beating holding counts most,
    then win rate and time spent winning."""
    lt = lt or {}
    edge = float(lt.get("vs_holding_pct") or 0)
    wr = lt.get("win_rate_pct")
    hrs = float(lt.get("hours_winning") or 0)
    score = edge + (0 if wr is None else (float(wr) - 50) * 0.08) + min(hrs, 48) * 0.15
    if lt.get("source") == "Bot Lab unseen-data test" and edge > 0:
        score += 1.5  # passing on unseen prices is worth extra
    for name, need in (("Legendary", 12), ("Epic", 7), ("Rare", 3.5), ("Uncommon", 1.5)):
        if score >= need:
            return name
    return "Common"


def xp_for(lt):
    lt = lt or {}
    return int(float(lt.get("hours_winning") or 0) * 10 + float(lt.get("trades") or 0) * 2
               + max(0.0, float(lt.get("vs_holding_pct") or 0)) * 5)


def level_for(xp):
    return min(99, 1 + int((max(0, xp) / 10) ** 0.5))


def collection_path():
    return os.path.join(HOME_DIR, "collection.json")


def load_collection():
    if not os.path.exists(collection_path()):
        return []
    bots, _ = read_bots_file(collection_path())
    return bots


def save_collection(bots):
    save_json(collection_path(), dict(format=BOT_FORMAT, version=BOT_FORMAT_VERSION, kind="collection",
                                      exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      bots=bots[:200]))


def catch(entries, source=""):
    """Adds bots to the collection, or updates ones you already have (they can level up and rank up,
    never down). Returns (new, levelled_up, [caught entries])."""
    col = load_collection()
    index = {bot_key(b): i for i, b in enumerate(col)}
    new = ups = 0
    out = []
    for e in entries:
        k = bot_key(e)
        lt = e.get("lifetime") or {}
        xp = xp_for(lt)
        r = rarity_for(lt)
        if k in index:
            old = col[index[k]]
            xp = max(xp, int(old.get("xp") or 0))
            if RARITIES.index(old.get("rarity", "Common")) > RARITIES.index(r):
                r = old.get("rarity", "Common")
            if level_for(xp) > int(old.get("level") or 1) or r != old.get("rarity"):
                ups += 1
            merged = dict(e, nickname=old.get("nickname") or bot_nickname(k), rarity=r, xp=xp, level=level_for(xp),
                          caught_at=old.get("caught_at"), source=old.get("source") or source, team=bool(old.get("team")),
                          shiny=bool(old.get("shiny")))
            for f in MEMORY_FIELDS:  # keep what it remembers (backtests, retests...) when the new copy doesn't carry it
                if f not in e and f in old:
                    merged[f] = old[f]
            col[index[k]] = merged
            out.append(merged)
        else:
            if len(col) >= 200:
                continue
            item = dict(e, nickname=bot_nickname(k), rarity=r, xp=xp, level=level_for(xp),
                        caught_at=datetime.now().isoformat(timespec="seconds"), source=source, team=False,
                        shiny=is_shiny(k))
            index[k] = len(col)
            col.append(item)
            out.append(item)
            new += 1
    save_collection(col)
    return new, ups, out


def release(keys):
    keys = set(keys)
    col = [b for b in load_collection() if bot_key(b) not in keys]
    save_collection(col)
    return col


def set_team(keys, on):
    """Adds bots to (or removes them from) your team. Returns (team size, refused because the team is full)."""
    keys, col, full = set(keys), load_collection(), 0
    size = sum(1 for b in col if b.get("team"))
    for b in col:
        if bot_key(b) in keys and bool(b.get("team")) != on:
            if on and size >= TEAM_MAX:
                full += 1
                continue
            b["team"] = on
            size += 1 if on else -1
    save_collection(col)
    return size, full


def team():
    return [b for b in load_collection() if b.get("team")]


# ---------------- Hall of Fame (long-term winners, saved automatically) ----------------
def hof_path():
    return os.path.join(HOME_DIR, "hall-of-fame.json")


def load_hof():
    """Hall of Fame entries (bot-file entries with lifetime stats), best first."""
    if not os.path.exists(hof_path()):
        return []
    bots, _ = read_bots_file(hof_path())
    return sorted(bots, key=lambda b: -((b.get("lifetime") or {}).get("vs_holding_pct") or 0))


def save_hof(bots, app_version=""):
    save_json(hof_path(), dict(format=BOT_FORMAT, version=BOT_FORMAT_VERSION, app_version=app_version,
                               exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               kind="hall-of-fame", bots=bots[:200]))


def update_saved(key, fn, app_version=""):
    """Runs fn(entry) on the saved copies of one bot (Library and Hall of Fame) and saves them. Returns how many."""
    n = 0
    col = load_collection()
    for b in col:
        if bot_key(b) == key:
            fn(b)
            n += 1
    if n:
        save_collection(col)
    hof = load_hof()
    m = 0
    for b in hof:
        if bot_key(b) == key:
            fn(b)
            m += 1
    if m:
        save_hof(hof, app_version)
    return n + m


def induct(entries, app_version=""):
    """Adds or refreshes Hall of Fame entries (bot-file dicts). Returns how many were new."""
    hof = load_hof()
    index = {bot_key(b): i for i, b in enumerate(hof)}
    new = 0
    for e in entries:
        k = bot_key(e)
        e = dict(e, inducted_at=e.get("inducted_at") or datetime.now().isoformat(timespec="seconds"))
        if k in index:
            e["inducted_at"] = hof[index[k]].get("inducted_at", e["inducted_at"])
            for f in MEMORY_FIELDS:
                if f not in e and f in hof[index[k]]:
                    e[f] = hof[index[k]][f]
            hof[index[k]] = e
        else:
            index[k] = len(hof)
            hof.append(e)
            new += 1
    save_hof(sorted(hof, key=lambda b: -((b.get("lifetime") or {}).get("vs_holding_pct") or 0)), app_version)
    return new


def remove_from_hof(keys):
    hof = [b for b in load_hof() if bot_key(b) not in set(keys)]
    save_hof(hof)
    return hof


def save_bots_file(path, payload):
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) < 1e12


def _clean_memory(d):
    """A saved bot's memory (backtests, retest, rule evidence, twin test), plain numbers only."""
    out = {}
    if _num(d.get("twin_test_pct")):
        out["twin_test_pct"] = float(d["twin_test_pct"])
    rt = d.get("retest")
    if isinstance(rt, dict):
        out["retest"] = {k: v for k, v in rt.items() if k in ("date", "edge", "ret", "rusty")
                         and (_num(v) or isinstance(v, bool) or (isinstance(v, str) and len(v) <= 20))}
    bts = d.get("backtests")
    if isinstance(bts, list):
        keep = []
        for b in bts[-10:]:
            if isinstance(b, dict):
                keep.append({k: v for k, v in b.items() if (_num(v) or v is None or (isinstance(v, str) and len(v) <= 20))})
        if keep:
            out["backtests"] = keep
    for f in ("layer_stats", "veto_stats"):
        st = d.get(f)
        if isinstance(st, dict):
            good = {k: [float(x[0]), float(x[1])] for k, x in st.items()
                    if isinstance(k, str) and len(k) <= 12 and isinstance(x, list) and len(x) == 2 and all(_num(y) for y in x)}
            if good:
                out[f] = good
    return out


def read_bots_file(path):
    """-> (valid bots, list of problems). Never raises on bad content. Accepts a bot file, or the
    plain saved-lineup list. Only known strategy names and numeric settings get through; the
    file is data only and nothing in it is ever run."""
    problems = []
    try:
        if os.path.getsize(path) > MAX_BOT_FILE:
            return [], ["That file is too big to be a bot file."]
        with open(path) as f:
            data = json.load(f)
    except Exception as ex:
        return [], [f"Could not read the file ({ex.__class__.__name__})."]
    if isinstance(data, dict) and data.get("format") in BOT_FORMATS:
        raw = data.get("bots")
    elif isinstance(data, dict) and "name" in data and "params" in data:
        raw = [data]
    elif isinstance(data, list):
        raw = data
    else:
        return [], ["That does not look like a CBBF bot file."]
    if not isinstance(raw, list):
        return [], ["The bot list in this file is damaged."]
    good = []
    for i, d in enumerate(raw[:200], 1):
        if not isinstance(d, dict) or d.get("name") not in STRATS or d["name"] == "Dollar-cost averaging" \
                or not isinstance(d.get("params"), dict):
            problems.append(f"Skipped item {i}: unknown or unsupported strategy.")
            continue
        try:
            params = {k: float(v) for k, v in d["params"].items() if k in STRATS[d["name"]]["params"]}
            size = float(d.get("size", 1.0))
        except (TypeError, ValueError):
            problems.append(f"Skipped item {i}: settings are not numbers.")
            continue
        stats = d.get("stats") if isinstance(d.get("stats"), dict) else {}
        item = dict(name=d["name"], params=params, size=size, stats=stats, tf=clamp_tf(d.get("tf", 1)),
                    risk=clean_risk(d.get("risk") if isinstance(d.get("risk"), dict) else None),
                    traits=clean_traits(d.get("traits") if isinstance(d.get("traits"), dict) else None),
                    vetoes=clean_vetoes(d.get("vetoes") if isinstance(d.get("vetoes"), dict) else None),
                    layers=clean_layers(d.get("layers")))
        if isinstance(d.get("lifetime"), dict):
            item["lifetime"] = {k: v for k, v in d["lifetime"].items()
                                if isinstance(v, (int, float, str)) or v is None}
        if isinstance(d.get("inducted_at"), str):
            item["inducted_at"] = d["inducted_at"][:32]
        for k in COLLECT_FIELDS:  # Bot Collection extras (plain text / numbers only)
            v = d.get(k)
            if isinstance(v, bool) or isinstance(v, (int, float)) or (isinstance(v, str) and len(v) <= 80):
                item[k] = v
        if isinstance(d.get("notes"), str):
            item["notes"] = d["notes"][:200]
        mem = _clean_memory(d)
        item.update(mem)
        good.append(item)
    return good, problems


TRADE_FIELDS = ["time", "mode", "side", "coin", "qty", "price", "usd", "pl", "reason", "who"]


def append_trade_csv(row):
    path = os.path.join(HOME_DIR, "trades.csv")
    os.makedirs(HOME_DIR, exist_ok=True)
    if os.path.exists(path):  # an older file has fewer columns: keep it aside rather than mixing formats
        try:
            with open(path, newline="") as f:
                header = f.readline().strip()
            if header != ",".join(TRADE_FIELDS):
                os.replace(path, os.path.join(HOME_DIR, f"trades-before-{datetime.now():%Y%m%d-%H%M%S}.csv"))
        except OSError:
            pass
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in TRADE_FIELDS})


def export_trades_csv(path, trades):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        w.writeheader()
        for t in trades:
            w.writerow({k: t.get(k, "") for k in TRADE_FIELDS})


# ---------------- optional add-ons (installed on demand) ----------------
DEPENDENCIES = [  # keep in sync with requirements.txt
    dict(pip="keyring>=24.0", module="keyring", label="Secure login storage",
         why="Lets the app remember your Alpaca login in your computer's keychain."),
]


def dep_status():
    """[(dependency, installed?)]"""
    importlib.invalidate_caches()
    return [(d, importlib.util.find_spec(d["module"]) is not None) for d in DEPENDENCIES]


def missing_deps():
    return [d for d, ok in dep_status() if not ok]


def install_packages(specs, log=print):
    """Installs packages with pip into the Python running this app. Calls log(line) as pip works.
    Returns (ok, plain-English message)."""
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}  # no extra console window on Windows

    def run(cmd):
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **flags)
        except OSError as e:
            return 1, str(e)
        out = []
        for line in p.stdout:
            out.append(line)
            log(line.rstrip())
        p.wait()
        return p.returncode, "".join(out)

    if importlib.util.find_spec("pip") is None:
        log("pip is missing, setting it up first...")
        run([sys.executable, "-m", "ensurepip", "--upgrade"])
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    rc, out = run(base + list(specs))
    low = out.lower()
    if rc != 0 and any(x in low for x in ("permission", "access is denied", "externally-managed", "externally managed")):
        log("Retrying for your user account only...")
        rc, out = run(base + ["--user"] + list(specs))
        low = out.lower()
    if rc == 0:
        importlib.invalidate_caches()
        try:  # a fresh per-user install folder is not on the path until the next start
            import site
            u = site.getusersitepackages()
            if os.path.isdir(u) and u not in sys.path:
                sys.path.append(u)
        except Exception:
            pass
        return True, "All set. The add-ons are installed and ready, no restart needed."
    if any(x in low for x in ("getaddrinfo", "connection", "timed out", "could not find a version", "no matching distribution",
                              "name or service not known", "network")):
        return False, "Couldn't download the add-ons. Check your internet connection and try again."
    if "externally-managed" in low or "externally managed" in low:
        return False, ("Your Python is locked by your operating system. Run this once in a terminal instead:\n"
                       f"{os.path.basename(sys.executable)} -m pip install --user --break-system-packages "
                       + " ".join(f'"{x}"' for x in specs))
    if "microsoft visual c++" in low or "failed building wheel" in low:
        return False, "An add-on needs build tools your computer doesn't have. Installing a newer Python (3.11 or 3.12) usually fixes it."
    return False, "The install didn't finish. The details are in the box above; sending them to me is the quickest way to get it fixed."


# ---------------- Alpaca login (API key) ----------------
KEYRING_SERVICE = "obf"


def check_credentials(key, secret):
    if not (key or "").strip():
        return False, "The API Key ID box is empty. It looks like PK... (paper) or AK... (live)."
    if not (secret or "").strip():
        return False, "The secret key box is empty. Alpaca shows it once, when you create the key."
    if len(key.strip()) < 10 or len(secret.strip()) < 20:
        return False, "That doesn't look like an Alpaca key pair. Copy both values again from the Alpaca dashboard."
    return True, ""


def explain_login_error(err, secret=""):
    low = str(err).lower()
    if "401" in low or "403" in low or "unauthorized" in low or "forbidden" in low:
        return ("Alpaca did not accept this key.\n\nCheck that you picked the right account type: paper keys (they start "
                "with PK) only work with 'Paper', live keys (AK...) only with 'Live'.\n\n(Technical detail: " + str(err) + ")")
    return str(err)


def keyring_available():
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------- other secrets: kept in the system keychain, never in config.json ----------------
SECRET_SETTINGS = ("alert_tg_token", "alert_discord")   # inside cfg["settings"]
SECRET_CFG = ("fred_key",)                              # at the top of cfg


def secret_set(name, value):
    """Stores a secret in the system keychain (Windows Credential Manager / macOS Keychain). False if unavailable."""
    try:
        import keyring
        if value:
            keyring.set_password(KEYRING_SERVICE, name, str(value))
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, name)
            except Exception:
                pass
        return True
    except Exception:
        return False


def secret_get(name):
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, name) or ""
    except Exception:
        return ""


def keychain_ok():
    try:
        import keyring
        keyring.get_password(KEYRING_SERVICE, "_probe")
        return True
    except Exception:
        return False


def scrub_config(cfg):
    """A copy of the config with its secrets moved to the keychain (if it works) and blanked."""
    if not isinstance(cfg, dict) or not keychain_ok():
        return cfg
    out = dict(cfg)
    st = dict(out.get("settings") or {})
    for k in SECRET_SETTINGS:  # an emptied field removes the stored secret too
        if k in st and secret_set(k, st.get(k) or ""):
            st[k] = ""
    for k in SECRET_CFG:
        if k in out and secret_set(k, out.get(k) or ""):
            out[k] = ""
    if "settings" in out:
        out["settings"] = st
    return out


def fill_secrets(cfg):
    """Puts the keychain's secrets back into a freshly loaded config (in memory only)."""
    st = cfg.setdefault("settings", {}) if isinstance(cfg.get("settings"), dict) or "settings" not in cfg else cfg["settings"]
    for k in SECRET_SETTINGS:
        if not st.get(k):
            v = secret_get(k)
            if v:
                st[k] = v
    for k in SECRET_CFG:
        if not cfg.get(k):
            v = secret_get(k)
            if v:
                cfg[k] = v
    return cfg


_REDACT = [
    (re.compile(r"(api_key=)[A-Za-z0-9]+"), r"\1[hidden]"),
    (re.compile(r"(api\.telegram\.org/bot)[^/\s]+"), r"\1[hidden]"),
    (re.compile(r"(discord(?:app)?\.com/api/webhooks/)\S+"), r"\1[hidden]"),
    (re.compile(r"\b(?:PK|AK)[A-Z0-9]{14,}\b"), "[hidden key]"),
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"), "[hidden token]"),
]


def redact(text):
    """Removes anything that looks like a key, token or webhook from text going into logs."""
    text = str(text)
    for rx, sub in _REDACT:
        text = rx.sub(sub, text)
    return text


def private_dir(path):
    """Makes the data folder readable by you only (Mac / Linux; Windows user folders already are)."""
    try:
        if os.name == "posix":
            os.makedirs(path, exist_ok=True)
            os.chmod(path, 0o700)
    except OSError:
        pass


def save_login(key, secret, paper=True):
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, "alpaca", json.dumps({"key": key, "secret": secret, "paper": bool(paper)}))
        return True
    except Exception:
        return False


def load_login():
    """(key, secret, paper) or None."""
    try:
        import keyring
        raw = keyring.get_password(KEYRING_SERVICE, "alpaca")
        if raw:
            d = json.loads(raw)
            return d["key"], d["secret"], bool(d.get("paper", True))
    except Exception:
        pass
    return None


def clear_login():
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, "alpaca")
    except Exception:
        pass


# ---------------- updates from GitHub ----------------
def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def changelog_since(text, current):
    """The changelog sections newer than `current` (sections start with '## <version>' or '## Unreleased')."""
    out, keep = [], False
    for line in (text or "").splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            head = m.group(1).strip()
            nums = re.findall(r"\d+\.\d+(?:\.\d+)?", head)
            keep = bool(nums) and version_tuple(nums[0]) > version_tuple(current)
        if keep:
            out.append(line)
    return "\n".join(out).strip()


UPDATE_FILES = re.compile(r"^(?:[\w.-]+\.pyw?|VERSION|README\.md|CHANGELOG\.md|requirements\.txt|[\w .-]+\.bat)$")


def install_update(zip_bytes, here, current_version):
    """Unpacks a GitHub branch zip over the app folder. The files being replaced are first copied to
    here/backups/<old version>-<time>/ so the update can be undone. Returns (files written, backup folder)."""
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    picks = {}
    for name in z.namelist():
        rel = name.split("/", 1)[1] if "/" in name else ""
        if rel and "/" not in rel and UPDATE_FILES.match(rel):
            picks[rel] = name
    if "main.py" not in picks or "engine.py" not in picks:
        raise RuntimeError("the download doesn't look like this app (main.py / engine.py missing)")
    for rel in ("main.py", "engine.py"):  # never install something that doesn't even compile
        compile(z.read(picks[rel]).decode("utf-8"), rel, "exec")
    backup = os.path.join(here, "backups", f"{current_version}-{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(backup, exist_ok=True)
    for rel in os.listdir(here):
        if UPDATE_FILES.match(rel) and os.path.isfile(os.path.join(here, rel)):
            shutil.copy2(os.path.join(here, rel), os.path.join(backup, rel))
    written = []
    for rel, name in picks.items():
        tmp = os.path.join(here, rel + ".new")
        with open(tmp, "wb") as f:
            f.write(z.read(name))
        os.replace(tmp, os.path.join(here, rel))
        written.append(rel)
    return written, backup


def latest_backup(here):
    root = os.path.join(here, "backups")
    try:
        dirs = sorted((d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))),
                      key=lambda d: os.path.getmtime(os.path.join(root, d)))
    except OSError:
        return None
    return os.path.join(root, dirs[-1]) if dirs else None


def restore_backup(here, backup):
    for rel in os.listdir(backup):
        if UPDATE_FILES.match(rel):
            shutil.copy2(os.path.join(backup, rel), os.path.join(here, rel))


# ---------------- CBBF's own notification sounds ----------------
SOUNDS = {  # (frequency Hz, start s, length s) notes; synthesized, so nothing to download
    "trade": [(988, 0.0, 0.09), (1319, 0.05, 0.12)],
    "notify": [(1319, 0.0, 0.35), (1760, 0.13, 0.5)],
    "hof": [(1047, 0.0, 0.22), (1319, 0.11, 0.22), (1568, 0.22, 0.22), (2093, 0.33, 0.6)],
    "problem": [(440, 0.0, 0.28), (349, 0.22, 0.42)],
}


def sound_path(kind, volume=60):
    """Writes (once) and returns a small .wav for this kind of sound: soft bell-like tones with a quick
    fade, clearly different from the Windows system sounds."""
    import math as _m
    import struct
    import wave
    vol = max(0, min(100, int(volume)))
    folder = os.path.join(HOME_DIR, "sounds")
    path = os.path.join(folder, f"{kind}-{vol}.wav")
    if os.path.exists(path):
        return path
    os.makedirs(folder, exist_ok=True)
    rate = 22050
    notes = SOUNDS.get(kind, SOUNDS["notify"])
    total = max(st + ln for _, st, ln in notes) + 0.05
    buf = [0.0] * int(rate * total)
    for f, st, ln in notes:
        a = int(st * rate)
        for i in range(int(ln * rate)):
            t = i / rate
            env = min(1.0, t / 0.008) * _m.exp(-t * 6.5 / ln)  # quick attack, bell-like decay
            v = (_m.sin(2 * _m.pi * f * t) + 0.35 * _m.sin(2 * _m.pi * 2 * f * t) + 0.12 * _m.sin(2 * _m.pi * 3 * f * t)) * env
            if a + i < len(buf):
                buf[a + i] += v
    peak = max(1e-9, max(abs(x) for x in buf))
    scale = 32767 * 0.9 * (vol / 100) / peak
    with wave.open(path + ".tmp", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(x * scale)) for x in buf))
    os.replace(path + ".tmp", path)
    return path


def play_sound(kind, volume=60):
    """Plays one of CBBF's sounds without blocking. Silently does nothing if the computer can't."""
    def run():
        try:
            path = sound_path(kind, volume)
            if sys.platform.startswith("win"):
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            elif sys.platform == "darwin":
                subprocess.Popen(["afplay", path])
            else:
                for player in ("paplay", "aplay", "pw-play"):
                    if shutil.which(player):
                        subprocess.Popen([player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        break
        except Exception:
            pass
    import threading
    threading.Thread(target=run, daemon=True).start()
