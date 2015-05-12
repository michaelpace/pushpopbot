"""
TODO-LIST:
- only update local timeline if twitter api request was a success
- use sqlite3 module instead of housekeeping.ini, and also to keep track of original authors of Pushes
    - class in charge of interacting w/ sqlite db
- unit tests (check various inputs w/ newlines, etc.; everything else)
- fab file
- travis ci
- at-mention the original pusher w/ the pop recipient? (perhaps as follow-up tweet so we don't have to worry about length limits); this will require more persistence between runs (i.e., more than just using bot's twitter timeline)
    - the follow-up tweet would be: "pushed ____ by @incrediblepasta" or something similar. maybe "via @incrediblepasta on ____", or "via @incrediblepasta, pushed ____"
- handle twitter throttling
- handle twitter not returning full results (e.g., if the mentions array hit some max limit, how would we know? or if the timeline returned wasn't the full timeline?)
"""


import tweepy
import ConfigParser
import re
import time
import logging


HTTP_FORBIDDEN = 403

BOT_NAME = '@pushpopbot'
MAXIMUM_TWEET_LENGTH = 140
SLEEP_TIME_SECONDS = 1

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


def get_logger(obj):
    logger = logging.getLogger('pushpopbot.%s.%s' % (__name__, obj.__class__))
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler('pushpopbot.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


class TwitterAction(object):
    """
    Abstract base class for interacting with Twitter.
    """
    def __init__(self, **kwargs):
        super(TwitterAction, self).__init__()

        self.status = None

        self._logger = get_logger(self)
        self._kwargs = kwargs

    def execute(self):
        # always sleep before performing an action in the hope that twitter doesn't rate-limit us
        time.sleep(SLEEP_TIME_SECONDS)
        return self._make_api_call(**self._kwargs)

    def _make_api_call(self, **kwargs):
        raise NotImplementedError()


class TwitterActionPost(TwitterAction):
    """
    Represents posting a new update to Twitter.

    Required kwargs when creating: status
    Optional kwargs when creating: in_reply_to_status_id
    """
    def _make_api_call(self, **kwargs):
        status = kwargs.get('status')
        if not status:
            raise Exception('Expected a status to post')
        in_reply_to_status_id = kwargs.get('in_reply_to_status_id')

        if len(status) > MAXIMUM_TWEET_LENGTH:
            self._logger.error('Desired status too long to post (%s characters).' % len(status))
            return

        try:
            return api.update_status(status=status, in_reply_to_status_id=in_reply_to_status_id)
        except tweepy.TweepError as e:
            raise e


class TwitterActionDelete(TwitterAction):
    """
    Represents deleting a tweet from Twitter.

    Required kwargs when creating: tweet_id
    """
    def _make_api_call(self, **kwargs):
        tweet_id = kwargs.get('tweet_id')
        if not tweet_id:
            raise Exception('Expected a tweet_id to delete')

        try:
            return api.destroy_status(tweet_id)
        except tweepy.TweepError as e:
            raise e


class TwitterActionRetrieveTimeline(TwitterAction):
    """
    Represents a retrieval of our bot's timeline.
    """
    def _make_api_call(self, **kwargs):
        self._logger.info('Getting user timeline...')
        return api.user_timeline()


class TwitterActionRetrieveMentions(TwitterAction):
    """
    Represents a retrieval of @ mentions to our bot.

    Optional kwargs when creating: tweet_id
    """
    def _make_api_call(self, **kwargs):
        self._logger.info('Getting user mentions...')

        since_id = kwargs.get('since_id')
        return api.mentions_timeline(since_id=since_id)


class PushPopBotAction(object):
    """
    Abstract base class for @pushpopbot's possible actions.

    Subclasses should override _setup_twitter_actions and _timeline_modifications.
    """
    def __init__(self, tweet):
        super(PushPopBotAction, self).__init__()

        self._logger = get_logger(self)
        self._tweet = tweet

    def execute(self):
        """
        Perform our action.
        """
        twitter_actions = self._setup_twitter_actions()
        self._perform_twitter_actions(twitter_actions)
        self._update_housekeeping()

        # TODO: only perform local modifications if our twitter actions succeeded
        return self._timeline_modifications()

    def _update_housekeeping(self):
        """
        Update our persistence store w/ the most recent tweet we've processed so we can run this job and pick up from
        where we left off.
        """
        # TODO: change this to be db code
        housekeeping.set('runtimes', 'last_processed_tweet', str(self._tweet.id))
        hk_file = open('housekeeping.ini', 'w')
        housekeeping.write(hk_file)
        hk_file.close()

    def _timeline_modifications(self):
        """
        Subclasses should override and return a function which takes in a list (which represents our local timeline) and
        manipulates it such that it stays in sync with Twitter's timeline.
        """
        raise NotImplementedError()

    def _setup_twitter_actions(self):
        """
        Subclasses should override and return a list of TwitterActions to be executed.
        """
        raise NotImplementedError()

    def _perform_twitter_actions(self, twitter_actions):
        """
        Execute each of our TwitterActions.
        """
        results = []
        for twitter_action in twitter_actions:
            try:
                results.append(twitter_action.execute())
            except Exception as e:
                self._logger.error(e)
        return results


class PushPopBotActionPush(PushPopBotAction):
    """
    Post a new status to Twitter and update our local timeline by appending one new tweet.
    """
    def __init__(self, tweet):
        super(PushPopBotActionPush, self).__init__(tweet)

        self._posted_tweet = None

    def _perform_twitter_actions(self, twitter_actions):
        # overriding from parent so we can stash the posted tweet for referring to later when modifying local timeline.
        results = super(PushPopBotActionPush, self)._perform_twitter_actions(twitter_actions)
        self._posted_tweet = results[0] if results else None

    def _setup_twitter_actions(self):
        status = remove_pushpopbot_from_tweet(self._tweet.text)
        return [TwitterActionPost(status=status)]

    def _timeline_modifications(self):
        def add_new_tweet_to_timeline(timeline):
            timeline.append(self._posted_tweet)

        return add_new_tweet_to_timeline


class PushPopBotActionPop(PushPopBotAction):
    """
    Post a @reply to Twitter and delete the timeline's most recent tweet.
    """
    def __init__(self, tweet, timeline):
        super(PushPopBotActionPop, self).__init__(tweet)

        # store a reference to the timeline. it could be empty at this point, but later on when we reference it it may
        # have an element which we can pop.
        self._timeline = timeline

    def _setup_twitter_actions(self):
        target_tweet = self._timeline[len(self._timeline)-1] if len(self._timeline) > 0 else None

        if not target_tweet:
            self._logger.warning('No tweet to pop; skipping that pop')
            return []

        author = '@' + self._tweet.author.screen_name
        status = '%s %s' % (author, remove_pushpopbot_from_tweet(target_tweet.text))
        return [
            TwitterActionPost(status=status),
            TwitterActionDelete(tweet_id=target_tweet.id)
            # TODO: add another TwitterActionPost to do the follow-up tweet mentioning author and date
        ]

    def _timeline_modifications(self):
        def pop_most_recent_tweet_off_top_of_timeline(timeline):
            timeline.pop()

        return pop_most_recent_tweet_off_top_of_timeline


class PushPopBotRunner(object):
    """
    Mastermind behind the whole operation; responsible for running the bot.
    """
    pop_identifier = 'pop'

    def __init__(self):
        super(PushPopBotRunner, self).__init__()

        self._logger = get_logger(self)
        self._timeline = [s
                          for s
                          in TwitterActionRetrieveTimeline().execute()
                          if not s.in_reply_to_status_id]  # ignore tweets in our timeline that we've @'d to someone else

    def sanitize_tweet(self, text):
        """
        Strip @botname from text.
        :param text: String. Text of the tweet to be sanitized.
        :return: String. Input text minus @botname.
        """
        self._logger.info('About to sanitize tweet: %s' % text)
        return remove_pushpopbot_from_tweet(text)

    def is_a_pop(self, text):
        """
        Is the given text a pop?
        :param text: String. Text to be evaluated.
        :return: Boolean. Indicates whether input text is a pop or not (if not, implicitly it's a push).
        """
        len_pop_identifier = len(self.pop_identifier)

        if len(text) < len_pop_identifier:
            # "po"
            return False

        # we want to accept "pop", "pop dude!", etc. but not "popsicle"
        if text[:len_pop_identifier] == self.pop_identifier:
            if len(text) == len_pop_identifier:
                # "pop"
                return True

            assert len(text) > len_pop_identifier
            next_char = text[len_pop_identifier]
            if next_char.isalpha():
                # "popsicle"
                return False

            # "pop!"
            return True

        # "lol, pop"
        return False

    def run(self):
        """
        Run dis whole thang.
        :return: NADA
        """
        self._logger.info('Running!')

        # TODO: replace with calls to db class
        since_id = housekeeping.get('runtimes', 'last_processed_tweet')
        since_id = int(since_id) if since_id else None
        self._logger.info('Last processed tweet: %s' % since_id)

        # reverse the mentions so we're iterating through them chronologically
        mentions = TwitterActionRetrieveMentions(since_id=since_id).execute()[::-1]

        push_pop_actions = []
        for mention in mentions:
            text = self.sanitize_tweet(mention.text)

            if self.is_a_pop(text):
                pop = PushPopBotActionPop(mention, self._timeline)
                push_pop_actions.append(pop)
            else:
                push = PushPopBotActionPush(mention)
                push_pop_actions.append(push)

        for action in push_pop_actions:
            modify_timeline = action.execute()
            modify_timeline(self._timeline)

        self._logger.info('Done!')


def main():
    PushPopBotRunner().run()


if __name__ == '__main__':
    main()
