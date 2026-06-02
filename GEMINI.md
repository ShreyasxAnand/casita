# Project Instructions: Casita (San Jose ADU MVP)

This project is a standalone San Jose address-to-ADU studio. It builds a parcel-local 3D scene from outlines, computes buildable zones, and enables interactive ADU placement.

## Core Architecture
- **Backend:** FastAPI (Python 3.10+)
- **Frontend:** Vanilla JS/CSS (mounted at `/static`)
- **Main Flow:**
  1. Geocode address via ArcGIS.
  2. Fetch parcel and building data from City of San Jose/Santa Clara County GIS services.
  3. Generate site model with setbacks and buildable zones in UTM coordinates.
  4. Serve geometry and imagery metadata to frontend.

## Key Files
- `backend/app/main.py`: FastAPI entry point and routes.
- `backend/app/site_model.py`: Core logic for geometry processing, setbacks, and ADU placement.
- `backend/app/services/site_pipeline.py`: Orchestrates external data fetching and model building.
- `backend/app/cities/`: City-specific adapters (currently focused on San Jose).
- `data/`: Bundled GeoJSON samples for testing.

## Development Workflows
- **Running locally:** `python -m uvicorn app.main:app` from `backend/` directory.
- **Testing:** `./venv/bin/python -m unittest discover -s tests -v` from project root.
- **Sample Data:** Default sample is 1214 Alderbrook Ln (APN 37329056).

## Conventions
- Use UTM for local geometry calculations (meters).
- Use WGS84 for external GIS service interactions (degrees).
- Prefer composition over complex inheritance in city adapters.
- Maintain `SITE_CONTEXT.md` for current sample site details.
