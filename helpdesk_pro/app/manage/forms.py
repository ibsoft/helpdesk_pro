from flask_wtf import FlaskForm
from flask_babel import gettext as _
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length


class VaultOrganizationForm(FlaskForm):
    name = StringField(
        _("Name"),
        validators=[DataRequired(), Length(max=180)],
        render_kw={"placeholder": _("Acme Corp")},
    )
    description = TextAreaField(
        _("Description"),
        validators=[Length(max=500)],
        render_kw={"rows": 2},
    )
    submit = SubmitField(_("Create organization"))


class VaultCollectionForm(FlaskForm):
    organization_id = SelectField(
        _("Organization"),
        coerce=int,
        validators=[DataRequired()],
    )
    name = StringField(
        _("Collection name"),
        validators=[DataRequired(), Length(max=160)],
        render_kw={"placeholder": _("Engineering secrets")},
    )
    description = TextAreaField(
        _("Description"),
        validators=[Length(max=500)],
        render_kw={"rows": 2},
    )
    submit = SubmitField(_("Create collection"))


class VaultOrganizationMemberForm(FlaskForm):
    organization_id = SelectField(
        _("Organization"),
        coerce=int,
        validators=[DataRequired()],
        render_kw={"placeholder": _("Select organization")},
    )
    user_id = SelectField(
        _("User"),
        coerce=int,
        validators=[DataRequired()],
        render_kw={"placeholder": _("Select user")},
    )
    role = SelectField(
        _("Role"),
        choices=[("member", _("Member")), ("admin", _("Administrator"))],
        default="member",
        validators=[DataRequired()],
    )
    submit = SubmitField(_("Add member"))


class VaultCollectionAccessForm(FlaskForm):
    collection_id = SelectField(
        _("Collection"),
        coerce=int,
        validators=[DataRequired()],
    )
    user_id = SelectField(
        _("User"),
        coerce=int,
        validators=[DataRequired()],
    )
    access_level = SelectField(
        _("Access level"),
        choices=[("read", _("Read")), ("edit", _("Edit")), ("manage", _("Manage"))],
        validators=[DataRequired()],
    )
    submit = SubmitField(_("Grant access"))
