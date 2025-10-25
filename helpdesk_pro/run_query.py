from app import create_app, db
from app.models import Network, NetworkHost

app = create_app()
app.app_context().push()

rows = (
    NetworkHost.query.join(Network)
    .with_entities(
        Network.name,
        Network.cidr,
        NetworkHost.ip_address,
        NetworkHost.hostname,
        NetworkHost.assigned_to,
    )
    .filter(db.func.lower(NetworkHost.hostname) == db.func.lower('ioabuh-linux'))
    .all()
)

print(rows)
