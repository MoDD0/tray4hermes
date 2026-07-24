"""tray4hermes — passive KDE/Plasma tray monitor for Hermes Gateway.

Hermes Gateway is the messaging bridge that ships with Hermes Agent
(Nous Research). This package is a thin controller:

  - reads ~/.hermes/{gateway_state.json, profiles/, config.yaml, logs/gateway.log}
  - writes only ~/.config/tray4hermes/state.json
  - controls the gateway via `systemctl --user`

Nothing else. No token storage, no provider config, no agent logic.
All of that lives in Hermes Agent itself.
"""

from __future__ import annotations

__version__ = "2.0.6"
__all__ = ["__version__"]
