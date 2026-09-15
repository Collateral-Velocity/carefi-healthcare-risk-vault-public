from ingest_production import normalize_cdc_row


def test_cdc_percentage_row_normalizes():
    row={
        "geography":"Texas",
        "pathogen":"Influenza",
        "percent_visits":"2.7",
        "week_end":"2026-01-10T00:00:00.000",
    }
    out=normalize_cdc_row(row)
    assert out is not None
    assert out["period_end"]=="2026-01-10"
    assert out["geography"]=="Texas"
    assert out["disease"]=="Influenza"
    assert out["value"]==2.7
