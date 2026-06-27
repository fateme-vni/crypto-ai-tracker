import os
import asyncio
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
import html
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from telegram import Bot
from google import genai

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

DB_FILE = "sent_tweets_ai.txt"

TWITTER_ACCOUNTS = [
    "Zcash","Compound_xyz","Plasma","AskVenice","RadiumFinance", 
    "ethena","Humanityprot","Pumpfun","Mantle_Official","bonk_inu",
    "HyperliquidX","StoryProtocol","opentensor","StoryToken_",
    "arbitrum","CurveFinance","avax","ensdomains","centrifuge",
    "Uniswap","OntologyNetwork","0xPolygon","TrustWallet",
    "trondao","aave","zodl_co","SkyEcosystem","StellarOrg","Dashpay",
    "Ripple","TheSandboxGame","cosmos"
]

# لیست سرورهای فعال Nitter برای پشتیبان‌گیری از یکدیگر
NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.moomoo.me",
    "https://nitter.perennialte.ch"
]

bot = Bot(token=TELEGRAM_BOT_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

def load_sent_tweets():
    if not os.path.exists(DB_FILE):
        return set()
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_tweet(link):
    with open(DB_FILE, 'a', encoding='utf-8') as f:
        f.write(link + '\n')

async def analyze_with_gemini(tweet_text, account):
    prompt = f"""
    You are an expert crypto fundamental analyst. Analyze this tweet from the official project account @{account}:
    "{tweet_text}"
    
    Determine if this tweet contains highly important fundamental news that could affect the project or token value.
    
    CRITERIA TO EVALUATE:
    1. Direct effect on price (Yes/No with brief reason)
    2. Technical update/Mainnet/V2/V3/Protocol changes (Yes/No)
    3. New Partnership/Integration (Yes/No)
    4. Burn or Buyback mechanism mentioned (Yes/No)
    5. Importance Score: Give a score from 1 to 10 based on fundamental impact.
    
    If the Importance Score is less than 4, reply ONLY with the word "IGNORE".
    
    If the score is 4 or higher, provide a Persian (Farsi) response formatted EXACTLY like this (use HTML tags for bolding if needed):
    
    📊 **تحلیل هوشمند جمنای**
    🔹 **اثر مستقیم بر قیمت:** [بله/خیر همراه توضیح خیلی کوتاه]
    🔹 **آپدیت فنی:** [بله/خیر]
    🔹 **همکاری جدید:** [بله/خیر]
    🔹 **توکن‌سوزی یا بای‌بک:** [بله/خیر]
    ⭐️ **نمره اهمیت:** [امتیاز از ۱ تا ۱۰]
    
    📝 **ترجمه خلاصه توییت:**
    [ترجمه روان، کوتاه و دقیق متن توییت به فارسی]
    """
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, 
            lambda: ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error for @{account}: {e}")
        return "IGNORE"

async def fetch_rss_with_retry(account):
    """تلاش برای دانلود فید با سرورهای مختلف Nitter در صورت خرابی"""
    # مخلوط کردن سرورها تا درخواست‌ها پخش بشن
    instances = NITTER_INSTANCES.copy()
    random.shuffle(instances)
    
    for instance in instances:
        try:
            nitter_url = f"{instance}/{account}/rss"
            req = urllib.request.Request(nitter_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            
            loop = asyncio.get_running_loop()
            response_data = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10).read())
            return response_data, instance
        except Exception:
            continue # اگر این سرور خراب بود، برو سراغ بعدی
            
    raise Exception("All Nitter instances failed.")

async def check_single_account(account, sent_tweets, today_date):
    try:
        response_data, used_instance = await fetch_rss_with_retry(account)
        
        root = ET.fromstring(response_data)
        items = root.findall('.//item')[:3]
        
        if not items:
            return

        for item in items:
            title = item.find('title').text if item.find('title') is not None else ""
            tweet_link = item.find('link').text if item.find('link') is not None else ""
            pub_date_text = item.find('pubDate').text if item.find('pubDate') is not None else ""
            
            # پاک‌سازی لینک نیتراسکات و تبدیل به لینک اصلی X
            clean_link = tweet_link
            for inst in NITTER_INSTANCES:
                domain = inst.replace("https://", "")
                if domain in clean_link:
                    clean_link = clean_link.replace(domain, "x.com")
                    break
            if "x.com" not in clean_link:
                # تبدیل‌های متفرقه احتمالی
                clean_link = f"https://x.com/{account}/status/" + tweet_link.split('/status/')[-1] if '/status/' in tweet_link else tweet_link

            if pub_date_text:
                try:
                    tweet_datetime = parsedate_to_datetime(pub_date_text)
                    if tweet_datetime.date() != today_date:
                        continue
                except Exception:
                    pass
            
            if clean_link in sent_tweets:
                continue
            
            tweet_text = title
            if not tweet_text:
                continue
                
            analysis_result = await analyze_with_gemini(tweet_text, account)
            
            if "IGNORE" in analysis_result or len(analysis_result) < 10:
                save_sent_tweet(clean_link)
                sent_tweets.add(clean_link)
                continue
            
            safe_original_text = html.escape(tweet_text)
            
            final_message = (
                f"🤖 **[نسخه AI] توییت جدید از: @{account}**\n\n"
                f"{analysis_result}\n\n"
                f"🇬🇧 **متن انگلیسی:**\n`{safe_original_text}`\n\n"
                f"🔗 <a href='{clean_link}'>لینک توییت در X</a>"
            )
            
            try:
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=final_message, parse_mode="HTML")
                print(f"[+] AI Report sent for @{account} successfully!")
                
                save_sent_tweet(clean_link)
                sent_tweets.add(clean_link)
                
            except Exception as tg_err:
                print(f"Error sending Telegram for @{account}: {tg_err}")
                    
    except Exception as e:
        print(f"Error checking @{account}: {e}")

async def main_pipeline():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking Twitter accounts via Smart Multi-Nitter & Gemini...")
    sent_tweets = load_sent_tweets()
    today_date = datetime.now(timezone.utc).date()
    
    tasks = [check_single_account(account, sent_tweets, today_date) for account in TWITTER_ACCOUNTS]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main_pipeline())
