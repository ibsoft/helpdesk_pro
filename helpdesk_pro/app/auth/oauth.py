from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_oauth(app):
    oauth.init_app(app)
    if not (
        app.config.get("AUTH_SSO_ENABLED")
        and app.config.get("AUTH_SSO_CLIENT_ID")
        and app.config.get("AUTH_SSO_CLIENT_SECRET")
        and app.config.get("AUTH_SSO_METADATA_URL")
    ):
        return
    oauth.register(
        name="sso",
        client_id=app.config["AUTH_SSO_CLIENT_ID"],
        client_secret=app.config["AUTH_SSO_CLIENT_SECRET"],
        server_metadata_url=app.config["AUTH_SSO_METADATA_URL"],
        client_kwargs={"scope": app.config.get("AUTH_SSO_SCOPE", "openid email profile")},
    )
