# SMS pilot

## Test without sending texts

Run the web app and open `/alerts`. Enter a test number and choose a ward (Ward 11 has the College Street item); the demo displays the confirmation code on the page. Confirm it, then open the demo phone (`/alerts/phone`): it already shows what is live in that ward plus city-wide items (up to 3). After that, whenever a staff approval or a processing run first puts an item live, its ward's subscribers are texted automatically. `/staff/sms/overview` shows what was sent and has a "send now" button only for items that were never sent. Each item reaches each phone at most once. `SMS_MODE` defaults to `demo`.

## Send real texts with Twilio

Get a Twilio account, an SMS-capable sender number and its Account SID and Auth Token. The app reads the SMS variables from the local `.env` file, or from the shell environment (which takes precedence). Keep `.env` untracked and owner-readable only. For example:

```bash
export SMS_MODE=twilio
export TWILIO_ACCOUNT_SID='...'
export TWILIO_AUTH_TOKEN='...'
export TWILIO_FROM_NUMBER='+1...'
export SMS_WEBHOOK_URL='https://your-public-host.example/sms/twilio/inbound'
.venv/bin/uvicorn civify.app:app --host 0.0.0.0 --port 8000
```

Restart the web server after changing `.env`. Keep `SMS_MODE=demo` until a sender number and public HTTPS webhook are ready. As checked on November 13, 2026, the connected Twilio account is active but on a Trial plan and has no owned sender number. Twilio's current trial terms restrict custom message bodies, which Civify needs for confirmation codes and local issue alerts. Upgrade and acquire an SMS-capable sender before attempting the live flow.

Configure that exact HTTPS webhook URL as the Twilio number's **incoming message** webhook, using POST form data. The URL must be publicly reachable. The app verifies Twilio's signature and records STOP/UNSUBSCRIBE; Twilio also manages standard STOP replies. A local `127.0.0.1` URL cannot receive carrier webhooks. Test with your own opted-in phone before inviting residents. Twilio trial accounts can have recipient restrictions.

Alerts are sent automatically when an item first goes live; the text is built in code from the record (ward, place, official link), with no AI-written content. The SMS never claims an open comment period or calculates a deadline; it links to the official City item. A timeout is recorded as `unknown` and will not be retried automatically, avoiding duplicate messages. The provider's acceptance means the API accepted the message, not that a handset received it.

Phone numbers and consent timestamps are kept in local `civify.db`; addresses are not collected. A production pilot needs an approved retention/deletion process, delivery status callbacks, a secure hosted database, rate limits across multiple servers, and accessibility and language review. SMS is one access route: printable pages and in-person or phone assistance remain important for residents who do not use texting.
