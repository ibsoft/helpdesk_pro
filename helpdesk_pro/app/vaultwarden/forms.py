from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, SelectField, StringField
from wtforms.validators import DataRequired, Length, Optional

from app.models.vaultwarden import ITEM_TYPES


class VaultItemForm(FlaskForm):
    name = StringField(
        "Item label",
        validators=[DataRequired(), Length(max=255)],
        render_kw={"placeholder": "GitHub Login"},
    )
    item_type = SelectField(
        "Item type",
        choices=ITEM_TYPES,
        validators=[DataRequired()],
    )
    folder_id = SelectField(
        "Folder",
        coerce=int,
        validators=[Optional()],
        choices=[(0, "- No folder -")],
    )
    organization_id = SelectField(
        "Organization",
        coerce=int,
        validators=[Optional()],
        choices=[(0, "Personal vault")],
    )
    collection_id = SelectField(
        "Collection",
        coerce=int,
        validators=[Optional()],
        choices=[(0, "No collection")],
    )
    tags = StringField(
        "Tags",
        validators=[Optional()],
        render_kw={"placeholder": "work, client"},
    )
    favorite = BooleanField("Mark as favorite")
    encrypted_blob = HiddenField("Encrypted payload", validators=[DataRequired()])
    metadata_blob = HiddenField("Metadata", validators=[Optional()])


class VaultFolderForm(FlaskForm):
    name = StringField(
        "Folder name",
        validators=[DataRequired(), Length(max=120)],
        render_kw={"placeholder": "Client logins"},
    )
    organization_id = SelectField(
        "Organization",
        coerce=int,
        validators=[Optional()],
        choices=[(0, "Personal vault")],
    )
    collection_id = SelectField(
        "Collection",
        coerce=int,
        validators=[Optional()],
        choices=[(0, "No collection")],
    )
