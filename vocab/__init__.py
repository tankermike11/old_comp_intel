"""Centralized controlled vocabularies. Must match schema.md exactly — no inline enum values elsewhere."""

SURFACE = {
    "edgar", "app_store_ios", "app_store_android", "pricing_page",
    "cftc", "press_blog", "social", "careers", "earnings_call", "other",
}

CATEGORY = {
    "feature_launch", "product_launch", "pricing_change", "acquisition_ma",
    "regulatory_filing", "partnership", "hiring_signal", "content_education",
    "platform_infra", "other",
}

PILLAR = {
    "options", "crypto", "prediction", "equities_etfs", "futures", "multi", "other",
}

ACTION = {
    "PRIORITIZE", "ACT_SOON", "COUNTER_POSITION", "MONITOR",
    "TRACK", "WEDGE_WATCH", "NOTE", "LOG", "LOG_ONLY",
}

STATUS = {
    "proposed", "confirmed", "dismissed", "superseded",
}

CONFIDENCE = {"high", "medium", "low"}

WEDGE_DIRECTION = {"reinforces", "validates", "dilutes", "threatens", "neutral"}

BUCKET = {"Very High", "High", "Moderate", "Low", "Negligible"}

RUN_TYPE = {"monthly", "baseline", "convergence_check", "adhoc"}

RUN_STATUS = {"running", "complete", "failed"}


def validate(value, vocab, field_name):
    if value not in vocab:
        raise ValueError(f"invalid {field_name}: {value!r} not in {sorted(vocab)}")
    return value
