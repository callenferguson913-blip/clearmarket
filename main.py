import os

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.database import Recommendation, User, get_db, init_db

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    latest = (
        db.query(Recommendation.week_of)
        .filter(Recommendation.percent_change.isnot(None))
        .order_by(Recommendation.week_of.desc())
        .first()
    )
    top_picks = []
    if latest:
        picks = (
            db.query(Recommendation)
            .filter(Recommendation.week_of == latest.week_of)
            .filter(Recommendation.percent_change > 0)
            .order_by(Recommendation.percent_change.desc())
            .all()
        )
        seen = {}
        for p in picks:
            if p.ticker not in seen:
                seen[p.ticker] = p
        top_picks = list(seen.values())[:5]
    return templates.TemplateResponse(request, "index.html", {"top_picks": top_picks})


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
