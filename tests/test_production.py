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


def test_kalshi_signature_roundtrip():
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from live_data import kalshi_sign

    private_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    timestamp="1703123456789"
    path="/trade-api/v2/portfolio/balance"
    signature=base64.b64decode(kalshi_sign(pem,timestamp,"GET",path))
    private_key.public_key().verify(
        signature,
        f"{timestamp}GET{path}".encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_kalshi_missing_credentials_is_not_connected():
    from live_data import fetch_kalshi_clearer_state
    result=fetch_kalshi_clearer_state(api_key_id="",private_key_pem="",environment="demo")
    assert result["status"]=="not_connected"
    assert result["provider"]=="Kalshi"


def test_bls_sihcare3_flat_file_parser():
    from live_data import parse_bls_special_index_text
    sample="series_id\tyear\tperiod\tvalue\tfootnote_codes\nWPUSIHCARE3\t2026\tM07\t150.1\t\nWPUSIHCARE3\t2026\tM08\t151.2\tP\nWPU00000000\t2026\tM08\t100.0\t\n"
    df=parse_bls_special_index_text(sample,"WPUSIHCARE3")
    assert len(df)==2
    assert list(df["value"])==[150.1,151.2]
    assert list(df["series_id"].unique())==["WPUSIHCARE3"]


def test_oriel_event_marks_use_live_bls_series():
    import pandas as pd
    from datetime import datetime, timezone
    from oriel_event_marks import generate_event_marks

    dates=pd.date_range("2019-01-01",periods=84,freq="MS")
    medical=pd.DataFrame({"date":dates,"value":[100*(1.0025**i) for i in range(len(dates))],"series_id":"CUUR0000SAM","series":"Medical CPI"})
    ppi=pd.DataFrame({"date":dates,"value":[100*(1.0020**i) for i in range(len(dates))],"series_id":"SIHCARE3","series":"Healthcare Services PPI"})
    history=pd.concat([medical,ppi],ignore_index=True)
    artifact=generate_event_marks(history,{"records":{}},generated_at=datetime(2026,9,15,tzinfo=timezone.utc))
    by_id={m["contract_id"]:m for m in artifact["marks"]}
    assert artifact["methodology_version"]=="OER-HC-1.0.0"
    assert by_id["ORIEL-HC-MCPI-2027-01"]["source_health"]=="healthy"
    assert by_id["ORIEL-HC-PPI-2027-01"]["source_health"]=="healthy"
    assert 0 < by_id["ORIEL-HC-MCPI-2027-01"]["fair_value"] < 1
    assert 0 < by_id["ORIEL-HC-PPI-2027-01"]["fair_value"] < 1

def test_contract_sources_expose_required_controls():
    from pathlib import Path

    registry=(Path("contracts")/"EligibilityRegistry.sol").read_text()
    token=(Path("contracts")/"VaultShareToken.sol").read_text()
    suite=(Path("contracts")/"CAREHRV01ShareSuite.sol").read_text()

    for item in ["CLASS_S","CLASS_M","CLASS_E","setEligibility","replaceWallet","canTransfer"]:
        assert item in registry

    for item in ["mint","burn","recoverWallet","pauseTransfers","transferFrom","eligibilityRegistry"]:
        assert item in token

    for item in ["hrvSenior","hrvMezzanine","hrvEquity"]:
        assert item in suite


def test_contracts_do_not_store_plaintext_kyc_fields():
    from pathlib import Path
    source="\n".join(p.read_text().lower() for p in Path("contracts").glob("*.sol"))
    for forbidden in ["social_security","passport_number","date_of_birth","home_address"]:
        assert forbidden not in source

