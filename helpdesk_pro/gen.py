# Run inside `flask shell`
from app import db
from app.models import FleetApiKey

key = FleetApiKey(name="Primary Agent")
raw_value = FleetApiKey.generate_key()
key.set_key(raw_value)
db.session.add(key)
db.session.commit()

print("Share this API key with agents:", raw_value)
