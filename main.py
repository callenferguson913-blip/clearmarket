import os
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.database import MagicToken, Recommendation, User, get_db, init_db

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    latest_perf = (
        db.query(Recommendation.week_of)
        .filter(Recommendation.percent_change.isnot(None))
        .order_by(Recommendation.week_of.desc())
        .first()
    )
    top_picks = []
    if latest_perf:
        picks = (
            db.query(Recommendation)
            .filter(Recommendation.week_of == latest_perf.week_of)
            .filter(Recommendation.percent_change > 0)
            .order_by(Recommendation.percent_change.desc())
            .all()
        )
        seen = {}
        for p in picks:
            if p.ticker not in seen:
                seen[p.ticker] = p
        top_picks = list(seen.values())[:5]

    latest_week = (
        db.query(Recommendation.week_of)
        .order_by(Recommendation.week_of.desc())
        .first()
    )
    this_week_picks = []
    if latest_week and (not latest_perf or latest_week.week_of > latest_perf.week_of):
        rows = (
            db.query(Recommendation)
            .filter(Recommendation.week_of == latest_week.week_of)
            .all()
        )
        seen = {}
        for r in rows:
            if r.ticker not in seen:
                seen[r.ticker] = r
        this_week_picks = list(seen.values())[:5]

    return templates.TemplateResponse(request, "index.html", {
        "top_picks": top_picks,
        "this_week_picks": this_week_picks,
        "this_week_date": latest_week.week_of.strftime("%B %d, %Y") if latest_week else None,
    })


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request, "signup.html")


@app.post("/signup", response_class=HTMLResponse)
def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    weekly_amount: int = Form(...),
    goal: str = Form(...),
    risk: str = Form(...),
    holdings: str = Form(""),
    interests: str = Form(""),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "That email is already signed up."}
        )

    user = User(
        name=name,
        email=email,
        weekly_amount=weekly_amount,
        goal=goal,
        risk=risk,
        holdings=holdings,
        interests=interests,
    )
    db.add(user)
    db.commit()

    return templates.TemplateResponse(request, "confirmed.html", {"name": name})


@app.get("/settings/{token}", response_class=HTMLResponse)
def settings_page(token: str, request: Request, db: Session = Depends(get_db)):
    magic = db.query(MagicToken).filter(MagicToken.token == token, MagicToken.used == False).first()
    if not magic or magic.expires_at < datetime.now():
        return HTMLResponse("<h2>This link has expired or is invalid. Check your next Monday email for a fresh link.</h2>", status_code=400)
    user = db.query(User).filter(User.id == magic.user_id).first()
    return templates.TemplateResponse(request, "settings.html", {"token": token, "user": user})


@app.post("/settings/{token}", response_class=HTMLResponse)
def settings_save(
    token: str,
    request: Request,
    weekly_amount: int = Form(...),
    goal: str = Form(...),
    risk: str = Form(...),
    interests: str = Form(...),
    holdings: str = Form(""),
    db: Session = Depends(get_db),
):
    magic = db.query(MagicToken).filter(MagicToken.token == token, MagicToken.used == False).first()
    if not magic or magic.expires_at < datetime.now():
        return HTMLResponse("<h2>This link has expired or is invalid.</h2>", status_code=400)
    user = db.query(User).filter(User.id == magic.user_id).first()
    user.weekly_amount = weekly_amount
    user.goal = goal
    user.risk = risk
    user.interests = interests
    user.holdings = holdings
    magic.used = True
    db.commit()
    return templates.TemplateResponse(request, "settings_saved.html", {"name": user.name})
