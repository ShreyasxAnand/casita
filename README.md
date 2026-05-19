# ADU MVP

Clean standalone San Jose address-to-ADU studio.

The main flow is now:

1. Geocode the typed San Jose address with ArcGIS World Geocoding.
2. Fetch the containing parcel from City of San Jose GIS parcels.
3. Fetch building footprints from San Jose Public Works buildings.
4. Build a parcel-local 3D scene with satellite imagery under the parcel.

The app intentionally excludes the old LiDAR, roofer, cache, and job-output
pipeline. LiDAR is not required for the MVP path.

## Run

```powershell
cd aduMVP\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Open:

```text
http://127.0.0.1:8010/
```

## Sample Data

`GET /api/site` loads the bundled sample files for smoke testing:

- `data/parcel.geojson`
- `data/building.geojson`

`POST /api/site` does not use those files. It uses the typed address and live
GIS services, so an arbitrary San Jose parcel should not silently fall back to
the Alderbrook sample.

## Scope

The app builds a parcel-local 3D scene from outlines, displays satellite imagery
under the parcel, computes a buildable zone from setback and house clearance,
and lets the ADU be moved/rotated interactively.

## Live GIS Sources

- Geocoder: ArcGIS World GeocodeServer
- Parcels: City of San Jose `OPN_OpenDataService` layer 270
- Buildings: City of San Jose Public Works `DPW_BasemapServiceWGS` layer 21
- Secondary building fallback: Santa Clara County `SCCBuildings` layer 0, if it
  is online
