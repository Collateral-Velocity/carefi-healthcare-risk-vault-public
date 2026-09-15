from pathlib import Path
import base64

def test_carefi_logo_asset_is_valid_jpeg():
    p=Path("assets/carefi_logo.jpg")
    data=p.read_bytes()
    assert len(data)>10000
    assert data[:2]==b"\xff\xd8"
    assert data[-2:]==b"\xff\xd9"
    uri="data:image/jpeg;base64,"+base64.b64encode(data).decode("ascii")
    decoded=base64.b64decode(uri.split(",",1)[1])
    assert decoded==data
