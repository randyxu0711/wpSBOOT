from flask import Flask, render_template, request, redirect, url_for
from flask import send_from_directory, session
from form import UserForm
from flask_mail import Mail, Message
import subprocess
import datetime
import os
import config

app = Flask(__name__)
app.config.from_object(config)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=1)
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

@app.route('/history')
def history():
    if session.get('mail'):
        mail = session.get('mail')
        timeUp = datetime.datetime.now().strftime('%y%m%d%H%M%S')
        timeDown = str(int(timeUp)-1000000)
        path = fpath
        listDir = os.listdir(path)
        joblist=[]

        for dir in listDir:
            #check id
            if mail in dir:
                #check time
                if mail+timeDown < dir < mail+timeUp:
                    joblist.append(dir)
        return render_template('history.html', empty=False, joblist=joblist)

    else:
        print('no history')
        return render_template('history.html', empty=True)

@app.route('/deletehistory')
def deletehistory():
    session.clear()
    return redirect(url_for('history'))

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
            if request.form.get('email'):
                email = str(form.email.data)
            else:
                email = 'test'
            filename = email.replace('.', '') + timeStr

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

            # 判斷option, aligner selector
            opcount = 0		
		#mafft
            if request.form.get('mafft'):
                cmd_list.append('-m')
                cmd_list.append('mafft')
                opcount += 1
		#msucle
            if request.form.get('muscle'):
                cmd_list.append('-m')
                cmd_list.append('muscle')
                opcount += 1
		#clustalw
            if request.form.get('clustalw'):
                cmd_list.append('-m')
                cmd_list.append('clustalw')
                opcount += 1
		#tcoffee
            if request.form.get('t-coffee'):
                cmd_list.append('-m')
                cmd_list.append('tcoffee')
                opcount += 1
            # if the number of aligners less than 2 (fatal error)
            if opcount < 2:
                return redirect(url_for('index'))

            # 執行 cmd line
            p = subprocess.Popen(cmd_list)
            p.communicate()
            
            #session
            if email != 'test':
                session['mail'] = email.replace('.', '')
                session.permanent = True

            # Mail
            link = url_for('result', fid=filename, _external=True)
            msg = Message(
                subject='wpSBOOT alignment result',
                recipients=[email],
                html='Hello,<br>'
                     '<blockquote>Your alignment has been completed.<br>'
                     'Please click <a href="{link}">here</a> to view your results.<br><br>'
		     'If you have question or report problems, do not reply to this message,and write instead to '
		     '<a href="mailto:chang.jiaming@gmail.com ">chang.jiaming@gmail.com</a></blockquote>'
                     '<br>Cheers,<br>'
                     'wpSBOOT team'.format(link=link)
            )
            mail.send(msg)

            return redirect(url_for('result', fid=filename))
    else:
        return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port='8000', debug=False)

