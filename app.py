from flask import Flask, render_template, request
from form import UserForm
import subprocess
import datetime
import os
import config

app = Flask(__name__)
app.config.from_object(config)
ALLOWED_EXTENSIONS = {'txt', 'fasta'}
cmd_list = ['perl','./src/wpSBOOT.sh']

def allowed_file(filename):
	return '.' in filename and \
		filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/', methods=['GET', 'POST'])
def user():
	form = UserForm()
	basepath = os.path.dirname(__file__)
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

        	# 儲存file
            		f = request.files['file']
            		#filename = secure_filename(f.filename)
            		f.save(os.path.join(basepath, 'static/uploads', filename))

       		 # create cmd line
            		# -i input
            		cmd_list.append('-i')
            		cmd_list.append('./static/uploads/'+filename)
            		# -o output
            		cmd_list.append('-o')
            		cmd_list.append(filename)
            		# -p path
            		cmd_list.append('-p')
            		cmd_list.append('./UserData/'+filename)
            		#print(cmd_list)
		
        	# 執行 cmd line
			p = subprocess.Popen(cmd_list)
			p.communicate()	
		return 'Successful submit! '+email
	else:
        	return render_template('index.html', form=form)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port='8000', debug=False)

