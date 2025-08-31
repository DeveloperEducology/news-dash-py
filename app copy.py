from flask import Flask, render_template, request, redirect, url_for
from flask_session import Session
from deep_translator import GoogleTranslator
import feedparser
import nltk
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lex_rank import LexRankSummarizer
from pymongo import MongoClient
from bson.objectid import ObjectId
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

# --- Auto-download required NLTK models ---
for resource in ["punkt", "stopwords"]:
    try:
        nltk.data.find(f"tokenizers/{resource}")
    except LookupError:
        nltk.download(resource)

app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# --- MongoDB ---
MONGO_URI = "mongodb+srv://vijaymarka:admin123@cluster0.ivjiolu.mongodb.net/News?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db = client["News"]
raw_articles = db["raw_articles"]

# --- Languages & RSS ---
LANGUAGES = {"en": "English", "te": "Telugu", "hi": "Hindi", "fr": "French", "de": "German", "es": "Spanish"}
RSS_SOURCES = {
    "BBC": "http://feeds.bbci.co.uk/news/rss.xml",
    "NDTV": "https://feeds.feedburner.com/ndtvnews-top-stories"
}

# --- Telugu Categories ---
CATEGORIES = {
    "రాజకీయాలు": ["ప్రధాని", "మంత్రి", "ఎన్నికలు", "పార్టీ", "విపక్షం", "రాజకీయాలు"],
    "క్రీడలు": ["క్రీడలు", "మ్యాచ్", "క్రికెట్", "ఫుట్‌బాల్", "హాకీ", "ప్లేయర్", "టోర్నమెంట్"],
    "సినిమా": ["సినిమా", "హీరో", "హీరోయిన్", "దర్శకుడు", "ఫిల్మ్", "పాట"],
    "సాంకేతికం": ["టెక్నాలజీ", "సాంకేతికం", "మొబైల్", "AI", "ఆర్టిఫిషియల్ ఇంటెలిజెన్స్", "కంప్యూటర్", "సాఫ్ట్‌వేర్"],
    "వ్యాపారం": ["బ్యాంక్", "మార్కెట్", "వ్యాపారం", "అర్థవ్యవస్థ", "స్టాక్", "రూపాయి"],
    "ఆరోగ్యం": ["ఆసుపత్రి", "ఆరోగ్యం", "డాక్టర్", "వ్యాధి", "టీకా", "హెల్త్"],
    "విద్య": ["పరీక్షలు", "విద్య", "పాఠశాల", "కాలేజీ", "విశ్వవిద్యాలయం"]
}

# --- Summarization ---
def summarize_text(text, sentence_count=3):
    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = LexRankSummarizer()
    summary = summarizer(parser.document, sentence_count)
    return " ".join(str(sentence) for sentence in summary)

def summarize_to_words(text, max_words=50):
    summary = summarize_text(text, sentence_count=5)
    words = summary.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "..."
    return summary

# --- Telugu Classifier ---
def classify_telugu_article(text):
    text = text.lower()
    scores = {cat: 0 for cat in CATEGORIES}
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw.lower() in text:
                scores[cat] += 1
    best_cat = max(scores, key=scores.get)
    return best_cat if scores[best_cat] > 0 else "ఇతరాలు"

# --- RSS fetch function ---
def fetch_rss_feeds():
    target_lang = "te"
    max_words = 60
    for source_choice, rss_url in RSS_SOURCES.items():
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:10]:
            if not entry.get("link"):
                continue  # Skip articles without links
            source_text = (entry.title or "") + ". " + (entry.get("summary","") or "")
            text_to_translate = summarize_to_words(source_text, max_words)
            translated_text = GoogleTranslator(source="en", target=target_lang).translate(text_to_translate)
            category = classify_telugu_article(translated_text)
            article_doc = {
                "title": entry.title or "",
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary_en": summarize_to_words(source_text, max_words),
                "summary_translated": translated_text,
                "target_lang": target_lang,
                "category": category,
                "source": source_choice
            }
            # Upsert to avoid duplicates
            raw_articles.update_one(
                {"link": entry.link, "target_lang": target_lang},
                {"$set": article_doc},
                upsert=True
            )

# --- Scheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_rss_feeds, trigger="interval", minutes=15)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# --- Routes ---
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST" and "delete" not in request.form:
        target_lang = request.form.get("language", "te")
        max_words = int(request.form.get("max_words", 60))
        translate_full = request.form.get("translate_full") == "on"
        source_choice = request.form.get("source", "BBC")
        feed = feedparser.parse(RSS_SOURCES[source_choice])
        for entry in feed.entries[:10]:
            if not entry.get("link"):
                continue
            source_text = (entry.title or "") + ". " + (entry.get("summary","") or "")
            text_to_translate = source_text if translate_full else summarize_to_words(source_text, max_words)
            translated_text = GoogleTranslator(source="en", target=target_lang).translate(text_to_translate)
            category = classify_telugu_article(translated_text) if target_lang=="te" else "General"
            article_doc = {
                "title": entry.title or "",
                "link": entry.link,
                "published": entry.get("published", ""),
                "summary_en": summarize_to_words(source_text, max_words),
                "summary_translated": translated_text,
                "target_lang": target_lang,
                "category": category,
                "source": source_choice
            }
            raw_articles.update_one(
                {"link": entry.link, "target_lang": target_lang},
                {"$set": article_doc},
                upsert=True
            )

    # --- Search & filter ---
    query = {}
    keyword = request.args.get("keyword","").strip()
    category_filter = request.args.get("category","").strip()
    if keyword:
        query["$or"] = [
            {"title": {"$regex": keyword, "$options":"i"}},
            {"summary_translated": {"$regex": keyword, "$options":"i"}}
        ]
    if category_filter:
        query["category"] = category_filter

    # --- Pagination ---
    page = int(request.args.get("page",1))
    per_page = int(request.args.get("per_page",10))
    total = raw_articles.count_documents(query)
    articles_cursor = raw_articles.find(query).sort("published",-1).skip((page-1)*per_page).limit(per_page)
    articles = list(articles_cursor)
    for a in articles:
        a["_id"] = str(a["_id"])

    return render_template("index.html",
        articles=articles,
        languages=LANGUAGES,
        sources=RSS_SOURCES,
        categories=list(CATEGORIES.keys()),
        selected_category=category_filter,
        keyword=keyword,
        page=page,
        per_page=per_page,
        total_pages=(total + per_page - 1)//per_page
    )

@app.route("/delete/<id>", methods=["POST"])
def delete_article(id):
    raw_articles.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("index"))

@app.route("/edit", methods=["POST"])
def edit_article():
    data = request.form
    raw_articles.update_one(
        {"_id": ObjectId(data["id"])},
        {"$set": {
            "title": data.get("title",""),
            "summary_en": data.get("summary_en",""),
            "summary_translated": data.get("summary_translated",""),
            "category": data.get("category","General"),
            "target_lang": data.get("target_lang","te")
        }}
    )
    return redirect(url_for("index"))

if __name__=="__main__":
    app.run(debug=True)
