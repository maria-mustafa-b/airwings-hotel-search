from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.models.search import HotelSearch
from app.providers.hotelrack_live import HotelrackLiveBrowser

BASE_DIR = Path(__file__).resolve().parent

hotelrack_browser = HotelrackLiveBrowser()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await hotelrack_browser.start()
        app.state.hotelrack = hotelrack_browser
    except Exception as error:
        print(f"[Hotelrack] Browser failed to start: {error}")
        app.state.hotelrack = None

    yield

    if app.state.hotelrack is not None:
        await app.state.hotelrack.stop()


app = FastAPI(
    title="Airwings Hotel Search",
    version="0.1.0",
    lifespan=lifespan,
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
async def search_hotels(
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
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"error": error.errors()[0]["msg"]},
            status_code=422,
        )
    provider = request.app.state.hotelrack

    if provider is None:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "The Hotelrack backend browser is unavailable."
            },
            status_code=503,
        )

    if search.rooms != 1:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "The current prototype supports one room per search."
            },
            status_code=422,
        )

    try:
        hotels = await provider.search_hotels(
            city=search.city,
            hotel_name=search.hotel_name,
            check_in=search.check_in,
            check_out=search.check_out,
            adults=search.adults,
            children=search.children,
        )
    except Exception as error:
        print(f"[Hotelrack] Search failed: {error}")

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": (
                    "Hotelrack search failed. Confirm that the administrator "
                    "is logged in and try again."
                )
            },
            status_code=502,
        )

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "search": search,
            "hotels": hotels,
        },
    )


@app.get("/api/hotelrack/status")
async def hotelrack_status(request: Request):
    provider = request.app.state.hotelrack

    if provider is None:
        return {
            "running": False,
            "authenticated": False,
            "message": "Hotelrack browser failed to start.",
        }

    return await provider.status()


@app.post("/rooms")
async def room_rates(
    request: Request,
    hotel_name: str = Form(...),
):
    provider = request.app.state.hotelrack

    if provider is None:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "The Hotelrack backend is unavailable."
            },
            status_code=503,
        )

    try:
        rooms = await provider.get_room_rates(
            hotel_name=hotel_name,
        )
    except Exception as error:
        print(f"[Hotelrack] Room-rate retrieval failed: {error}")

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": (
                    "Room rates could not be retrieved. "
                    "Please perform the hotel search again."
                )
            },
            status_code=502,
        )

    return templates.TemplateResponse(
        request=request,
        name="rooms.html",
        context={
            "hotel_name": hotel_name,
            "rooms": rooms,
        },
    )

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)
