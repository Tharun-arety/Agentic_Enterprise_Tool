"""Business domains. Each owns its models, schemas, services, routes and tools.

A domain package may import from `app.core` and from domains it genuinely
depends on (knowledge -> pdm for the `related_part` link, ecm -> pdm for the
items a change affects). It must not import from `app.agents` or `app.tools`:
the dependency runs the other way, so that the tool registry can be assembled
from the domains rather than the domains knowing they are exposed as tools.
"""
