"""San Francisco ADU compliance adapter — scaffolding only.

When implemented, this will hit DataSF for parcels (data.sfgov.org dataset
acdm-wktn), the SF Planning zoning map service, and the SF Building Permits
dataset. Checklist will follow the SF Planning ADU Information Packet plus the
state-law baseline in `app.rules_common.state_standards`.
"""

from app.cities._stub import StubAdapter

SF_ADAPTER = StubAdapter(
    name="sf",
    display_name="San Francisco",
    docs_url="https://sfplanning.org/accessory-dwelling-units",
)
