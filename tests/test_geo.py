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
    assert "ADDRESS_NUMBER" in seen["url"] and "LINEAR_NAME" not in seen["url"]


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


def test_directions_are_not_discarded_and_ambiguous_addresses_need_a_choice():
    from civify.geo import search_address
    records = json.loads(CITY_REPLY)['result']['records']
    east = {**records[0], 'ADDRESS_FULL': '100 Queen St E', 'WARD': '13'}
    west = {**records[0], 'ADDRESS_FULL': '100 Queen St W', 'WARD': '10'}
    fetch = lambda _: json.dumps({'result': {'records': [east, west]}})
    assert search_address('100 Queen Street West, Toronto, ON', fetch)['match']['ward'] == '10'
    assert search_address('Unit 5, 100 queen st w', fetch)['match']['ward'] == '10'
    ambiguous = search_address('100 Queen St', fetch)
    assert ambiguous['status'] == 'ambiguous' and ambiguous['match'] is None
    assert len(ambiguous['candidates']) == 2
    assert parse_address('55 St Clair Avenue West') == ('55', 'St Clair')


def test_service_failure_is_not_an_invalid_address():
    from civify.geo import search_address
    def offline(_): raise OSError('offline')
    assert search_address('100 Queen St W', offline)['status'] == 'unavailable'
    assert search_address('Queen St', offline)['status'] == 'invalid'


def test_malformed_geometry_does_not_crash_lookup():
    from civify.geo import search_address
    row = json.loads(CITY_REPLY)['result']['records'][0]
    row['geometry'] = 'not json'
    assert search_address('191 College St', lambda _: json.dumps({'result':{'records':[row]}}))['match'] is None


def test_near_includes_close_cross_ward_items_but_distrusts_conflicting_locations(client, monkeypatch):
    from civify import app as appmod
    point = {'address': '100 Queen St W', 'ward': '10', 'ward_name': 'Spadina-Fort York', 'lat':43.6534, 'lon':-79.3841}
    monkeypatch.setattr(appmod.geo, 'search_address', lambda _: {'status':'matched','match':point,'candidates':[]})
    records = appmod.db.list_items()
    college = next(r for r in records if r['item_id']=='2026.TE34.21')
    bad = {**college, 'item_id':'2026.TE34.999', 'title':'X - Wrong location - Test', 'ward':'4'}
    monkeypatch.setattr(appmod.db, 'list_items', lambda: [college, bad])
    response=client.get('/near', params={'address':'100 Queen St W'})
    matches={r['rec']['item_id']:r for r in response.context['results']}
    assert matches['2026.TE34.21']['relevant'] and not matches['2026.TE34.21']['same_ward']
    assert matches['2026.TE34.999']['km'] is None and not matches['2026.TE34.999']['relevant']
