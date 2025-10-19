# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length


class TicketForm(FlaskForm):
    subject = StringField('Subject', validators=[
                          DataRequired(), Length(max=255)])
    description = TextAreaField('Description', validators=[DataRequired()])
    priority = SelectField('Priority', choices=[(
        'Low', 'Low'), ('Medium', 'Medium'), ('High', 'High'), ('Critical', 'Critical')])
    status = SelectField('Status', choices=[
                         ('Open', 'Open'), ('In Progress', 'In Progress'), ('Closed', 'Closed')])
    department = StringField('Department')
    # <-- Select με ακέραιο id
    assigned_to = SelectField('Assigned To', coerce=int)
    submit = SubmitField('Save')
