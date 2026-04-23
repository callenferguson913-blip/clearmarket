import os
import smtplib
from datetime import date, datetime, timezone
from email.mime.text import MIMEText

import anthropic
import yfinance as yf
from dotenv import load_dotenv

from src.database import Recommendation, SessionLocal, User

load_dotenv()

MARKET_TICKERS = ["SPY", "QQQ", "VTI"]


def get_market_data():
    result = {}
    for ticker in MARKET_TICKERS:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d", timeout=10)
            info = stock.fast_info
            result[ticker] = {
                "price": round(info.last_price, 2) if info.last_price else None,
                "week_high": round(hist["Close"].max(), 2) if not hist.empty else None,
                "week_low": round(hist["Close"].min(), 2) if not hist.empty else None,
            }
        except Exception as e:
            print(f"  Warning: could not fetch {ticker}: {e}")
    return result


def get_news():
    headlines = []
    for ticker in ["QQQ", "SPY"]:
        try:
            news = yf.Ticker(ticker).news
            for item in (news or [])[:3]:
                title = item.get("content", {}).get("title") or item.get("title")
                if title:
                    headlines.append(f"- {title}")
        except Exception as e:
            print(f"  Warning: could not fetch news for {ticker}: {e}")
    return headlines[:8]


def build_prompt(user: User, market_data: dict, news: list[str]) -> str:
    market_text = ""
    for ticker, info in market_data.items():
        market_text += f"  {ticker}: ${info['price']} | 5-day range: ${info['week_low']} - ${info['week_high']}\n"

    news_text = "\n".join(news)
    holdings_text = user.holdings if user.holdings else "No current holdings — starting fresh"

    goal_map = {"growth": "Long-term growth", "balanced": "Balanced growth and stability", "safety": "Capital preservation"}
    risk_map = {"low": "Low — prefers stability", "medium": "Medium — comfortable with some volatility", "high": "High — comfortable with volatility for bigger gains"}
    interest_map = {"etfs": "ETFs and index funds", "tech": "Tech stocks", "dividends": "Dividend stocks", "energy": "Energy sector", "mixed": "Mixed — variety of asset types"}

    today = date.today().strftime("%B %d, %Y")
    return f"""You are a personal investment advisor writing a weekly report for a specific investor.
Today's date is {today}.

INVESTOR PROFILE:
- Name: {user.name}
- Weekly investment amount: ${user.weekly_amount}
- Goal: {goal_map.get(user.goal, user.goal)}
- Risk tolerance: {risk_map.get(user.risk, user.risk)}
- Investment interests: {interest_map.get(user.interests, user.interests)}
- Current holdings: {holdings_text}

MARKET DATA:
{market_text}
RECENT NEWS:
{news_text}

Write a personalized weekly investment report with these sections:

1. MARKET OVERVIEW — 3-4 sentences on what the market is doing this week.

2. YOUR PORTFOLIO CHECK-IN — Brief note on how their specific holdings are positioned (or encouragement if starting fresh).

3. THIS WEEK'S OPTIONS — 3 specific investment options for their ${user.weekly_amount}. For each:
   - Ticker and what it is
   - Why it fits THEIR goal and risk tolerance specifically
   - Risk level: Low / Medium / High
   - Suggested dollar amount

4. FINAL RECOMMENDATION — Pick the best one for THIS investor. State what to buy, how much, and why it's right for their specific profile. End this section with a line in exactly this format:
RECOMMENDED_TICKER: XXX

5. WATCH LIST — 2-3 things to monitor this week.

Address them by name. Be direct and personalized — not generic. Write like a knowledgeable friend."""


def generate_report(user: User, market_data: dict, news: list[str]) -> str:
    client = anthropic.Anthropic()
    prompt = build_prompt(user, market_data, news)
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                import time
                print(f"  API overloaded, retrying in 30s... (attempt {attempt + 1}/3)")
                time.sleep(30)
            else:
                raise


def parse_ticker(report: str) -> str | None:
    import re
    match = re.search(r"RECOMMENDED_TICKER[:\s]+([A-Z]{1,5})", report.upper())
    if match:
        return match.group(1).strip()
    return None


def get_current_price(ticker: str) -> float | None:
    try:
        return round(yf.Ticker(ticker).fast_info.last_price, 2)
    except Exception:
        return None


def save_recommendation(db, user_id: int, ticker: str, week_of: datetime):
    price = get_current_price(ticker)
    rec = Recommendation(
        user_id=user_id,
        week_of=week_of,
        ticker=ticker,
        price_at_recommendation=price,
    )
    db.add(rec)
    db.commit()
    print(f"  Saved recommendation: {ticker} @ ${price}")


def update_last_week_results(db, week_of: datetime):
    from sqlalchemy import func
    last_week = db.query(Recommendation).filter(
        Recommendation.week_of < week_of,
        Recommendation.price_one_week_later == None,
    ).all()
    for rec in last_week:
        current_price = get_current_price(rec.ticker)
        if current_price and rec.price_at_recommendation:
            rec.price_one_week_later = current_price
            rec.percent_change = round(
                (current_price - rec.price_at_recommendation) / rec.price_at_recommendation * 100, 2
            )
            print(f"  Updated {rec.ticker}: {rec.percent_change:+.2f}%")
    db.commit()


def send_email(to_email: str, name: str, report: str):
    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_APP_PASSWORD")

    msg = MIMEText(report)
    msg["Subject"] = "📈 Your ClearMarket Weekly Report"
    msg["From"] = f"ClearMarket <{sender}>"
    msg["To"] = to_email

    with smtplib.SMTP("smtp.mail.me.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, to_email, msg.as_string())

    print(f"  Sent to {name} ({to_email})")


def run():
    print("Fetching market data...")
    market_data = get_market_data()

    print("Fetching news...")
    news = get_news()

    db = SessionLocal()
    week_of = datetime.now(timezone.utc)

    print("Updating last week's recommendation results...")
    update_last_week_results(db, week_of)

    test_mode = os.getenv("TEST_MODE", "").lower() == "true"
    query = db.query(User).filter(User.active)
    if test_mode:
        query = query.filter(User.email == "callenferguson@icloud.com")
        print("TEST MODE — only sending to callenferguson913@gmail.com\n")
    users = query.all()
    print(f"Sending reports to {len(users)} user(s)...\n")

    for user in users:
        print(f"  Generating report for {user.name}...")
        report = generate_report(user, market_data, news)
        send_email(user.email, user.name, report)
        ticker = parse_ticker(report)
        print(f"  Parsed ticker: {ticker}")
        if ticker:
            save_recommendation(db, user.id, ticker, week_of)
        else:
            print(f"  Warning: could not parse ticker from report")

    db.close()
    print("\nDone.")


if __name__ == "__main__":
    run()
