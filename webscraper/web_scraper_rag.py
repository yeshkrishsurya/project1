import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import time
from tqdm import tqdm
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

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


def get_rendered_html(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    driver = webdriver.Chrome(options=options)
    driver.get(url)
    time.sleep(2)  # Wait for JS to load
    html = driver.page_source
    driver.quit()
    return html


def scrape_url(url):
    try:
        html = get_rendered_html(url)
        soup = BeautifulSoup(html, 'html.parser')
        # Docsify main content is in .markdown-section
        content = soup.select_one('.markdown-section')
        text = content.get_text(separator=' ', strip=True) if content else ''
        links = extract_links(soup, url)
        return {'url': url, 'text': text, 'links': list(links)}
    except Exception as e:
        print(f"Failed to scrape {url}: {e}")
        return None


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


def crawl(start_url, max_pages=MAX_PAGES, existing_urls=None):
    if existing_urls is None:
        existing_urls = set()
    visited = set()
    to_visit = [start_url]
    new_dataset = []

    with tqdm(total=max_pages, desc="Crawling new URLs") as pbar:
        while to_visit and len(new_dataset) < max_pages:
            url = to_visit.pop(0)
            if url in visited:
                continue
            result = scrape_url(url)
            visited.add(url)
            if result and result['url'] not in existing_urls:
                new_dataset.append(result)
                existing_urls.add(result['url'])
                pbar.update(1)
            # Always add new links to queue for further crawling
            if result:
                for link in result['links']:
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


def main():
    #start_url = input("Enter the starting URL: ").strip()
    start_url = r"https://tds.s-anand.net/#/2025-01/"
    existing_urls = load_existing_dataset()
    new_dataset = crawl(start_url, existing_urls=existing_urls)
    save_dataset_append(new_dataset)

if __name__ == "__main__":
    main()
