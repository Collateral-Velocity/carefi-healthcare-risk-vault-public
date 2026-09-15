import pandas as pd

from historical_replay import cdc_flu_replay_frame, cpi_ppi_correlation, replay_years
from live_data import parse_bls_response


def test_verified_flu_replay_peak():
    df=cdc_flu_replay_frame()
    assert len(df)==18
    assert float(df["influenza_ed_pct"].max())==8.3
    assert bool((df["influenza_ed_pct"]>=5.0).any())


def test_cpi_ppi_correlation_runs():
    dates=pd.date_range("2023-01-01",periods=30,freq="MS")
    cpi=pd.DataFrame({"date":dates,"value":[100+i for i in range(30)]})
    ppi=pd.DataFrame({"date":dates,"value":[120+1.2*i for i in range(30)]})
    result=cpi_ppi_correlation(cpi,ppi)
    assert result["observations"]>=12
    assert result["correlation"] is not None


def test_bls_parser():
    payload={
        "status":"REQUEST_SUCCEEDED",
        "Results":{"series":[{"seriesID":"CUUR0000SAM","data":[
            {"year":"2026","period":"M02","value":"600.1"},
            {"year":"2026","period":"M01","value":"599.0"},
            {"year":"2025","period":"M13","value":"0"},
        ]}]}
    }
    out=parse_bls_response(payload)["CUUR0000SAM"]
    assert len(out)==2
    assert list(out["value"])==[599.0,600.1]


def test_replay_years_with_observed_inputs():
    dates=pd.date_range("2023-01-01",periods=36,freq="MS")
    cpi=pd.DataFrame({"date":dates,"value":[100*(1.004**i) for i in range(36)]})
    ppi=pd.DataFrame({"date":dates,"value":[100*(1.003**i) for i in range(36)]})
    out=replay_years(cpi,ppi)
    assert not out.empty
    assert "medical_cpi_trigger" in out.columns
