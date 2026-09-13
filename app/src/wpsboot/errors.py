from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from wpsboot.templating import templates


class ErrorBody(BaseModel):
    errors: list[str]


class ApiError(Exception):
    def __init__(
        self, status_code: int, errors: list[str], headers: dict[str, str] | None = None
    ) -> None:
        super().__init__("; ".join(errors))
        self.status_code = status_code
        self.errors = errors
        self.headers = headers


def _wants_html(request: Request) -> bool:
    return not request.url.path.startswith("/api/")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def handle_api_error(request: Request, exc: ApiError) -> Response:
        return JSONResponse(
            ErrorBody(errors=exc.errors).model_dump(), exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        messages = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"] if part not in ("body", "path"))
            messages.append(f"{location}: {error['msg']}" if location else error["msg"])
        if _wants_html(request):
            return _html_error(request, 404)
        return JSONResponse(ErrorBody(errors=messages).model_dump(), 422)

    @app.exception_handler(HTTPException)
    def handle_http_error(request: Request, exc: HTTPException) -> Response:
        if _wants_html(request) and exc.status_code in (404, 405):
            return _html_error(request, exc.status_code)
        return JSONResponse(
            ErrorBody(errors=[str(exc.detail)]).model_dump(), exc.status_code, headers=exc.headers
        )


def _html_error(request: Request, status_code: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "error.html", {"status_code": status_code}, status_code=status_code
    )
