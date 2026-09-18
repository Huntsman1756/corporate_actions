"""P10 — delivery adapters (transport boundary).

Cada adapter expone ``deliver(request, dest_config) -> AdapterResult``
y ``CONFIG_KEYS`` (allowlist fail-closed de claves de config).
Ningun adapter persiste nada: el ledger lo hace el dispatcher.
"""
