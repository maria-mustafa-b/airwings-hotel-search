from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.models.search import HotelSearch

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Airwings Hotel Search",
    version="0.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": None},
    )


@app.post("/search")
def search_hotels(
    request: Request,
    city: str = Form(...),
    hotel_name: str = Form(""),
    check_in: date = Form(...),
    check_out: date = Form(...),
    rooms: int = Form(...),
    adults: int = Form(...),
    children: int = Form(...),
):
    try:
        search = HotelSearch(
            city=city.strip(),
            hotel_name=hotel_name.strip() or None,
            check_in=check_in,
            check_out=check_out,
            rooms=rooms,
            adults=adults,
            children=children,
        )
    except ValidationError as error:
        message = error.errors()[0]["msg"]

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": message},
            status_code=422,
        )

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={"search": search},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)
