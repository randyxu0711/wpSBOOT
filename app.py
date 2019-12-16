from flask import Flask, render_template, request, redirect, url_for
from flask import send_from_directory
from form import UserForm
from flask_mail import Mail, Message
import subprocess
import datetime
import os
import config

app = Flask(__name__)
app.config.from_object(config)
ALLOWED_EXTENSIONS = {'txt', 'fasta'}
cmd_list = ['perl', './src/wpSBOOT.sh']
basepath = os.path.dirname(__file__)
fpath = "/home/ubuntu/wpSBOOT/static/UserData/"
app.config.update(
    DEBUG=False,
    # EMAIL SETTINGS
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USE_SSL=True,
    MAIL_DEFAULT_SENDER=('wpSBOOT server', 'wpsboot@gmail.com'),
    MAIL_MAX_EMAILS=10,
    MAIL_USERNAME='wpsboot@gmail.com',
    MAIL_PASSWORD='mail4wpsboot'
)
mail = Mail(app)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/', methods=['GET'])
def index():
    form = UserForm()
    return render_template('index.html', form=form)

@app.route('/reference', methods=['GET'])
def reference():
    return render_template('reference.html')

@app.route('/contact', methods=['GET'])
def contact():
    return render_template('contact.html')

@app.route('/result/<fid>')
def result(fid):
    path = fpath + fid
    flist = os.listdir(path)
    return render_template('result.html', filename=fid, flist=flist)

@app.route('/download/<fid>')
def download(fid):
    dir = fpath + fid
    return send_from_directory(dir, fid, as_attachment=True)


@app.route('/', methods=['POST'])
def submit():
    form = UserForm()
    #basepath = os.path.dirname(__file__)
    # 收到表單
    if request.method == 'POST':

        # 抓取時間，格式化後轉成字串
        time = datetime.datetime.now()
        timeStr = time.strftime('%y%m%d%H%M%S')

        # 檢驗表單資料格式、缺失
        if form.validate_on_submit():

            # 以 email+datetime 作為filename(需唯一)
            email = str(form.email.data)
            filename = email.replace('.', '')+timeStr
            #print(filename)

            # 處理textarea
            if request.form['seqs']:
                text = request.form['seqs']
               # target = os.path.join(os.getcwd(), '/static/uploads/'+filename)
                fo = open('/home/ubuntu/wpSBOOT/static/uploads/'+filename,'w+')
                #print("filename :"+filename)
                fo.write(text)
                fo.close()
            elif request.files['file'] :
                # 處理file儲存
                f = request.files['file']
               # filename = secure_filename(f.filename)
                f.save(os.path.join(basepath, 'static/uploads', filename))
            else :
                return redirect(url_for('index'))
            # create cmd line
            # -i input
            cmd_list.append('-i')
            cmd_list.append('./static/uploads/'+filename)
            # -o output
            cmd_list.append('-o')
            cmd_list.append(filename)
            # -p path
            cmd_list.append('-p')
            cmd_list.append('./static/UserData/'+filename)
            #print(cmd_list)

            # 執行 cmd line
            p = subprocess.Popen(cmd_list)
            p.communicate()
            
            # Mail
            link = url_for('result', fid=filename, _external=True)
            msg = Message(
                subject='wpSBOOT alignment result',
                recipients=[email],
                html='Hello,<br><br>'
                     '	Your alignment has been completed.<br>'
                     '  click here to view your results--><a href="{link}">here</a><br><br>'
		     'If you have questions, suggestions or to report problems do not reply to this message, write instead to '
		     '<a href="mailto:chang.jiaming@gmail.com ">chang.jiaming@gmail.com</a><br><br>'
                     'Cheers,<br>'
                     'wpSBOOT team'.format(link=link)
            )
            mail.send(msg)

            return redirect(url_for('result', fid=filename))
    else:
        return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port='8000', debug=False)

