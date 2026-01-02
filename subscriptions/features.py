from __future__ import annotations

FEATURE_TX_CREATE = "tx_create"
FEATURE_TX_DELETE = "tx_delete"
FEATURE_TX_QUERY_DAY = "tx_query_day"
FEATURE_TX_QUERY_RANGE = "tx_query_range"
FEATURE_MONTHLY_SUMMARY = "monthly_summary"

FEATURE_LOAN_CREATE = "loan_create"
FEATURE_LOAN_ALERTS = "loan_alerts"          # alertas programadas (Pro)
FEATURE_LOAN_MARK_PAID = "loan_mark_paid"    # (siguiente paso)
FEATURE_LOAN_ADVANCED_FLOW = "loan_advanced_flow"  # flujo guiado avanzado (Pro)

DEFAULT_PLANS = {
    "free": {
        FEATURE_TX_CREATE: True,
        FEATURE_TX_DELETE: True,
        FEATURE_TX_QUERY_DAY: True,
        FEATURE_TX_QUERY_RANGE: False,
        FEATURE_MONTHLY_SUMMARY: True,

        FEATURE_LOAN_CREATE: True,
        FEATURE_LOAN_ALERTS: False,
        FEATURE_LOAN_MARK_PAID: False,
        FEATURE_LOAN_ADVANCED_FLOW: False,
    },
    "plus": {
        FEATURE_TX_CREATE: True,
        FEATURE_TX_DELETE: True,
        FEATURE_TX_QUERY_DAY: True,
        FEATURE_TX_QUERY_RANGE: True,      # Plus ya puede rango
        FEATURE_MONTHLY_SUMMARY: True,

        FEATURE_LOAN_CREATE: True,
        FEATURE_LOAN_ALERTS: False,        # solo Pro
        FEATURE_LOAN_MARK_PAID: True,      # Plus puede marcar cuotas (paso siguiente)
        FEATURE_LOAN_ADVANCED_FLOW: False,
    },
    "pro": {
        FEATURE_TX_CREATE: True,
        FEATURE_TX_DELETE: True,
        FEATURE_TX_QUERY_DAY: True,
        FEATURE_TX_QUERY_RANGE: True,
        FEATURE_MONTHLY_SUMMARY: True,

        FEATURE_LOAN_CREATE: True,
        FEATURE_LOAN_ALERTS: True,
        FEATURE_LOAN_MARK_PAID: True,
        FEATURE_LOAN_ADVANCED_FLOW: True,
    },
}