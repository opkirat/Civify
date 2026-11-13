"""Geo tests. The City API is replaced by a canned reply so tests are offline and stable."""

import json

from civify.geo import WARDS, distance_km, lookup, parse_address, ward_number

CITY_REPLY = json.dumps({"result": {"records": [{
    "ADDRESS_FULL": "191 College St", "WARD": "11", "WARD_NAME": "University-Rosedale",
    "geometry": '{"type": "Point", "coordinates": [-79.394797577481, 43.6586796454236]}'}]}})


def test_parse_address_strips_type_and_uses_first_number_of_a_range():
    assert parse_address("191-199 College Street") == ("191", "College")
    assert parse_address("100 Queen St W") == ("100", "Queen")
    assert parse_address("2686 Lake Shore Boulevard West") == ("2686", "Lake Shore")
    assert parse_address("College Street") is None


def test_lookup_returns_ward_and_point_and_sends_structured_filters():
    seen = {}
    def fake(url): seen["url"] = url; return CITY_REPLY
    r = lookup("191 College St", fetch=fake)
    assert r == {"address": "191 College St", "ward": "11", "ward_name": "University-Rosedale",
                 "lat": 43.6586796454236, "lon": -79.394797577481}
    assert "ADDRESS_NUMBER" in seen["url"] and "College" in seen["url"]


def test_lookup_is_none_when_city_has_no_match_or_api_fails():
    assert lookup("1 Nowhere St", fetch=lambda u: json.dumps({"result": {"records": []}})) is None
    def boom(u): raise OSError("offline")
    assert lookup("191 College St", fetch=boom) is None


def test_distance_and_ward_helpers():
    city_hall = {"lat": 43.6534, "lon": -79.3841}
    college = {"lat": 43.6587, "lon": -79.3948}
    assert 0.9 < distance_km(city_hall, college) < 1.2
    assert ward_number("11 - University-Rosedale") == "11" and ward_number(None) is None
    assert len(WARDS) == 25 and WARDS["11"] == "University-Rosedale"
