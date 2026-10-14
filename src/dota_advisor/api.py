from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from .capture import ScreenCaptureError
from .config import Settings
from .container import AppContainer, build_container
from .models import (
    AnalysisOutcome,
    CaptureStartRequest,
    CaptureStatus,
    ManualStateInput,
    MatchState,
    Recommendation,
    RegionConfiguration,
    RetrievedPassage,
    Role,
)

PACKAGE_DIRECTORY = Path(__file__).resolve().parent


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def create_app(
    container: AppContainer | None = None,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    active_container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.container.advisor.shutdown()

    app = FastAPI(
        title="Dota 2 Item Advisor",
        version="0.1.0",
        description="Local, advisory-only Dota 2 item recommendations.",
        lifespan=lifespan,
    )
    app.state.container = active_container
    templates = Jinja2Templates(directory=PACKAGE_DIRECTORY / "templates")
    app.mount(
        "/static",
        StaticFiles(directory=PACKAGE_DIRECTORY / "static"),
        name="static",
    )
    app.mount(
        "/debug",
        StaticFiles(directory=active_container.settings.debug_directory, check_dir=False),
        name="debug",
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"data_version": active_container.settings.data_version},
        )

    @app.get("/calibration", response_class=HTMLResponse, include_in_schema=False)
    async def calibration(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="calibration.html",
            context={"data_version": active_container.settings.data_version},
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(active: AppContainer = Depends(get_container)) -> dict[str, object]:
        ready_state = (
            bool(active.item_repository.list_items()) and active.settings.regions_path.exists()
        )
        if not ready_state:
            raise HTTPException(
                status_code=503, detail="Seed data or HUD region configuration is missing."
            )
        return {
            "status": "ready",
            "mode": "gemini" if active.settings.gemini_api_key else "manual/local",
            "data_version": active.settings.data_version,
        }

    @app.get("/api/v1/catalog")
    async def catalog(active: AppContainer = Depends(get_container)) -> dict[str, object]:
        return {
            "heroes": active.item_repository.list_heroes(),
            "items": active.item_repository.list_items(),
            "roles": [role.value for role in Role],
            "data_version": active.settings.data_version,
            "data_notice": "Demonstration data only; not a claim about the current live patch.",
            "confidence_threshold": active.settings.confidence_threshold,
            "capture_interval_seconds": active.settings.capture_interval_seconds,
            "recommendation_cooldown_seconds": active.settings.recommendation_cooldown_seconds,
            "debug_save_crops": active.settings.debug_save_crops,
        }

    @app.get("/api/v1/monitors")
    async def monitors(active: AppContainer = Depends(get_container)) -> list[object]:
        try:
            return active.capture_service.enumerate_monitors()
        except ScreenCaptureError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v1/state", response_model=MatchState | None)
    async def state(active: AppContainer = Depends(get_container)) -> MatchState | None:
        return active.advisor.current_state()

    @app.put("/api/v1/state/manual", response_model=MatchState)
    async def update_manual_state(
        request: ManualStateInput,
        active: AppContainer = Depends(get_container),
    ) -> MatchState:
        return active.advisor.set_manual_state(request)

    @app.post("/api/v1/screenshots/analyze", response_model=AnalysisOutcome)
    async def analyze_screenshot(
        screenshot: UploadFile = File(...),
        force: bool = Query(default=True),
        active: AppContainer = Depends(get_container),
    ) -> AnalysisOutcome:
        content = await screenshot.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Screenshot exceeds the 20 MiB limit.")
        try:
            image = Image.open(BytesIO(content)).convert("RGB")
            return await active.advisor.process_image(image, force=force)
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(
                status_code=400, detail="Upload a valid PNG or JPEG screenshot."
            ) from exc
        except ScreenCaptureError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/capture/once", response_model=AnalysisOutcome)
    async def capture_once(
        monitor_index: int = Query(default=active_container.settings.monitor_index, ge=1),
        force: bool = Query(default=False),
        active: AppContainer = Depends(get_container),
    ) -> AnalysisOutcome:
        try:
            return await active.advisor.capture_once(monitor_index, force=force)
        except ScreenCaptureError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/capture/start", response_model=CaptureStatus)
    async def start_capture(
        request: CaptureStartRequest,
        active: AppContainer = Depends(get_container),
    ) -> CaptureStatus:
        interval = request.interval_seconds or active.settings.capture_interval_seconds
        try:
            return await active.advisor.capture_loop.start(request.monitor_index, interval)
        except ScreenCaptureError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/capture/stop", response_model=CaptureStatus)
    async def stop_capture(active: AppContainer = Depends(get_container)) -> CaptureStatus:
        return await active.advisor.capture_loop.stop()

    @app.get("/api/v1/capture/status", response_model=CaptureStatus)
    async def capture_status(active: AppContainer = Depends(get_container)) -> CaptureStatus:
        return active.advisor.capture_loop.status

    @app.post("/api/v1/recommendations")
    async def recommend(active: AppContainer = Depends(get_container)) -> dict[str, object]:
        try:
            recommendations, passages = active.advisor.generate_recommendations()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"recommendations": recommendations, "retrieved_passages": passages}

    @app.get("/api/v1/recommendations/latest", response_model=list[Recommendation])
    async def latest_recommendations(
        active: AppContainer = Depends(get_container),
    ) -> list[Recommendation]:
        return active.advisor.latest_recommendations()

    @app.get("/api/v1/retrieval/latest", response_model=list[RetrievedPassage])
    async def latest_retrieval(
        active: AppContainer = Depends(get_container),
    ) -> list[RetrievedPassage]:
        return active.advisor.latest_retrieval()

    @app.get("/api/v1/regions", response_model=RegionConfiguration)
    async def get_regions(active: AppContainer = Depends(get_container)) -> RegionConfiguration:
        try:
            return active.capture_service.load_regions()
        except ScreenCaptureError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/v1/regions", response_model=RegionConfiguration)
    async def put_regions(
        configuration: RegionConfiguration,
        active: AppContainer = Depends(get_container),
    ) -> RegionConfiguration:
        active.capture_service.save_regions(configuration)
        active.advisor.change_detector.reset()
        return configuration

    return app
