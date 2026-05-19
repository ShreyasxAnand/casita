"""Adapters for external services (ArcGIS, geocoders, scrapers).

Each client module owns one external dependency and returns plain Python
data structures so services can compose them without coupling to transport
or schema details.
"""
