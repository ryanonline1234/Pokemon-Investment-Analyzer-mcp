#!/usr/bin/env python3
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
    """Fetch the PriceCharting page for a Pokémon set and return the
    market price for a sealed Booster Box (if found).

    This function constructs a likely PriceCharting set URL, fetches the
    HTML, and searches for rows or text that mention "Booster" and "Box"
    (or "Sealed") then extracts the adjacent price using a currency regex.

    Returns a float price if found, or None.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)"
    }

    slug = slugify(set_name)
    candidates = [
        f"https://www.pricecharting.com/console/pokemon-card-game/sets/{slug}",
        # Fallback: use the search endpoint
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

        # 1) Look for table rows containing 'Booster' + 'Box' / 'Sealed'
        texts = soup.find_all(string=re.compile(r"Booster|Box|Sealed", re.I))
        for t in texts:
            txt = t.strip()
            if not re.search(r"booster", txt, re.I):
                # prioritize booster rows, but allow other matches later
                continue
            # climb up to the table row
            tr = t.find_parent("tr")
            if tr:
                row_text = tr.get_text(separator=" ")
                price = parse_price_from_text(row_text)
                if price is not None:
                    return price

        # 2) Fallback: search for any currency-looking text near the word 'Booster'
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
    # Look for dates like 'Mar 10, 2025'
    m = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b", text)
    if m:
        return m.group(0)
    # Look for relative times like '3 days ago' or 'yesterday'
    m2 = re.search(r"\b\d+\s+(?:day|days|week|weeks|month|months)\s+ago\b", text, re.I)
    if m2:
        return m2.group(0)
    return None


def scrape_ebay_sales(query: str):
    """Scrape eBay completed (sold) listings for `query` and return
    a summary dict with `count_sold` and `avg_price`.

    The function requests the eBay search results with parameters
    LH_Sold=1 and LH_Complete=1 to show completed/sold listings,
    parses visible listing items for sold prices and optional dates,
    and computes simple summary statistics.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    search_url = (
        f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}&_sop=10&LH_Sold=1&LH_Complete=1"
    )

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
    """Attempt to find current listing counts for `product_name` on TCGplayer.

    This function tries a couple of likely TCGplayer search/product URLs and
    parses static HTML for phrases like "X listings" or "listings as low as"
    to estimate supply. If the site renders this data dynamically via JavaScript,
    a headless browser (Selenium) may be required — see the comment below.

    Returns a dict: {"listings_count": int|None, "sellers_count": int|None, "error": str|None}
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Try multiple URL patterns for TCGPlayer
    candidates = [
        f"https://www.tcgplayer.com/search/pokemon/product?productLineName=pokemon&q={quote_plus(product_name)}",
        f"https://www.tcgplayer.com/search/all/product?q={quote_plus(product_name)}",
        f"https://www.tcgplayer.com/search?query={quote_plus(product_name)}",
        f"https://www.tcgplayer.com/search/pokemon?q={quote_plus(product_name)}",
    ]

    def extract_counts(text: str, html_soup=None):
        """Extract listing/seller counts from text or HTML."""
        listings = None
        sellers = None
        
        # Try multiple regex patterns for listings
        patterns = [
            r"([0-9,]+)\s+(?:available\s+)?listings?",  # "123 listings" or "123 available listings"
            r"listings?[:\s]+([0-9,]+)",  # "listings: 123"
            r"([0-9,]+)\s+results?",  # "123 results"
            r"showing\s+([0-9,]+)",  # "showing 123"
        ]
        
        for pattern in patterns:
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    listings = int(m.group(1).replace(",", ""))
                    break
                except Exception:
                    pass
        
        # Try multiple patterns for sellers
        seller_patterns = [
            r"([0-9,]+)\s+(?:sellers?|vendors?|offers?)",
            r"(?:from|by)\s+([0-9,]+)\s+sellers?",
        ]
        
        for pattern in seller_patterns:
            m2 = re.search(pattern, text, re.I)
            if m2:
                try:
                    sellers = int(m2.group(1).replace(",", ""))
                    break
                except Exception:
                    pass
        
        # Try searching in specific HTML elements if soup is provided
        if html_soup and (listings is None or sellers is None):
            # Look for data attributes or specific classes that might contain counts
            for elem in html_soup.find_all(attrs={"class": re.compile(r"listing|result|count", re.I)}):
                elem_text = elem.get_text()
                if listings is None:
                    for pattern in patterns:
                        m = re.search(pattern, elem_text, re.I)
                        if m:
                            try:
                                listings = int(m.group(1).replace(",", ""))
                                break
                            except Exception:
                                pass

        return listings, sellers

    last_err = None
    attempts = []
    
    for url in candidates:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            attempts.append({"url": url, "status": resp.status_code})
            
            if resp.status_code != 200:
                last_err = f"http_{resp.status_code}"
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = soup.get_text(separator=" ")
            
            # Try extracting with both text and soup
            listings, sellers = extract_counts(page_text, soup)
            
            if listings is not None or sellers is not None:
                return {
                    "listings_count": listings,
                    "sellers_count": sellers,
                    "error": None,
                    "source": url,
                    "note": "data found via static HTML scraping"
                }
        except Exception as e:
            last_err = str(e)
            attempts.append({"url": url, "error": str(e)})
            continue

    # If we reach here, static HTML didn't reveal counts. TCGplayer likely
    # renders marketplace counts with JavaScript; would need Selenium/Playwright
    # or access to their API to retrieve dynamic content.
    return {
        "listings_count": None,
        "sellers_count": None,
        "error": "TCGPlayer data not found in static HTML (likely requires JavaScript rendering)",
        "source": None,
        "note": "TCGPlayer renders listing counts dynamically. Alternative: Check TCGPlayer website directly, use their API (requires partnership), or implement Selenium-based scraping.",
        "attempts": attempts[:2],  # Include first 2 attempts for debugging
        "recommendation": f"Visit https://www.tcgplayer.com/search/pokemon/product?q={quote_plus(product_name)} to check supply manually"
    }


def get_set_info(set_name: str):
    """Retrieve basic metadata for a Pokémon TCG set from Wikipedia.

    Attempts a MediaWiki search to find the best-matching page, then
    parses the page's infobox for fields like 'Cards' and release date.
    Also scans the page text for words like 'limited', 'reprint', or
    'limited edition' to produce a short note about rarity/print-run.

    Returns a dict: {"num_cards": int|None, "release_date": str|None, "notes": str|None, "source": url|None}
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)",
    }

    # 1) Use the MediaWiki API to search for a likely page title
    api_search = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": set_name + " Pokemon",
        "format": "json",
        "srlimit": 1,
    }
    try:
        r = requests.get(api_search, params=params, headers=headers, timeout=8)
        r.raise_for_status()
        data = r.json()
        hits = data.get("query", {}).get("search", [])
        if not hits:
            return {"num_cards": None, "release_date": None, "notes": None, "source": None}
        title = hits[0].get("title")
    except Exception:
        # Fallback: try a direct page guess
        title = f"Pokemon {set_name}"

    page_url = "https://en.wikipedia.org/wiki/" + quote_plus(title.replace(" ", "_"))
    try:
        resp = requests.get(page_url, headers=headers, timeout=10)
        resp.raise_for_status()
    except Exception:
        return {"num_cards": None, "release_date": None, "notes": None, "source": None}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Find infobox and extract rows
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
                # extract first number
                m = re.search(r"([0-9,]+)", val)
                if m:
                    try:
                        num_cards = int(m.group(1).replace(",", ""))
                    except Exception:
                        num_cards = None
            if any(k in key for k in ("released", "release date", "release")) and not release_date:
                release_date = val

    # Scan page text for notes about limited runs, reprints, or rarity
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
    """Return the top `top_n` most expensive single-card listings for a set.

    Attempts to parse the PriceCharting set page for product links and
    associated prices. Filters out entries that look like sealed products
    (Box, Pack, Set, Booster) to focus on single cards.

    Returns a dict: {"top_cards": [{"name": str, "price": float}], "sum_top": float, "avg_top": float}
    If parsing fails, returns empty results.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)"
    }

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

    # Find product links (PriceCharting product pages often contain '/product/')
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/product/" in href and a.get_text(strip=True):
            name = a.get_text(strip=True)
            # ignore sealed/set/box listings
            if re.search(r"\b(box|booster|pack|set|sealed|bundle)\b", name, re.I):
                continue
            # try to find a nearby price in the parent elements
            price = None
            # Check parent td/tr
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

    # If we found nothing via product links, try scanning table rows for card entries
    if not candidates:
        rows = soup.find_all("tr")
        for tr in rows:
            txt = tr.get_text(separator=" ")
            if re.search(r"\b(box|booster|pack|set|sealed)\b", txt, re.I):
                continue
            price = parse_price_from_text(txt)
            if price is None:
                continue
            # try to extract a plausible name (first link or leading text)
            a = tr.find("a")
            if a and a.get_text(strip=True):
                name = a.get_text(strip=True)
            else:
                name = txt.strip().split(" \n")[0][:80]
            candidates.append({"name": name, "price": price})

    # Deduplicate by name (keep max price)
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
    """Check recent social media/news for mentions of a reprint for `set_name`.

    Strategy:
    - Prefer using `snscrape` (Python module or CLI) to search recent tweets for the phrase
      '"<set_name> reprint"' or '<set_name> reprint'. If snscrape is not available, return
      an informational note that the check couldn't be run.
    - In a production setup, you'd wire official RSS/news feeds, the official Pokemon TCG
      site, or authenticated social APIs (Twitter API, Mastodon, etc.) and apply trust
      scoring for sources. This function is a lightweight proxy for that behavior.

    Returns a dict: {"warning": bool, "matches": [ {"source": url, "text": text} ], "note": str|None}
    """
    query = f'"{set_name}" reprint OR {set_name} reprint'
    since_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
    results = []

    # Attempt 1: use snscrape Python module if available (DISABLED - TODO: fix type issues)
    '''
    try:
        import snscrape.modules.twitter as sntwitter
        scraper_query = f'{query} since:{since_date}'
        scraper = sntwitter.TwitterSearchScraper(scraper_query)
        for i, tweet in enumerate(scraper.get_items()):
            if i >= 20:
                break
            # Only process real Tweet objects (not Tombstone, TweetRef, etc.)
            if hasattr(tweet, 'content') and hasattr(tweet, 'user') and hasattr(tweet, 'id') and hasattr(tweet.user, 'username'):
                text = tweet.content
                url = f"https://twitter.com/{tweet.user.username}/status/{tweet.id}"
                results.append({"source": url, "text": text})
    except Exception:
        pass
    '''
    # Attempt 2: try calling snscrape CLI if installed
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

    # Simple heuristic: if we found any matches, flag a warning.
    if results:
        return {"warning": True, "matches": results, "note": None}
    return {"warning": False, "matches": [], "note": None}


def get_psa_population(card_name: str):
    """Fetch PSA population counts for `card_name`.

    This attempts to query PSA's public population search page and parse
    counts for PSA 10 (Gem Mint) and other grades. If PSA blocks scraping
    or the page is heavily dynamic, the function will return None counts
    and an explanatory error note. In production, prefer an official API
    or a vetted scraper (psa-scrape) that handles PSA's site behavior.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PokemonInvestmentAnalyzer/1.0)",
    }

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
        # look for patterns like 'PSA 10' followed by a number nearby
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
    """Analyze sentiment around `set_name` on Reddit.

    Attempts to use PRAW to fetch recent submissions/comments mentioning the set
    from common subreddits (r/PokeInvesting, r/PokemonTCG). If PRAW/TextBlob
    are not available or credentials are not configured, the function falls
    back to a simple keyword-based scoring on dummy/sample data.

    Returns: {"avg_polarity": float|None, "classification": str, "sample": [texts]}

    Notes:
    - In production, configure PRAW with credentials and consider comment-level
      scraping, rate limits, and profanity filtering. For large-scale analysis
      use a dedicated NLP model or cloud sentiment API.
    """
    positive_keywords = ["good", "great", "bull", "buy", "hype", "pop", "profit", "moon", "win"]
    negative_keywords = ["bad", "sell", "dump", "overvalued", "scam", "bubble", "fear", "loss"]

    texts = []

    # Try PRAW first (requires praw and configured credentials)
    try:
        import praw
        reddit = praw.Reddit()  # assumes praw.ini or env vars configured
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
        # fallback: try Reddit search page scraping (lightweight)
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
            # last fallback: dummy data (so function returns a deterministic shape)
            texts = [f"I love the {set_name} set! Great buy.", f"I think {set_name} is overhyped and might drop."]

    # Sentiment scoring: try TextBlob if available, else keyword scoring
    polarities = []
    sample_texts = texts[:10]
    try:
        from textblob import TextBlob
        for t in texts:
            try:
                blob = TextBlob(str(t))
                sentiment = getattr(blob, "sentiment", None)
                p = getattr(sentiment, "polarity", 0.0) if sentiment is not None else 0.0
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
    """Gather data and compute derived investment metrics for `set_name`.

    Returns a structured dict with numeric metrics and a human-readable summary.
    """
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

    # Derived metrics
    sold_count_30d = ebay.get("count_sold") or 0
    days_window = 30
    daily_sales = sold_count_30d / days_window if sold_count_30d else 0.0
    weekly_sales = daily_sales * 7
    listings_count = listings.get("listings_count") or 0
    days_to_clear = None
    if daily_sales > 0:
        days_to_clear = listings_count / daily_sales if listings_count is not None else None

    # Build summary string
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
        print(json.dumps({"error": "no set name provided"}))
        sys.exit(1)
    set_name = sys.argv[1]
    price = None
    try:
        price = scrape_price_data(set_name)
    except Exception as e:
        # don't fail hard; return error info in JSON
        print(json.dumps({"set": set_name, "error": str(e)}))
        sys.exit(1)

    result = {
        "set": set_name,
        "status": "analyzed",
        "score": 42,
        "booster_box_price": price,
        "tcgplayer_supply": scrape_tcgplayer_listings(f"{set_name} booster box"),
    }
    # Add top chase cards (single-card high values)
    try:
        result["top_chase_cards"] = get_top_chase_cards(set_name, top_n=5)
    except Exception:
        result["top_chase_cards"] = {"top_cards": [], "sum_top": 0.0, "avg_top": None}
    # Add reprint news check
    try:
        result["reprint_news"] = check_reprint_news(set_name)
    except Exception:
        result["reprint_news"] = {"warning": False, "matches": [], "note": "check failed"}
    # Add sentiment analysis
    try:
        result["sentiment"] = analyze_sentiment(set_name)
    except Exception:
        result["sentiment"] = {"avg_polarity": None, "classification": "unknown", "sample": []}
    # Add computed metrics summary
    try:
        result["metrics"] = compute_metrics(set_name)
    except Exception:
        result["metrics"] = {"summary": "metrics computation failed"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
