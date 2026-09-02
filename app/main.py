from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Airwings Hotel Search",
    version="0.1.0",
)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Airwings Hotel Search</title>
        </head>
        <body>
            <h1>Airwings Hotel Search</h1>
            <p>The application is running successfully.</p>
        </body>
    </html>
    """


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}
