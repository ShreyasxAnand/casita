"""San Jose ADU compliance adapter.

Wires the San Jose ArcGIS clients (parcels, buildings, zoning, designations,
permits, code enforcement) and the Bulletin #210 checklist together behind
the city-agnostic `CityAdapter` Protocol.
"""

from app.cities.san_jose.adapter import SAN_JOSE_ADAPTER

__all__ = ["SAN_JOSE_ADAPTER"]
