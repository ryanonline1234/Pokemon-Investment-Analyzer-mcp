#!/usr/bin/env python3
"""TCG Analyzer

Consolidated command-line analyzer that gathers pricing, sales, listings,
set metadata, PSA population, sentiment, and reprint signals for a given
Pokémon TCG set and prints a human-readable summary.

Usage:
    python3 tcg_analyzer.py "Set Name"
"""
import sys
import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import subprocess
import datetime


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s


def parse_price_from_text(text: str):
    if not text:
        return None
    m = re.search(r"\$\s?([0-9,]+(?:\.[0-9]{1,2})?)", text)
    if not m:
        return None
    price_str = m.group(1).replace(",", "")
    try:
        return float(price_str)
    except ValueError:
        return price_str


def scrape_price_data(set_name: str):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)"}
    slug = slugify(set_name)
    candidates = [
        f"https://www.pricecharting.com/console/pokemon-card-game/sets/{slug}",
        f"https://www.pricecharting.com/search-products?query={quote_plus(set_name)}&type=console&platform=pokemon-card-game",
    ]
    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        texts = soup.find_all(string=re.compile(r"Booster|Box|Sealed", re.I))
        for t in texts:
            txt = t.strip()
            if not re.search(r"booster", txt, re.I):
                continue
            tr = t.find_parent("tr")
            if tr:
                row_text = tr.get_text(separator=" ")
                price = parse_price_from_text(row_text)
                if price is not None:
                    return price
        page_text = soup.get_text(separator=" \n")
        for match in re.finditer(r"(.{0,120}booster.{0,120})", page_text, re.I):
            snippet = match.group(1)
            price = parse_price_from_text(snippet)
            if price is not None:
                return price
    return None


def parse_date_from_text(text: str):
    if not text:
        return None
    m = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b", text)
    if m:
        return m.group(0)
    m2 = re.search(r"\b\d+\s+(?:day|days|week|weeks|month|months)\s+ago\b", text, re.I)
    if m2:
        return m2.group(0)
    return None


def scrape_ebay_sales(query: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    search_url = f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}&_sop=10&LH_Sold=1&LH_Complete=1"
    try:
        resp = requests.get(search_url, headers=headers, timeout=10)
    except Exception as e:
        return {"count_sold": 0, "avg_price": None, "error": str(e)}
    if resp.status_code != 200:
        return {"count_sold": 0, "avg_price": None, "error": f"http_{resp.status_code}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("li.s-item")
    prices = []
    samples = []
    for item in items:
        text = item.get_text(separator=" ")
        price = parse_price_from_text(text)
        date = parse_date_from_text(text)
        if price is not None:
            prices.append(price)
            samples.append({"price": price, "date": date})
    count = len(prices)
    avg = None
    if count > 0:
        avg = sum(prices) / count
    return {"count_sold": count, "avg_price": avg, "samples": samples[:10]}


def scrape_tcgplayer_listings(product_name: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    candidates = [
        f"https://www.tcgplayer.com/search?query={quote_plus(product_name)}",
        f"https://www.tcgplayer.com/search/products?query={quote_plus(product_name)}",
        f"https://www.tcgplayer.com/search?q={quote_plus(product_name)}",
    ]
    def extract_counts(text: str):
        m = re.search(r"([0-9,]+)\s+listings", text, re.I)
        listings = None
        sellers = None
        if m:
            try:
                listings = int(m.group(1).replace(",", ""))
            except Exception:
                listings = None
        m2 = re.search(r"([0-9,]+)\s+(?:sellers|seller|offers)", text, re.I)
        if m2:
            try:
                sellers = int(m2.group(1).replace(",", ""))
            except Exception:
                sellers = None
        return listings, sellers
    last_err = None
    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
        except Exception as e:
            last_err = str(e)
            continue
        if resp.status_code != 200:
            last_err = f"http_{resp.status_code}"
            continue
        page_text = BeautifulSoup(resp.text, "html.parser").get_text(separator=" ")
        listings, sellers = extract_counts(page_text)
        if listings is not None or sellers is not None:
            return {"listings_count": listings, "sellers_count": sellers, "error": None, "source": url}
    return {"listings_count": None, "sellers_count": None, "error": last_err, "source": None}


def get_set_info(set_name: str):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)",}
    api_search = "https://en.wikipedia.org/w/api.php"
    params = {"action": "query", "list": "search", "srsearch": set_name + " Pokemon", "format": "json", "srlimit": 1}
    try:
        r = requests.get(api_search, params=params, headers=headers, timeout=8)
        r.raise_for_status()
        data = r.json()
        hits = data.get("query", {}).get("search", [])
        if not hits:
            return {"num_cards": None, "release_date": None, "notes": None, "source": None}
        title = hits[0].get("title")
    except Exception:
        title = f"Pokemon {set_name}"
    page_url = "https://en.wikipedia.org/wiki/" + quote_plus(title.replace(" ", "_"))
    try:
        resp = requests.get(page_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception:
        return {"num_cards": None, "release_date": None, "notes": None, "source": None}
    soup = BeautifulSoup(resp.text, "html.parser")
    infobox = soup.find("table", class_=re.compile(r"infobox", re.I))
    num_cards = None
    release_date = None
    if infobox:
        for row in infobox.find_all("tr"):
            th = row.find("th")
            td = row.find("td")
            if not th or not td:
                continue
            key = th.get_text(separator=" ").strip().lower()
            val = td.get_text(separator=" ").strip()
            if "cards" in key or "number" in key and "cards" in val.lower():
                m = re.search(r"([0-9,]+)", val)
                if m:
                    try:
                        num_cards = int(m.group(1).replace(",", ""))
                    except Exception:
                        num_cards = None
            if any(k in key for k in ("released", "release date", "release")) and not release_date:
                release_date = val
    page_text = soup.get_text(separator=" ")
    notes = []
    if re.search(r"limited\s+run|limited\s+edition|limited edition", page_text, re.I):
        notes.append("mentions limited run/edition")
    if re.search(r"reprint|reprinted", page_text, re.I):
        notes.append("mentions reprint/reprinted")
    if re.search(r"promotional|promo|exclusive distribution", page_text, re.I):
        notes.append("mentions promotional/exclusive distribution")
    notes_str = "; ".join(notes) if notes else None
    return {"num_cards": num_cards, "release_date": release_date, "notes": notes_str, "source": page_url}


def get_top_chase_cards(set_name: str, top_n: int = 5):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)"}
    slug = slugify(set_name)
    url = f"https://www.pricecharting.com/console/pokemon-card-game/sets/{slug}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"top_cards": [], "sum_top": 0.0, "avg_top": None, "source": url, "error": f"http_{resp.status_code}"}
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        return {"top_cards": [], "sum_top": 0.0, "avg_top": None, "source": url, "error": str(e)}
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/product/" in href and a.get_text(strip=True):
            name = a.get_text(strip=True)
            if re.search(r"\b(box|booster|pack|set|sealed|bundle)\b", name, re.I):
                continue
            price = None
            parent = a
            for _ in range(4):
                parent = parent.parent
                if parent is None:
                    break
                text = parent.get_text(separator=" ")
                price = parse_price_from_text(text)
                if price is not None:
                    break
            if price is not None:
                candidates.append({"name": name, "price": price})
    if not candidates:
        rows = soup.find_all("tr")
        for tr in rows:
            txt = tr.get_text(separator=" ")
            if re.search(r"\b(box|booster|pack|set|sealed)\b", txt, re.I):
                continue
            price = parse_price_from_text(txt)
            if price is None:
                continue
            a = tr.find("a")
            if a and a.get_text(strip=True):
                name = a.get_text(strip=True)
            else:
                name = txt.strip().split(" \n")[0][:80]
            candidates.append({"name": name, "price": price})
    dedup = {}
    for c in candidates:
        n = c["name"]
        p = c["price"]
        if n not in dedup or (dedup[n] is not None and p > dedup[n]):
            dedup[n] = p
    items = [{"name": n, "price": p} for n, p in dedup.items() if p is not None]
    items.sort(key=lambda x: x["price"], reverse=True)
    top = items[:top_n]
    sum_top = sum([c["price"] for c in top]) if top else 0.0
    avg_top = (sum_top / len(top)) if top else None
    return {"top_cards": top, "sum_top": sum_top, "avg_top": avg_top, "source": url}


def check_reprint_news(set_name: str, days_back: int = 30):
    query = f'"{set_name}" reprint OR {set_name} reprint'
    since_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    results = []
    try:
        import snscrape.modules.twitter as sntwitter
        scraper_query = f'{query} since:{since_date}'
        scraper = sntwitter.TwitterSearchScraper(scraper_query)
        for i, tweet in enumerate(scraper.get_items()):
            if i >= 20:
                break
            text = tweet.content
            url = f"https://twitter.com/{tweet.user.username}/status/{tweet.id}"
            results.append({"source": url, "text": text})
    except Exception:
        try:
            cmd = [
                "snscrape",
                "--jsonl",
                "twitter-search",
                f'{query} since:{since_date}',
                "--max-results",
                "20",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0 and proc.stdout:
                for line in proc.stdout.splitlines():
                    try:
                        j = json.loads(line)
                        content = j.get("content") or j.get("rawContent") or ""
                        username = j.get("user", {}).get("username")
                        tweetid = j.get("id")
                        if username and tweetid:
                            url = f"https://twitter.com/{username}/status/{tweetid}"
                        else:
                            url = None
                        results.append({"source": url, "text": content})
                    except Exception:
                        continue
        except Exception:
            return {"warning": False, "matches": [], "note": "snscrape not available; check not performed"}
    if results:
        return {"warning": True, "matches": results, "note": None}
    return {"warning": False, "matches": [], "note": None}


def get_psa_population(card_name: str):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)",}
    search_url = f"https://www.psacard.com/pop/search?searchTerm={quote_plus(card_name)}"
    try:
        resp = requests.get(search_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"psa10": None, "grades": {}, "source": search_url, "error": f"http_{resp.status_code}"}
        text = BeautifulSoup(resp.text, "html.parser").get_text(separator=" ")
    except Exception as e:
        return {"psa10": None, "grades": {}, "source": search_url, "error": str(e)}
    grades = {}
    for g in [10, 9, 8, 7, 6, 5]:
        m = re.search(rf"PSA\s*{g}[^0-9\n\r]{{0,30}}([0-9,]+)", text, re.I)
        if m:
            try:
                grades[str(g)] = int(m.group(1).replace(",", ""))
            except Exception:
                grades[str(g)] = None
    psa10 = grades.get("10")
    if not grades:
        return {"psa10": psa10, "grades": {}, "source": search_url, "error": "no grade data parsed; site may be dynamic"}
    return {"psa10": psa10, "grades": grades, "source": search_url, "error": None}


def analyze_sentiment(set_name: str, max_posts: int = 50):
    positive_keywords = ["good", "great", "bull", "buy", "hype", "pop", "profit", "moon", "win"]
    negative_keywords = ["bad", "sell", "dump", "overvalued", "scam", "bubble", "fear", "loss"]
    texts = []
    try:
        import praw
        reddit = praw.Reddit()
        subs = ["PokeInvesting", "PokemonTCG", "pokemontcg"]
        for sub in subs:
            try:
                subreddit = reddit.subreddit(sub)
                for submission in subreddit.search(set_name, limit=max_posts//len(subs)):
                    texts.append(submission.title + " \n" + (submission.selftext or ""))
                    if len(texts) >= max_posts:
                        break
                if len(texts) >= max_posts:
                    break
            except Exception:
                continue
    except Exception:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)"}
            url = f"https://old.reddit.com/search?q={quote_plus(set_name)}&sort=new"
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for post in soup.select("div.search-result-link")[:max_posts]:
                    title = post.select_one("a.search-title")
                    if title:
                        texts.append(title.get_text())
        except Exception:
            texts = [f"I love the {set_name} set! Great buy.", f"I think {set_name} is overhyped and might drop."]
    polarities = []
    sample_texts = texts[:10]
    try:
        from textblob import TextBlob
        for t in texts:
            try:
                p = TextBlob(t).sentiment.polarity
            except Exception:
                p = 0.0
            polarities.append(p)
    except Exception:
        for t in texts:
            score = 0
            low = t.lower()
            for pk in positive_keywords:
                if pk in low:
                    score += 1
            for nk in negative_keywords:
                if nk in low:
                    score -= 1
            polarities.append(float(score))
    avg = None
    classification = "no data"
    if polarities:
        avg = sum(polarities) / len(polarities)
        if avg > 0.3:
            classification = "mostly positive"
        elif avg < -0.3:
            classification = "mostly negative"
        else:
            classification = "mixed"
    return {"avg_polarity": avg, "classification": classification, "sample": sample_texts}


def compute_metrics(set_name: str):
    try:
        box_price = scrape_price_data(set_name)
    except Exception:
        box_price = None
    try:
        ebay = scrape_ebay_sales(f"{set_name} booster box")
    except Exception:
        ebay = {"count_sold": 0, "avg_price": None}
    try:
        listings = scrape_tcgplayer_listings(f"{set_name} booster box")
    except Exception:
        listings = {"listings_count": None}
    try:
        info = get_set_info(set_name)
    except Exception:
        info = {"num_cards": None, "release_date": None}
    try:
        top = get_top_chase_cards(set_name, top_n=5)
    except Exception:
        top = {"top_cards": [], "sum_top": 0.0, "avg_top": None}
    top_card_name = None
    if top.get("top_cards"):
        top_card_name = top["top_cards"][0].get("name")
    psa = None
    if top_card_name:
        try:
            psa = get_psa_population(top_card_name)
        except Exception:
            psa = {"psa10": None}
    try:
        reprint = check_reprint_news(set_name)
    except Exception:
        reprint = {"warning": False, "matches": [], "note": "check failed"}
    try:
        sentiment = analyze_sentiment(set_name)
    except Exception:
        sentiment = {"avg_polarity": None, "classification": "unknown", "sample": []}
    sold_count_30d = ebay.get("count_sold") or 0
    days_window = 30
    daily_sales = sold_count_30d / days_window if sold_count_30d else 0.0
    weekly_sales = daily_sales * 7
    listings_count = listings.get("listings_count") or 0
    days_to_clear = None
    if daily_sales > 0:
        days_to_clear = listings_count / daily_sales if listings_count is not None else None
    parts = []
    if box_price:
        try:
            parts.append(f"current box price ${float(box_price):.2f}")
        except Exception:
            parts.append(f"current box price {box_price}")
    else:
        parts.append("current box price N/A")
    parts.append(f"~{int(weekly_sales)} sold/week on eBay")
    parts.append(f"{listings_count} listings on market")
    if days_to_clear is None:
        parts.append("days-to-clear: N/A")
    else:
        parts.append(f"~{int(days_to_clear)} days to clear")
    if top.get("top_cards"):
        top0 = top["top_cards"][0]
        parts.append(f"top card {top0.get('name')} ~${top0.get('price')}")
    if psa and psa.get("psa10") is not None:
        parts.append(f"PSA10 pop {psa.get('psa10')}")
    parts.append(f"sentiment: {sentiment.get('classification')}")
    parts.append(f"reprint risk: {'HIGH' if reprint.get('warning') else 'low'}")
    summary = f"{set_name}: " + ", ".join(parts)
    return {
        "box_price": box_price,
        "sold_count_30d": sold_count_30d,
        "daily_sales": daily_sales,
        "weekly_sales": weekly_sales,
        "listings_count": listings_count,
        "days_to_clear": days_to_clear,
        "top_chase": top,
        "psa": psa,
        "reprint": reprint,
        "sentiment": sentiment,
        "set_info": info,
        "summary": summary,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tcg_analyzer.py \"Set Name\"")
        sys.exit(1)
    set_name = " ".join(sys.argv[1:]).strip()
    print(f"Analyzing set: {set_name}\n")
    metrics = compute_metrics(set_name)
    # Human readable summary
    print("SUMMARY:\n")
    print(metrics.get("summary"))
    print("\nDETAILS:\n")
    print(f"Box price: {metrics.get('box_price')}")
    print(f"30d sold count: {metrics.get('sold_count_30d')}")
    print(f"Daily sales (est): {metrics.get('daily_sales'):.2f}")
    print(f"Listings: {metrics.get('listings_count')}")
    print(f"Days to clear (est): {metrics.get('days_to_clear')}")
    top = metrics.get('top_chase', {})
    if top and top.get('top_cards'):
        print('\nTop chase cards:')
        for c in top.get('top_cards'):
            print(f" - {c.get('name')}: ${c.get('price')}")
    psa = metrics.get('psa')
    if psa:
        print(f"\nPSA population (PSA10): {psa.get('psa10')}")
    print(f"\nSentiment: {metrics.get('sentiment', {}).get('classification')}")
    reprint = metrics.get('reprint')
    print(f"Reprint risk: {'HIGH' if reprint and reprint.get('warning') else 'low'}")


if __name__ == "__main__":
    main()
