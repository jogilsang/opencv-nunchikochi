import json, pathlib
from nunchi.contracts import FrameResult, Decision, SessionSummary

FIX = pathlib.Path(__file__).parent / "fixtures"

def test_fixtures_roundtrip_json():
    for name in ("frame_result_ok", "frame_result_dark", "decision_nudge", "session_summary"):
        d = json.loads((FIX / f"{name}.json").read_text())
        assert isinstance(d, dict) and d

def test_no_image_fields_in_contracts():
    banned = ("image", "frame_bytes", "jpeg", "pixels", "data_url")
    for cls in (FrameResult, Decision, SessionSummary):
        assert not any(b in k.lower() for k in cls.__dataclass_fields__ for b in banned)

def test_frame_result_defaults_safe():
    fr = FrameResult()
    assert fr.face_present is False and fr.events == [] and fr.to_dict()["schema"] == "1.0"
