#!/usr/bin/env python
# Encoding: utf-8
# -----------------------------------------------------------------------------
# Project : Broken Promises
# -----------------------------------------------------------------------------
# Author : Edouard Richard                                  <edou4rd@gmail.com>
# -----------------------------------------------------------------------------
# License : proprietary journalism++
# -----------------------------------------------------------------------------
# Creation : 28-Oct-2013
# Last mod : 04-Nov-2013
# -----------------------------------------------------------------------------
from models import Article
import collector.utils

# -----------------------------------------------------------------------------
#
#    Collector
#
# -----------------------------------------------------------------------------
class Collector:

	def __init__(self, channels=tuple()):
		self.channels = [channel() for channel in collector.utils.perform_channels_import(channels)]

	def get_articles(self, year, month=None, day=None):
		results = []
		for channel in self.channels:
			results += channel.get_articles(year, month, day)
		# TODO
		# 	[ ]  check date in body
		# 	[ ]  get the snippets with dates
		# 	[ ]  set ref_date, multiple allowed
		date_formats = collector.utils.get_all_date_formats(year, month, day)
		for result in results:
			result.ref_date = (year, month, day)
			result.snippets = collector.utils.get_snippets(date_formats)
		return results

# -----------------------------------------------------------------------------
#
# TESTS
#
# -----------------------------------------------------------------------------
import unittest

class TestCollector(unittest.TestCase):
	'''Test Class'''

	def test_get_articles(self):
		channels = (
			"collector.channels.nytimes",
			# "collector.channels.guardian",
		)
		# channels  = collector.utils.get_available_channels()

		collector = Collector(channels)
		results   = collector.get_articles("2014", "1")
		print 
		print "results:", len(results)
		assert len(results) > 0

if __name__ == "__main__":
	# unittest.main()
	suite = unittest.TestLoader().loadTestsFromTestCase(TestCollector)
	unittest.TextTestRunner(verbosity=2).run(suite)

# EOF
