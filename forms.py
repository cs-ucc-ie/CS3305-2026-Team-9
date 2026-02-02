from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import InputRequired, EqualTo, Regexp, ValidationError
 

def password_not_username(form, field):
    username = getattr(form, 'user_id').data or ""
    if username and field.data and field.data == username:
        raise ValidationError("Password must not be the same as the username.")

class RegistrationForm(FlaskForm):
    user_id = StringField("User id:", validators=[InputRequired()])
    password = PasswordField(
        "Password:",
        validators=[
            InputRequired(),
            Regexp(r'^.{6,}$', message="Password must be at least 6 characters long."),
            Regexp(r'.*\d.*', message="Password must include at least one digit."),
            Regexp(r'.*[A-Z].*', message="Password must include at least one uppercase letter."),
            Regexp(r'.*[a-z].*', message="Password must include at least one lowercase letter."),
            Regexp(r'.*[^A-Za-z0-9].*', message="Password must include at least one symbol."),
            password_not_username,
        ]
    )
    password2 = PasswordField(
        "Confirm Password: ",
        validators=[InputRequired(), EqualTo("password")]
    )
    submit = SubmitField("Submit")

class LoginForm(FlaskForm):
    user_id = StringField("User id:", validators=[InputRequired()])
    password = PasswordField("Password:", validators=[InputRequired()])
    submit = SubmitField("Submit")

