#!/usr/bin/env python
# Encoding: utf-8
# -----------------------------------------------------------------------------
# Project : Broken Promises
# -----------------------------------------------------------------------------
# Author : Edouard Richard                                  <edou4rd@gmail.com>
# -----------------------------------------------------------------------------
# License : GNU General Public License
# -----------------------------------------------------------------------------
# Creation : 05-Nov-2013
# Last mod : 08-Nov-2013
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

import brokenpromises.channels
import brokenpromises.utils
import nltk
import os
import dateparser
import datetime
import reporter
from   wwwclient import HTML
from brokenpromises import Report

debug, trace, info, warning, error, fatal = reporter.bind(__name__)

class Collector(object):

	def __init__(self):
		self.report = None

	@classmethod
	def retrieve_referenced_dates(cls, text):
		references = []
		# filters tags if it's html
		text = HTML.parse(text)
		text = filter(lambda _: _.name() != "img", text)
		text = "".join(map(lambda _:_.html() ,text))
		# search and add dates to `refrences`
		for date_obj, date_row, date_position in dateparser.find_dates(text):
			reference = {
				"date"           : date_obj,
				"extract"        : cls.get_sentence(text, date_row),
				"extracted_date" : date_row
			}
			references.append(reference)
		return references

	@classmethod
	def get_sentence(cls, text, search):
		# TODO : DIY
		tokenizer = nltk.data.load(
			"file:%s" % (
				os.path.join(os.path.dirname(__file__), "nltk_data/tokenizers/punkt/english.pickle")))
		for sentence in tokenizer.sentences_from_text(text):
			if search in sentence:
				break
			sentence = None
		return sentence

	def set_report(self, **kwargs):
		self.report           = Report()
		self.report.date      = datetime.datetime.now()
		self.report.collector = "%s.%s" % (self.__class__.__module__, self.__class__.__name__)
		self.report.meta      = kwargs

	def get_report(self):
		return self.report

	def pre_filter(self, results):
		""" Excecuted before the dates parsing """
		# articles with no body
		results = filter(lambda _: _.body, results)
		return results

	def post_filter(self, results):
		""" Excecuted after the dates parsing """
		# TODO: TO TEST
		# filter ref_dates anterior to pub_date
		def _pub_date_is_anterior(_):
			try:
				date = (_['date'][0], _['date'][1] or 1, _['date'][2] or 1)
				return datetime.date(*date) > result.pub_date.date()
			except AttributeError as e:
				error("%s\nIs %s a datetime instance ? (type: %s)\nobj:" % (e, result.pub_date, type(result.pub_date), result.__dict__))
				return False
			except ValueError as e:
				error("%s\nIs %s a real date ?\nobj: %s" % (e, date, result.__dict__))
				return False
		for result in results:
			result.ref_dates = filter(_pub_date_is_anterior, result.ref_dates)
		# filter results when ref_dates is empty
		results = filter(lambda _: _.ref_dates, results)
		return results

# -----------------------------------------------------------------------------
#
#    Collect Articles
#
# -----------------------------------------------------------------------------
class CollectArticles(Collector):

	def __init__(self, channels, year, month=None, day=None):
		super(CollectArticles, self).__init__()
		self.channels_active = channels
		self.channels = [Channel() for Channel in brokenpromises.channels.perform_channels_import(channels)]
		self.date     = (year, month, day)

	def run(self):
		articles = []
		# retrieve articles from channels
		for channel in self.channels:
			articles += channel.get_articles(*self.date)
		# pre-filters
		articles = self.pre_filter(articles)
		# search dates in the body articles
		for result in articles:
			result.ref_dates = self.retrieve_referenced_dates(result.body)
		# post-filters
		articles = self.post_filter(articles)
		# reporting
		self.set_report(
			count         = len(articles),
			channels      = self.channels_active,
			date_searched = self.date,
			urls_found    = [_.url for _ in articles]
		)
		return articles

# -----------------------------------------------------------------------------
#
#    RefreshArticles : reparse given articles
#
# -----------------------------------------------------------------------------
class RefreshArticles(Collector):

	def __init__(self, articles, scrape=False):
		super(RefreshArticles, self).__init__()
		self.articles = articles
		self.scrape   = scrape

	def run(self):
		articles = self.articles
		# pre-filters
		self.pre_filter(articles)
		# parsing date
		for article in articles:
			if self.scrape:
				Channel       = brokenpromises.channels.perform_channels_import(article.channel)
				article.body  = Channel().scrape_body_article(article.url)
			article.ref_dates = self.retrieve_referenced_dates(article.body)
		# post-filters
		articles = self.post_filter(articles)
		return articles

# -----------------------------------------------------------------------------
#
#    Worker
#
# -----------------------------------------------------------------------------
class RedisWorker(object):

	def __init__(self):
		import rq
		import redis
		conn       = redis.from_url(os.getenv('REDISTOGO_URL', 'redis://localhost:6379'))
		self.queue = rq.Queue(connection=conn)

	def run(self, job, *arg, **kwargs):
		job = self.queue.enqueue(job.run, *arg, **kwargs)

class SimpleWorker(object):

	def __init__(self):
		pass

	def run(self, job, *arg, **kwargs):
		return job.run(*arg, **kwargs)

Worker = SimpleWorker()
# -----------------------------------------------------------------------------
#
#    Utils
#
# -----------------------------------------------------------------------------
def collect_and_save(title, date, mongo_uri):
	from pymongo import MongoClient
	from urlparse import urlparse
	channels      = brokenpromises.channels.get_available_channels()
	collector     = CollectArticles(channels, *date)
	results       = collector.run()
	report        = collector.get_report()
	report.caller = title
	# save articles
	mongodb_uri   = mongo_uri
	client        = MongoClient(mongodb_uri)
	db            = client[urlparse(mongodb_uri).path.split("/")[-1]]
	articles_col  = db['articles']
	reports_col   = db['reports']
	inserted = []
	updated  = []
	for article in results:
		previous = articles_col.find_one({"url" : article.url})
		if not previous:
			articles_col.insert(article.__dict__)
			inserted.append(article._id)
		else:
			articles_col.update({'_id':previous['_id']}, dict(previous.items() + article.__dict__.items()))
			updated.append(previous['_id'])
	# save report
	report.meta['inserted'] = inserted
	report.meta['updated']  = updated
	reports_col.insert(report.__dict__)

# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------
import unittest

class TestOperations(unittest.TestCase):
	'''Test Class'''

	def test_get_articles(self):
		channels = (
			# "brokenpromises.channels.nytimes",
			"brokenpromises.channels.guardian",
		)
		# channels  = brokenpromises.utils.get_available_channels()

		collector = CollectArticles(channels, "2014", "1")
		results   = collector.run()
		print 
		print "results:", len(results)
		assert len(results) > 0
		for result in results:
			assert result.ref_dates, "%s : %s" % (result, result.url)
		assert collector.get_report()
		assert collector.get_report().collector               == "brokenpromises.operations.CollectArticles"
		assert collector.get_report().meta['count']           == len(results)
		assert len(collector.get_report().meta['urls_found']) == len(results)

	def test_retrieve_referenced_dates(self):
		dates = (
			("10 October 2013"       , (2013, 10, 10)),
			("10 october, 2013"      , (2013, 10, 10)),
			("4 by October 2013"     , (2013, 10, 4)),
			("10 by October 2013"    , (2013, 10, 10)),
			("10 by October, 2013"   , (2013, 10, 10)),
			("Jan 2014"              , (2014, 1, None)),
			("10 in October 2013"    , (2013, 10, 10)),
			("10 in October, 2013"   , (2013, 10, 10)),
			("10 of October 2013"    , (2013, 10, 10)),
			("10 of October, 2013"   , (2013, 10, 10)),
			("10th October 2013"     , (2013, 10, 10)),
			("10th by October 2013"  , (2013, 10, 10)),
			("10th by October, 2013" , (2013, 10, 10)),
			("10th in october 2013"  , (2013, 10, 10)),
			("10th in October, 2013" , (2013, 10, 10)),
			("10th of October 2013"  , (2013, 10, 10)),
			("10th of October, 2013" , (2013, 10, 10)),
			("2013-10-10"            , (2013, 10, 10)),
			("2013/10/10"            , (2013, 10, 10)),
			("August, 2013"          , (2013, 8, None)),
			("2013"                  , (2013, None, None)),
			("November 04, 2013"     , (2013, 11, 4)),
			("November 4, 2013"      , (2013, 11, 4)),
		)

		text  = " bla bli 123. Bu \n pouet12 \n 12412 ".join([_[0] for _ in dates])
		refs  = CollectArticles.retrieve_referenced_dates(text)
		date_found = [_['extracted_date'] for _ in refs]
		for searched_date in dates:
			try:
				ref = filter(lambda _: _["extracted_date"] == searched_date[0], refs)[0]
			except:
				raise Exception("\"%s\" not found in document. Date found:\n%s" % (searched_date[0], "\n".join(date_found)))
			assert ref['extracted_date'] in searched_date[0]
			assert ref['date']           == searched_date[1], "%s != %s" % (ref['date'], searched_date[1])
			date_found.remove(ref['extracted_date'])
		assert len(refs) == len(dates), "%s != %s\nToo much : %s" % (len(refs), len(dates), date_found)

if __name__ == "__main__":
	# unittest.main()
	suite = unittest.TestLoader().loadTestsFromTestCase(TestOperations)
	unittest.TextTestRunner(verbosity=2).run(suite)
