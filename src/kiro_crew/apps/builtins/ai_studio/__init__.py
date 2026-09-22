"""AI Studio — a three-column coding-studio shell over Kiro Crew.

Left column embeds the native chat (real sessions); center and right are the
workbench (project docs edited in place, plus the demo fixture views the first
cut shipped with). The project store — one directory per project under the
data home, seeded with its design docs at creation — lives in ``backend/``.

Required re-export: the gateway's startup scan imports the package and checks
``hasattr(_mod, "register_routes")`` (the crew_companion convention), so the
package must re-export it. Routes register at startup, not on enable; every
handler carries its own enabled check.
"""

from kiro_crew.apps.builtins.ai_studio.backend.routes import (  # noqa: F401
    register_routes,
)
