"""
TODO-LIST:
- there's a bug in the code right now; try running and witness that the final two pops are wrong. ACTUALLY they appear to be right, but were wrong when i first added them. try pushing four more, and then popping two, and then running it, and see if the two that get popped are the correct two.
- code cleanup
    - use sqlite instead of housekeeping.ini, and also to keep track of original authors of Pushes
    - classes with less responsibility
        - create class to represent a twitter action (i.e., instead of Push / Pop, TwitterActions would be PostTweet, DeleteTweet, GetTimeline, GetMentions, etc.)
            - TwitterActions should have success / failure results
        - each Push or Pop has a list of actions it needs to perform
        - create BotRunner class or something which is in charge of iterating over mentions, creating Pushes and Pops (which themselves create TwitterActions)
            - it should also update_local_timeline(), maybe. regardless, the local timeline should only be modified in one place
        - class in charge of interacting w/ sqlite db
    - dry it up
    - increase testability
- logging
- handle twitter throttling
- handle twitter not returning full results (e.g., if the mentions array hit some max limit, how would we know?)
- handle input better (e.g., strip newlines, etc.)
- wrap bot runner in a class
- unit tests
- fab file
- travis ci
- at-mention the original pusher w/ the pop recipient? (perhaps as follow-up tweet so we don't have to worry about length limits); this will require more persistence between runs (i.e., more than just using bot's twitter timeline)
    - the follow-up tweet would be: "pushed ____ by @incrediblepasta" or something similar. maybe "via @incrediblepasta on ____", or "via @incrediblepasta, pushed ____"
- should users have to write "push"?
"""


import tweepy
import ConfigParser
import re

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


def remove_pushpopbot_from_tweet(tweet_text):
    txt = re.sub(r'%s\s+' % BOT_NAME, '', tweet_text)
    txt = re.sub(r'\s+%s' % BOT_NAME, '', txt)
    txt = re.sub(r'\s*%s\s*' % BOT_NAME, '', txt)
    return txt


class TwitterAction(object):
    def __init__(self, tweet, timeline):
        self.tweet = tweet
        self.timeline = timeline
        self.tweet_text_without_mention_string = None

    def tweet_text_without_mention(self):
        if not self.tweet_text_without_mention_string:
            self.tweet_text_without_mention_string = remove_pushpopbot_from_tweet(self.tweet.text)
        return self.tweet_text_without_mention_string

    def text_for_tweet(self):
        raise NotImplementedError()

    def post_tweet(self):
        posted_tweet = None
        if self.should_post_tweet():
            text_for_tweet = self.text_for_tweet()
            if len(text_for_tweet) <= MAXIMUM_TWEET_LENGTH:
                try:
                    posted_tweet = api.update_status(status=text_for_tweet, in_reply_to_status_id=self.in_reply_to_status_id())
                except tweepy.TweepError as e:
                    # duplicate tweet error, etc.
                    # TODO: log this
                    pass
        return posted_tweet

    def should_post_tweet(self):
        raise NotImplementedError()

    def in_reply_to_status_id(self):
        raise NotImplementedError()

    def update_local_timeline(self, result):
        raise NotImplementedError()

    def perform_action(self):
        raise NotImplementedError()


class Push(TwitterAction):
    identifier = 'push '
    identifier_len = len(identifier)

    def __init__(self, tweet, timeline):
        super(Push, self).__init__(tweet, timeline)

    def text_for_tweet(self):
        return self.tweet_text_without_mention()[self.__class__.identifier_len:]

    def should_post_tweet(self):
        return True

    def in_reply_to_status_id(self):
        return None

    def update_local_timeline(self, result):
        if result:  # TODO: if result is not an error...
            self.timeline.append(result)

    def perform_action(self):
        tweet = self.post_tweet()
        self.update_local_timeline(tweet)
        if tweet:
            housekeeping.set('runtimes', 'last_processed_tweet', str(self.tweet.id))
            hk_file = open('housekeeping.ini', 'w')
            housekeeping.write(hk_file)
            hk_file.close()


class Pop(TwitterAction):
    identifier = 'pop'
    identifier_len = len(identifier)

    def __init__(self, tweet, timeline):
        super(Pop, self).__init__(tweet, timeline)

    def text_for_tweet(self):
        author = '@' + self.tweet.author.screen_name
        text = self.target_tweet().text
        return '%s %s' % (author, remove_pushpopbot_from_tweet(text))

    def should_post_tweet(self):
        return len(self.timeline) > 0

    def in_reply_to_status_id(self):
        return self.tweet.id

    def update_local_timeline(self, result):
        if result:  # TODO: if result is not an error...
            self.timeline.pop()

    def target_tweet(self):
        return self.timeline[len(self.timeline)-1]

    def delete_most_recent_tweet(self, tweet):
        if tweet:
            return api.destroy_status(self.target_tweet().id)

    def perform_action(self):
        tweet = self.post_tweet()
        remove_successful = self.delete_most_recent_tweet(tweet)
        self.update_local_timeline(remove_successful)
        if remove_successful:
            housekeeping.set('runtimes', 'last_processed_tweet', str(self.tweet.id))
            hk_file = open('housekeeping.ini', 'w')
            housekeeping.write(hk_file)
            hk_file.close()


# here's where all da fun stuff starts
last_processed_tweet = housekeeping.get('runtimes', 'last_processed_tweet')
if len(last_processed_tweet):
    last_processed_tweet = int(last_processed_tweet)
else:
    last_processed_tweet = None

# create actions array
mentions = api.mentions_timeline(since_id=last_processed_tweet)[::-1]
user_timeline = list(api.user_timeline())  # all actions will have a reference to this list so they can mutate it.
user_timeline = [s for s in user_timeline if not s.in_reply_to_status_id]  # filter out replies
actions = []
for mention in mentions:
    text = remove_pushpopbot_from_tweet(mention.text)

    is_a_push = text[:Push.identifier_len] == Push.identifier
    is_a_pop = text[:Pop.identifier_len] == Pop.identifier

    if is_a_push:
        push = Push(tweet=mention, timeline=user_timeline)
        actions.append(push)
    elif is_a_pop:
        pop = Pop(tweet=mention, timeline=user_timeline)
        actions.append(pop)

# execute each action (i.e., tweet & delete!)
for action in actions:
    action.perform_action()
