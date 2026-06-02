"""Oakland ADU compliance adapter — scaffolding only.

When implemented, this will hit Oakland's OpenData portal (data.oaklandca.gov)
for parcels and zoning, plus the Alameda County assessor for APN lookups.
Checklist will follow Oakland's ADU Bulletin and the CA state-law baseline
in `app.rules_common.state_standards`.
"""

from app.cities._stub import StubAdapter

OAKLAND_ADAPTER = StubAdapter(
    name="oakland",
    display_name="Oakland",
    docs_url="https://www.oaklandca.gov/topics/accessory-dwelling-units-adus",
)
