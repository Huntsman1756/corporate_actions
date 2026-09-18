"""Adaptadores live de fuentes publicas (P9).

Cada adapter refleja la semantica de descubrimiento ya probada de su
fuente (P9.0). La red pasa por un ``fetcher`` inyectable: en produccion
``urllib_fetcher``; en tests, fixtures offline. Nada de scraping
generico ni de navegador.
"""
