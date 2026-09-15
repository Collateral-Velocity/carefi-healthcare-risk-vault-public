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

