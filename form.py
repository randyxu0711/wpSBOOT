#  引入flask_wtf
from flask_wtf import FlaskForm
#  各別引入需求欄位類別
from wtforms import StringField, SubmitField
from wtforms.fields.html5 import EmailField
#  引入驗證
from wtforms.validators import DataRequired, Email


#  從繼承FlaskForm開始
class UserForm(FlaskForm):
    email = EmailField('Email')
    submit = SubmitField('Submit')
