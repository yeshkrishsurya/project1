import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import time
from tqdm import tqdm
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from datetime import datetime

# Configurable parameters
MAX_PAGES = 50  # Limit to avoid infinite crawling
CRAWL_DELAY = 1  # seconds between requests


def is_valid_url(url):
    parsed = urlparse(url)
    return bool(parsed.netloc) and bool(parsed.scheme)


def extract_links(soup, base_url):
    links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        full_url = urljoin(base_url, href)
        if is_valid_url(full_url):
            links.add(full_url)
    return links


def get_logged_in_driver(login_url, profile_dir="selenium_profile"):
    options = Options()
    # Use a persistent user data directory for Chrome
    options.add_argument(f"--user-data-dir={profile_dir}")
    # Add remote debugging port to help avoid DevToolsActivePort error
    options.add_argument("--remote-debugging-port=9222")
    # Add extra stability options
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-application-cache")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Specify the custom Chrome binary location
    options.binary_location = r"D:\Downloads\chrome-win64\chrome-win64\chrome.exe"
    print(f"[INFO] If you see Chrome crash errors, ensure no other Chrome is using the profile and delete Singleton* files in {profile_dir}/Default/")
    driver = webdriver.Chrome(options=options)
    time.sleep(3)
    driver.get(login_url)
    print(f"[INFO] Using Chrome profile at: {profile_dir}")
    print("If this is your first time, please log in (including Google OAuth) in the opened browser window. Press Enter here when done.")
    input()
    print("Continuing with scraping...")
    return driver


def get_rendered_html(url, driver=None):
    if driver is None:
        # fallback: open a new headless session (not recommended for login-protected pages)
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        time.sleep(2)
        html = driver.page_source
        driver.quit()
        return html
    else:
        driver.get(url)
        time.sleep(2)
        return driver.page_source


def scrape_url(url, start_date=None, end_date=None, driver=None):
    try:
        html = get_rendered_html(url, driver)
        soup = BeautifulSoup(html, 'html.parser')
        posts = []
        breakpoint()
        # Discourse: each post is in <div class="topic-post clearfix ..."> or <div class="topic-body">
        for post_div in soup.find_all('div', class_='topic-post'):
            # Get post content
            content_div = post_div.find('div', class_='cooked')
            if not content_div:
                continue
            text = content_div.get_text(separator=' ', strip=True)
            # Get post date
            time_tag = post_div.find('time')
            if not time_tag or not time_tag.has_attr('datetime'):
                continue
            timestamp = time_tag['datetime']
            # Parse and filter by date
            try:
                post_date = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except Exception:
                continue
            if start_date and post_date < start_date:
                continue
            if end_date and post_date > end_date:
                continue
            # Get post URL (permalink)
            post_id = post_div.get('data-post-id')
            if post_id:
                post_url = url.split('#')[0] + f'/{post_id}'
            else:
                post_url = url
            posts.append({
                'url': post_url,
                'text': text,
                'timestamp': timestamp
            })
        # If not a Discourse topic page, fallback to old logic
        if not posts:
            content = soup.select_one('.markdown-section')
            text = content.get_text(separator=' ', strip=True) if content else ''
            links = extract_links(soup, url)
            posts.append({'url': url, 'text': text, 'timestamp': None, 'links': list(links)})
        return posts
    except Exception as e:
        print(f"Failed to scrape {url}: {e}")
        return []


def load_existing_dataset(filename="rag_dataset.jsonl"):
    existing = set()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'url' in data:
                        existing.add(data['url'])
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return existing


def load_urls_from_jsonl(filename):
    """Load all URLs from a JSONL file into a set."""
    urls = set()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'url' in data:
                        urls.add(data['url'])
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return urls


def crawl(start_url, max_pages=MAX_PAGES, existing_urls=None, driver=None):
    if existing_urls is None:
        existing_urls = set()
    visited = set()
    to_visit = [start_url]
    new_dataset = []
    # Date range for filtering
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 4, 14, 23, 59, 59)

    with tqdm(total=max_pages, desc="Crawling new URLs") as pbar:
        while to_visit and len(new_dataset) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            posts = scrape_url(url, start_date, end_date, driver)
            visited.add(url)
            for post in posts:
                # Use post url for deduplication
                post_url = post['url']
                if post_url not in existing_urls and post.get('text'):
                    new_dataset.append(post)
                    existing_urls.add(post_url)
                    pbar.update(1)
                    if len(new_dataset) >= max_pages:
                        break
            # Always add new links to queue for further crawling
            if posts:
                # Use the first post's links if fallback, else extract links from soup
                if 'links' in posts[0]:
                    links = posts[0]['links']
                else:
                    html = get_rendered_html(url, driver)
                    soup = BeautifulSoup(html, 'html.parser')
                    links = extract_links(soup, url)
                for link in links:
                    if link not in visited and link not in to_visit:
                        to_visit.append(link)
            time.sleep(CRAWL_DELAY)
    return new_dataset


def save_dataset(dataset, filename="rag_dataset.jsonl"):
    with open(filename, 'w', encoding='utf-8') as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"Saved {len(dataset)} records to {filename}")


def save_dataset_append(dataset, filename="rag_dataset.jsonl"):
    with open(filename, 'a', encoding='utf-8') as f:
        for item in dataset:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"Appended {len(dataset)} new records to {filename}")


def extract_post_links_within_date_range(driver, url, start_date, end_date, output_file="filtered_urls.jsonl"):
    """
    Scrolls the main Discourse page, extracts post links with their dates, and saves URLs within the date range.
    Skips URLs already present in output_file.
    """
    import json
    import os

    # Load already collected URLs
    already_collected = load_urls_from_jsonl(output_file)
    driver.get(url)
    time.sleep(2)
    collected = set(already_collected)
    filtered = []
    last_height = driver.execute_script("return document.body.scrollHeight")
    reached_earliest = False
    scroll_count = 0
    print(f"[INFO] Starting extraction from: {url}")

    EXEMPT_URL = "/t/tds-references-guidelines/67216/5"

    while not reached_earliest and scroll_count < 8:
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        topic_rows = soup.find_all('tr', class_='topic-list-item')
        print(f"[DEBUG] Found {len(topic_rows)} topic rows on scroll {scroll_count}")
        for tr in topic_rows:
            a = tr.find('a', class_='post-activity')
            if not a:
                continue
            href = a.get('href')
            if not href:
                continue
            span = a.find('span', attrs={'data-time': True})
            if not span:
                continue
            data_time = span.get('data-time')
            try:
                post_date = datetime.fromtimestamp(int(data_time) / 1000)
            except Exception:
                print(f"[WARN] Could not parse date from data-time: {data_time}")
                continue
            print(f"[TRACE] Post: {href} | Date: {post_date}")
            # Exempt the specific URL from date filtering
            full_url = urljoin(url, href)
            if full_url in collected:
                continue  # Skip already collected
            if EXEMPT_URL in href:
                filtered.append({
                    'url': full_url,
                    'date': post_date.isoformat(),
                    'exempt': True
                })
                collected.add(full_url)
                print(f"[INFO] Collected (exempt): {full_url} | Date: {post_date}")
                continue
            if post_date < start_date:
                print(f"[INFO] Reached post before start_date: {post_date}. Stopping scroll.")
                reached_earliest = True
                break
            if start_date <= post_date <= end_date:
                filtered.append({
                    'url': full_url,
                    'date': post_date.isoformat()
                })
                collected.add(full_url)
                print(f"[INFO] Collected: {full_url} | Date: {post_date}")
        # Scroll down
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count += 1
        print(f"[DEBUG] Scroll {scroll_count} | New height: {new_height}")
        if new_height == last_height:
            print("[INFO] No more content to load. Stopping scroll.")
            break  # No more content to load
        last_height = new_height
    # Save to file (append new only)
    with open(output_file, 'a', encoding='utf-8') as f:
        for item in filtered:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"[SUCCESS] Added {len(filtered)} new filtered URLs to {output_file}")


def extract_articles_for_filtered_urls(driver, filtered_urls_file="filtered_urls.jsonl", output_file="rag_dataset.jsonl"):
    """
    For each URL in filtered_urls.jsonl, visit the URL, extract text from <article> tags, and save as JSONL.
    Skips URLs already present in output_file.
    """
    import json
    from bs4 import BeautifulSoup
    # Load URLs to process
    urls = []
    with open(filtered_urls_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line)
                if 'url' in data:
                    urls.append(data['url'])
            except Exception:
                continue
    # Load already processed URLs
    processed = set()
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'url' in data:
                        processed.add(data['url'])
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    # Visit and extract
    with open(output_file, 'a', encoding='utf-8') as out_f:
        for url in urls:
            if url in processed:
                continue
            try:
                html = get_rendered_html(url, driver)
                soup = BeautifulSoup(html, 'html.parser')
                articles = soup.find_all('article')
                article_texts = [a.get_text(separator=' ', strip=True) for a in articles]
                text = '\n\n'.join(article_texts)
                out_f.write(json.dumps({'url': url, 'text': text}, ensure_ascii=False) + '\n')
                print(f"[INFO] Extracted article for {url}")
            except Exception as e:
                print(f"[ERROR] Failed to extract article for {url}: {e}")


def answer_question_from_dataset(question, dataset_file="rag_dataset.jsonl", top_k=2):
    """
    Given a question, search the dataset for relevant articles and return a JSON object with answer and links.
    """
    import json
    import re
    from collections import Counter

    # Simple keyword extraction from question
    keywords = re.findall(r"\w+", question.lower())
    
    # Load dataset
    docs = []
    with open(dataset_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line)
                if 'text' in data and data['text'].strip():
                    docs.append(data)
            except Exception:
                continue
    # Score docs by keyword overlap
    scored = []
    for doc in docs:
        text = doc['text'].lower()
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scored.append((score, doc))
    scored.sort(reverse=True, key=lambda x: x[0])
    # Prepare links
    links = []
    for _, doc in scored[:top_k]:
        snippet = doc['text'][:200].replace('\n', ' ')
        links.append({
            'url': doc['url'],
            'text': snippet
        })
    # Compose answer (simple version)
    if links:
        answer = f"Based on the discussion, see the following links for details."
    else:
        answer = "No relevant information found in the dataset."
    return {
        "answer": answer,
        "links": links
    }


def main():
    #start_url = input("Enter the starting URL: ").strip()
    start_url = r"https://discourse.onlinedegree.iitm.ac.in/c/courses/tds-kb/34"
    driver = get_logged_in_driver(start_url)
    # Date range for filtering
    start_date = datetime(2025, 1, 1)
    end_date = datetime(2025, 4, 14, 23, 59, 59)
    extract_post_links_within_date_range(driver, start_url, start_date, end_date)
    # After extracting URLs, visit each and extract <article> text, save as {url, text}
    extract_articles_for_filtered_urls(driver, filtered_urls_file="filtered_urls.jsonl", output_file="rag_dataset.jsonl")
    driver.quit()

if __name__ == "__main__":
    main()