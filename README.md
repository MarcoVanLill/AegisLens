# Dota 2 Item Advisor

A local, advisory-only MVP that combines manually supplied match context, optional HUD screenshot extraction, original local strategy notes, and deterministic item ranking. It does not read process memory, inject code, intercept packets, control the mouse or keyboard, purchase items, reveal hidden information, bypass anti-cheat, or render an in-game overlay.

The server binds to `127.0.0.1` by default. The application is designed for Windows host capture with Dota 2 in **borderless-windowed mode**.

> Data notice: every seeded item, hero, cost, component, and strategy record is labeled `demo-2026.1`. It demonstrates the recommendation system and is **not a claim about the current live Dota 2 patch**.

## Quick start

Requirements: Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```powershell
cd "D:\CODE\AI engineering\PythonProjects\AegisLens"
uv sync --extra dev
Copy-Item .env.example .env
uv run uvicorn dota_advisor.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Manual entry and deterministic recommendations work without Gemini.

Optional screenshot extraction:

```powershell
# Edit .env and set this value; never commit the file.
GEMINI_API_KEY=your-key
```

The provider adapter uses Google's current `google-genai` SDK pattern: local PNG bytes become `types.Part.from_bytes(...)`, and `GenerateContentConfig` supplies a Pydantic response schema. Provider code is isolated in `vision.py`; malformed output is rejected by Pydantic rather than accepted or repaired silently.

## Typical workflow

1. Select your hero, role, visible enemies, inventory, gold, level, and game time.
2. Click **Save context & recommend** for immediate manual-mode advice.
3. Pick the Windows monitor containing Dota 2 and click **Capture once**, or start periodic capture.
4. If crops do not line up with your HUD, open **Calibrate HUD regions** and adjust normalized coordinates.
5. Expand score breakdowns and retrieved passages to inspect the evidence.

Only the inventory, gold, and game-time regions participate in change detection. An unchanged HUD skips expensive extraction. The default capture interval is 5 seconds and the recommendation cooldown is 45 seconds; configure both in `.env`.

## CLI

```powershell
uv run dota-advisor serve --reload
uv run dota-advisor capture-once --monitor 1 --force
uv run dota-advisor watch --monitor 1 --interval 5
uv run dota-advisor ingest .\my-strategy-notes.json
uv run dota-advisor reset-db
```

`ingest` expects a JSON array matching the `StrategyDocument` model. `reset-db` deletes only the configured SQLite database and its WAL sidecars, then rebuilds seeded demonstration data.

## Configuration

Environment variables use the `DOTA_ADVISOR_` prefix except the standard `GEMINI_API_KEY`.

| Variable | Default | Purpose |
|---|---:|---|
| `DOTA_ADVISOR_HOST` | `127.0.0.1` | Local bind address |
| `DOTA_ADVISOR_CAPTURE_INTERVAL_SECONDS` | `5` | Watch-loop interval |
| `DOTA_ADVISOR_RECOMMENDATION_COOLDOWN_SECONDS` | `45` | Minimum time between automatic reranks |
| `DOTA_ADVISOR_CHANGE_THRESHOLD` | `0.025` | Mean normalized ROI difference |
| `DOTA_ADVISOR_CONFIDENCE_THRESHOLD` | `0.65` | Minimum field confidence accepted from vision |
| `DOTA_ADVISOR_MONITOR_INDEX` | `1` | Default physical monitor |
| `DOTA_ADVISOR_DEBUG_SAVE_CROPS` | `false` | Persist cropped HUD regions only |
| `DOTA_ADVISOR_REGIONS_PATH` | `config/hud_regions.json` | Normalized ROI configuration |
| `DOTA_ADVISOR_DATABASE_PATH` | `.data/advisor.db` | SQLite items, FTS5 notes, and latest results |
| `DOTA_ADVISOR_GEMINI_MODEL` | `gemini-2.5-flash` | Configured multimodal model |

Full screenshots are never persisted by the application. If debug crop persistence is enabled, only the configured HUD crops are written under `.data/debug-crops/`.

## Capture and calibration

The included layout targets a 1920×1080, 16:9 reference with a conventional UI scale. Coordinates are normalized (`x`, `y`, `width`, `height` from 0 to 1), so they scale to other resolutions but may still need calibration for HUD scale, aspect ratio, or custom HUD skins.

If a frame is black or nearly uniform, the request fails with an actionable message. Use borderless-windowed mode, keep the game visible, select the correct display, and check Windows capture/privacy settings. Exclusive fullscreen commonly produces black capture on some systems.

## Architecture

The runtime path is:

```text
CaptureService -> normalized crops -> ChangeDetector -> VisionExtractor
  -> confidence-aware state merge -> SQLite FTS5 StrategyRetriever
  -> deterministic RecommendationEngine -> ExplanationService
  -> MatchStateStore -> API/dashboard
```

Main boundaries are protocols or replaceable services: `CaptureService`, `ChangeDetector`, `VisionExtractor`, `ItemRepository`, `StrategyRetriever`, `RecommendationEngine`, `ExplanationService`, and `MatchStateStore`. `FakeVisionExtractor` provides deterministic, credential-free tests. `LocalVisionExtractor` performs OpenCV preprocessing and deliberately reports low confidence until OCR or item templates are supplied.

Ranking exposes normalized subscores for threat coverage, hero synergy, role fit, game phase, affordability, component affordability, and strategy support. Duplicate, redundant, role-inappropriate, and unrealistic build-up penalties are kept in `RecommendationWeights`, not scattered through the engine.

## API

The OpenAPI explorer is at `/docs`. Key endpoints:

- `GET /health/live`, `GET /health/ready`
- `GET /api/v1/catalog`, `GET /api/v1/monitors`
- `GET /api/v1/state`, `PUT /api/v1/state/manual`
- `POST /api/v1/screenshots/analyze`
- `POST /api/v1/capture/once`, `/start`, `/stop`; `GET /api/v1/capture/status`
- `POST /api/v1/recommendations`; `GET /api/v1/recommendations/latest`
- `GET /api/v1/retrieval/latest`
- `GET /api/v1/regions`, `PUT /api/v1/regions`

Only one capture loop may run at a time. Application shutdown cancels it cleanly.

## Updating demo data for a real patch

1. Create a new explicit version string; do not overwrite the meaning of `demo-2026.1`.
2. Verify item costs, components, tags, and hero profiles against authorized current sources.
3. Add or revise original strategy notes in `seeds.py`, preserving source IDs and version metadata.
4. Update `DOTA_ADVISOR_DATA_VERSION`, rebuild with `uv run dota-advisor reset-db`, and run tests.
5. Review scoring behavior with curated match scenarios before presenting it as patch-specific advice.

The `StrategyRetriever` protocol is intentionally independent of SQLite FTS5 so a future embedding retriever can be added without changing the recommendation engine.

## Quality checks

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

