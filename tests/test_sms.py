"""Consent and dispatch gates use a fresh database and no external SMS provider."""

import re

import pytest

from civify import app as appmod, db, sms


@pytest.fixture(autouse=True)
def demo_only(monkeypatch):
    monkeypatch.setenv("SMS_MODE", "demo")


def test_signup_requires_consent_and_confirmation(client):
    bad = client.post("/alerts", data={"phone": "4165550123", "ward": "10"})
    assert bad.status_code == 400
    con = db.connect(appmod.DB_PATH)
    assert con.execute("SELECT count(*) FROM sms_subscriptions").fetchone()[0] == 0
    response = client.post("/alerts", data={"phone": "4165550123", "ward": "10", "consent": "yes"})
    assert response.status_code == 200
    code = re.search(r"Civify code: (\d{6})", response.text).group(1)
    assert con.execute("SELECT status FROM sms_subscriptions").fetchone()[0] == "pending"
    for _ in range(5):
        assert client.post("/alerts/confirm", data={"phone": "4165550123", "code": "999999"}).status_code == 400
    assert client.post("/alerts/confirm", data={"phone": "4165550123", "code": code}).status_code == 400


def test_confirm_then_send_once_and_stop(client):
    signup = client.post("/alerts", data={"phone": "4165550123", "ward": "10", "consent": "yes"})
    code = re.search(r"Civify code: (\d{6})", signup.text).group(1)
    assert client.post("/alerts/confirm", data={"phone": "4165550123", "code": code}).status_code == 200
    con = db.connect(appmod.DB_PATH)
    rec = {"item_id": "test.1", "title": "A local item", "ward": "10", "official_url": "https://secure.toronto.ca/council/agenda-item/test"}
    pub = {"version": 1, "claims": [{"sentence": "Reviewed."}]}
    assert sms.send_item(con, rec, pub, "Staff") == {"sent": 1, "mode": "demo"}
    assert sms.send_item(con, rec, pub, "Staff")["sent"] == 0
    assert con.execute("SELECT status FROM sms_deliveries").fetchone()[0] == "demo"
    sms.stop(con, "4165550123")
    assert con.execute("SELECT status FROM sms_subscriptions").fetchone()[0] == "stopped"
    try:
        sms.begin(con, "4165550123", "10")
    except ValueError:
        pass
    else:
        assert False, "STOP must not be bypassed by web signup"


def test_unpublished_and_wrong_ward_are_not_sent(client):
    con = db.connect(appmod.DB_PATH)
    phone, code = sms.begin(con, "4165550123", "11")
    assert sms.confirm(con, phone, code)
    rec = {"item_id": "test.2", "title": "A local item", "ward": "10", "official_url": "https://secure.toronto.ca/council/"}
    try:
        sms.send_item(con, rec, None, "Staff")
    except ValueError:
        pass
    else:
        assert False, "a publication is required"
    assert sms.send_item(con, rec, {"version": 1, "claims": [{"sentence": "Reviewed."}]}, "Staff")["sent"] == 0


def test_webhook_rejects_unsigned_stop(client):
    response = client.post("/sms/twilio/inbound", data={"From": "+14165550123", "Body": "STOP"})
    assert response.status_code == 403


def test_demo_shows_code_and_alerts_on_a_simulated_phone(client):
    page = client.post("/alerts", data={"phone": "4165550199", "ward": "04", "consent": "yes"}).text
    code = re.search(r"Civify code: (\d{6})", page).group(1)
    assert 'class="phone-mock"' in page and "Simulated text to +14165550199" in page
    assert "Open the demo phone" in client.post("/alerts/confirm", data={"phone": "4165550199", "code": code}).text
    assert "No messages yet." in client.get("/alerts/phone", params={"phone": "4165550199"}).text


def test_alert_text_names_the_place_not_the_official_title():
    body = sms.alert_body({"title": "PB1.6 - 1337 Queen Street West - Demolition and New Construction", "ward": "4",
                           "official_url": "https://secure.toronto.ca/council/agenda-item.do?item=2027.PB1.6"})
    assert body.startswith("Civify Ward 4: new plain-language explanation for 1337 Queen Street West.") and "Reply STOP" in body
