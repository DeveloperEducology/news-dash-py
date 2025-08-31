import feedparser

BBC_FEED = "http://feeds.bbci.co.uk/news/rss.xml"

def fetch_bbc_news(limit=5):
    feed = feedparser.parse(BBC_FEED)
    articles = []
    for entry in feed.entries[:limit]:
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.published if "published" in entry else None,
            "summary": entry.summary if "summary" in entry else ""
        })
    return articles

if __name__ == "__main__":
    news = fetch_bbc_news()
    for i, item in enumerate(news, start=1):
        print(f"{i}. {item['title']} ({item['published']})")
        print(f"   {item['link']}")
        print(f"   {item['summary']}\n")
