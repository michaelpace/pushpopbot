import tweepy
import os
import ConfigParser

BOT_NAME = '@pushpopbot'
MAXIMUM_TWEET_LENGTH = 140

# read da config, dummy
config = ConfigParser.ConfigParser()
config.read('config/config.ini')

# read da housekeeping, dumbo
housekeeping = ConfigParser.ConfigParser()
housekeeping.read('housekeeping.ini')

# tell twitter that i am a real robot
auth = tweepy.OAuthHandler(config.get('twitter', 'consumer_key'), config.get('twitter', 'consumer_secret'))
auth.set_access_token(config.get('twitter', 'access_token'), config.get('twitter', 'access_token_secret'))
api = tweepy.API(auth)

# delete tweets from twitter
user_timeline = api.user_timeline()
for status in user_timeline:
    api.destroy_status(status.id)

# reset our local stuff
housekeeping.set('runtimes', 'last_processed_tweet', '')
hk_file = open('housekeeping.ini', 'w')
housekeeping.write(hk_file)
hk_file.close()
os.remove('pushpopbot.log')
