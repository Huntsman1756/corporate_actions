"""DATE_MISBINDING: ligadura rol <-> fecha por predicado y 'claimed'.

Una fecha pertenece a la etiqueta de rol que la predica; la fecha del
rol adyacente (record, fin de plazo, anuncio) no puede ser emitida como
ex_date/record_date aunque sea la siguiente fecha tras la etiqueta.
"""
from __future__ import annotations

from ca_es.sources.parsers.labeled_dates import best_role_date


def test_ex_date_before_label_record_date_after() -> None:
    text = (
        "siendo el día 16 de abril de 2026 el ex - date, es decir, la "
        "fecha a partir de la cual las acciones se negociarán sin derecho "
        "a percibir dividendo y por tanto será el 17 de abril de 2026, la "
        "fecha de corte o record– date."
    )
    assert best_role_date(text, "EX_DATE")["iso"] == "2026-04-16"
    assert best_role_date(text, "RECORD_DATE")["iso"] == "2026-04-17"


def test_ex_date_bullet_date_precedes_label() -> None:
    text = (
        "el 15 de mayo de 2026 tendrán derecho a participar. "
        "• 14 de mayo de 2026. Comienzo del periodo de negociación de los "
        "derechos. Fecha desde la cual (inclusive) las acciones cotizan "
        "“ex-cupón” (ex date). "
        "• 25 de mayo de 2026. Fin del plazo para solicitar la retribución."
    )
    assert best_role_date(text, "EX_DATE")["iso"] == "2026-05-14"


def test_record_date_adjacent_parenthetical_label() -> None:
    text = (
        "figuren legitimados como accionistas en los registros de "
        "Iberclear el 15 de mayo de 2026 (record date), pero no respecto "
        "de los adquiridos. "
        "• 1 de junio de 2026. Fin del periodo de negociación de derechos."
    )
    assert best_role_date(text, "RECORD_DATE")["iso"] == "2026-05-15"


def test_descriptive_ex_dividendo_does_not_bind_announcement() -> None:
    text = (
        "se determinará sobre la base del número de acciones en "
        "circulación en la fecha ex-dividendo, y se prevé anunciarlo el "
        "15 de mayo de 2026. Las acciones cotizarán ex-dividendo a partir "
        "del 18 de mayo de 2026 en las Bolsas Españolas."
    )
    assert best_role_date(text, "EX_DATE")["iso"] == "2026-05-18"


def test_record_date_predicated_beats_parenthetical_alias() -> None:
    text = (
        "la fecha de registro del dividendo (dividend record date) será "
        "el 19 de mayo de 2026. 20 de mayo de 2026 (9:00 CEST) - 2 de "
        "junio de 2026 : Periodo de elección."
    )
    assert best_role_date(text, "RECORD_DATE")["iso"] == "2026-05-19"


def test_no_label_no_date() -> None:
    assert best_role_date("se repartirá un dividendo.", "EX_DATE") is None


def test_payment_date_label_binds_following_date() -> None:
    text = "Fecha de pago: 15 de junio de 2026 en cada entidad."
    assert best_role_date(text, "PAYMENT_DATE")["iso"] == "2026-06-15"


def test_conjoined_label_phrase_does_not_steal_previous_date() -> None:
    # "fecha ex-dividendo el 20 y fecha de registro el 21": el 20
    # pertenece a la primera frase; la conjuncion 'y' abre otra.
    text = (
        "con fecha ex -dividendo (exdate) el 20 de julio de 2026 y fecha "
        "de registro (record date) el 21 de julio de 2026"
    )
    assert best_role_date(text, "EX_DATE")["iso"] == "2026-07-20"
    assert best_role_date(text, "RECORD_DATE")["iso"] == "2026-07-21"


def test_prepositional_span_rejects_glossary_label() -> None:
    # El 15 de junio es la fecha de pago; "fecha de registro" es una
    # mencion descriptiva dentro del mismo sintagma preposicional.
    text = (
        "el pago del dividendo tendrá lugar a partir del 15 de junio de "
        "2026 sobre la base del número de acciones existentes en la "
        "fecha de registro del dividendo (dividend record date)."
    )
    assert best_role_date(text, "RECORD_DATE") is None


def test_article_apposition_names_the_date() -> None:
    # "el ex - date" es aposicion que nombra la fecha, no uso descriptivo.
    text = "siendo el día 16 de abril de 2026 el ex - date previsto."
    assert best_role_date(text, "EX_DATE")["iso"] == "2026-04-16"


def test_no_year_lexeme_bound_but_not_iso() -> None:
    # "30 de abril" liga como candidato; el anio se deriva del payment
    # date en el wiring del parser (DERIVED_BY_DEFINITION).
    text = "la acción cotizaría ex -dividendo el 30 de abril próximo."
    bound = best_role_date(text, "EX_DATE")
    assert bound["value"].startswith("30 de")
    assert bound["explicit"] is False
    assert bound["iso"] is None
