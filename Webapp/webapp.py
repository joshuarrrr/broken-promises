#!/usr/bin/env python
# Encoding: utf-8
# -----------------------------------------------------------------------------
# Project : Broken Promises
# -----------------------------------------------------------------------------
# Author : Edouard Richard                                  <edou4rd@gmail.com>
# -----------------------------------------------------------------------------
# License : GNU General Public License
# -----------------------------------------------------------------------------
# Creation : 29-Oct-2013
# Last mod : 30-Oct-2013
# -----------------------------------------------------------------------------
# This file is part of Broken Promises.
# 
#     Broken Promises is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
# 
#     Broken Promises is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
# 
#     You should have received a copy of the GNU General Public License
#     along with Broken Promises.  If not, see <http://www.gnu.org/licenses/>.

from flask            import Flask, render_template, request, send_file, \
	send_from_directory, Response, abort, session, redirect, url_for, make_response, json
from flask.ext.assets import Environment
from flask.ext.login  import LoginManager, login_user, login_required, UserMixin, logout_user
from flask.ext.cache  import Cache
from rq_dashboard     import RQDashboard

from brokenpromises.storage    import Storage
from brokenpromises.channels   import get_available_channels
from brokenpromises.operations import CollectArticlesAndSendEmail
from brokenpromises.worker     import worker
import os
import datetime

STORAGE = Storage()

class CustomFlask(Flask):
	jinja_options = Flask.jinja_options.copy()
	jinja_options.update(dict(
		block_start_string    = '[%',
		block_end_string      = '%]',
		variable_start_string = '[[',
		variable_end_string   = ']]',
		comment_start_string  = '[#',
		comment_end_string    = '#]'))

app = CustomFlask(__name__)
app.config.from_envvar("WEBAPP_SETTINGS")

RQDashboard(app)
Environment(app)
cache         = Cache(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# -----------------------------------------------------------------------------
#
#    Utils
#
# -----------------------------------------------------------------------------
from bson.objectid import ObjectId
def dthandler(obj):
	if isinstance(obj, datetime.datetime) or isinstance(obj, datetime.date):
		return obj.isoformat()
	elif isinstance(obj, ObjectId):
		return str(obj)
	return None

@login_manager.user_loader
def load_user(userid):
	if userid == "superuser":
		user = UserMixin()
		user.id = "superuser"
		return user
	else:
		return None

def make_cache_key(*args, **kwargs):
	path = request.path
	args = str(hash(frozenset(request.args.items())))
	return (path + args).encode('utf-8')

# -----------------------------------------------------------------------------
#
#    API
#
# -----------------------------------------------------------------------------

@app.route("/last_scrape/<year>")
@app.route("/last_scrape/<year>/<month>")
@app.route("/last_scrape/<year>/<month>/<day>")
@cache.cached(key_prefix=make_cache_key)
def last_scrape(year, month=None, day=None):
	date    = (int(year), month and int(month) or None, day and int(day) or None)
	reports = STORAGE.get_reports(name="collector", searched_date=date, status="done")
	if reports:
		report   = reports[0]
		response = json.dumps({
			"status"                    : "ok",
			"searched_date"             : date,
			"last_scrape_date"          : report.date.strftime('%Y-%m-%dT%H:%M:%S'),
			"last_scrape_results_count" : report.meta['count'],
			# "last_reports"              : [r.__dict__ for r in reports]
		}, default=dthandler)
	else:
		response = json.dumps({
			"status"        : "no_result",
			"searched_date" : date
		})
	return Response(response,  mimetype='application/json')

@app.route("/count/<year>")
@app.route("/count/<year>/<month>")
@app.route("/count/<year>/<month>/<day>")
@cache.cached(key_prefix=make_cache_key)
def count_for_date(year, month=None, day=None):
	date           = (int(year), month and int(month) or None, day and int(day) or None)
	articles_count = STORAGE.count_articles(date)
	response       = json.dumps({
		"status"        : "ok",
		"searched_date" : date,
		"count"         : articles_count
	})
	return Response(response,  mimetype='application/json')

@app.route("/search_date/<email>/<year>"              , methods=['post'])
@app.route("/search_date/<email>/<year>/<month>"      , methods=['post'])
@app.route("/search_date/<email>/<year>/<month>/<day>", methods=['post'])
def search_date(email, year, month=None, day=None):
	date      = (int(year), month and int(month) or None, day and int(day) or None)
	collector = CollectArticlesAndSendEmail(get_available_channels(), *date, use_storage=True, email=email)
	job       = worker.run(collector)
	response  = json.dumps({
		"status"        : "ok",
		"searched_date" : date,
		"ref_job"       : job.id
	})
	return Response(response,  mimetype='application/json')

@app.route("/articles")
@app.route("/articles/<year>")
@app.route("/articles/<year>/<month>")
@app.route("/articles/<year>/<month>/<day>")
@cache.cached(key_prefix=make_cache_key)
def articles(year=None, month=None, day=None):
	limit     = int(request.args.get('limit', 20))
	skip      = int(request.args.get('skip' , 0))
	date      = (year and int(year) or None, month and int(month) or None, day and int(day) or None)
	articles  = STORAGE.get_articles(date, limit=limit, skip=skip)
	response  = json.dumps({
		"status"   : "ok",
		"count"    : len(articles),
		"articles" : [_.__dict__ for _ in articles],
	}, default=dthandler)
	return Response(response,  mimetype='application/json')

@app.route("/reports")
@app.route("/reports/<year>")
@app.route("/reports/<year>/<month>")
@app.route("/reports/<year>/<month>/<day>")
@cache.cached(key_prefix=make_cache_key)
def reports(year=None, month=None, day=None):
	date      = (year and int(year) or None, month and int(month) or None, day and int(day) or None)
	reports   = STORAGE.get_reports(searched_date=date)
	response  = json.dumps({
		"status"   : "ok",
		"count"    : len(reports),
		"reports" : [_.__dict__ for _ in reports],
	}, default=dthandler)
	return Response(response,  mimetype='application/json')

@app.route("/scheduledjobs")
def scheduled_jobs():
	from rq_scheduler import Scheduler
	import redis
	conn           = redis.from_url(app.config['REDIS_URL'])
	scheduler      = Scheduler(connection=conn)
	scheduled_jobs = scheduler.get_jobs(with_times=True)
	response       = json.dumps({
		"status"   : "ok",
		"count"    : len(scheduled_jobs),
		"jobs"     : [ dict(_[0].__dict__.items() + {"next_work":_[1]}.items() ) for _ in scheduled_jobs ],
	}, default=dthandler)
	return Response(response,  mimetype='application/json')

# -----------------------------------------------------------------------------
#
# Site pages
#
# -----------------------------------------------------------------------------
@app.route('/ui')
@app.route('/')
@login_required
def index():
	response = make_response(render_template('home.html'))
	return response

@app.route("/login", methods=["GET", "POST"])
def login():
	if request.form.get("password"):
		print request.form.get("password") == app.config['SUPERUSER_PASSWORD']
		if request.form.get("password") == app.config['SUPERUSER_PASSWORD']:
			login_user(load_user("superuser"))
		return redirect(request.args.get("next") or url_for("index"))
	return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
	logout_user()
	return redirect("/login")

# -----------------------------------------------------------------------------
#
#    FILTERS
#
# -----------------------------------------------------------------------------
@app.after_request
def after_request(response):
	response.headers.add('Access-Control-Allow-Origin', '*')
	response.headers.add('Access-Control-Allow-Methods', 'GET, POST')
	response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
	return response

# -----------------------------------------------------------------------------
#
# Main
#
# -----------------------------------------------------------------------------
if __name__ == '__main__':
	app.run(
		extra_files=[os.path.join(os.path.dirname(__file__), "webapp_settings.py")]
	)

# EOF
