#!/usr/bin/env python3

from datetime import datetime, timedelta
import itertools
import json
import os
import re
import sys
import requests
import time

def pull_context(
    server,
    access_token,
    seen_urls,
    replied_toot_server_ids,
    reply_interval_hours,
    max_home_timeline_length,
):
    
    parsed_urls = {}

    if reply_interval_hours > 0:
        """pull the context toots of toots user replied to, from their
        original server, and add them to the local server."""
        user_ids = get_active_user_ids(server, access_token, reply_interval_hours)
        reply_toots = get_all_reply_toots(
            server, user_ids, access_token, seen_urls, reply_interval_hours
        )
        known_context_urls = get_all_known_context_urls(server, reply_toots,parsed_urls)
        seen_urls.update(known_context_urls)
        replied_toot_ids = get_all_replied_toot_server_ids(
            server, reply_toots, replied_toot_server_ids, parsed_urls
        )
        context_urls = get_all_context_urls(server, replied_toot_ids)
        add_context_urls(server, access_token, context_urls, seen_urls)


    if max_home_timeline_length > 0:
        """Do the same with any toots on the key owner's home timeline """
        timeline_toots = get_timeline(server, access_token, max_home_timeline_length)
        known_context_urls = get_all_known_context_urls(server, timeline_toots,parsed_urls)
        add_context_urls(server, access_token, known_context_urls, seen_urls)

def get_timeline(server, access_token, max):
    """Get all post in the user's home timeline"""

    url = f"https://{server}/api/v1/timelines/home"

    try:
    
        response = get_toots(url, access_token)

        if response.status_code == 200:
            toots = response.json()
        elif response.status_code == 401:
            raise Exception(
                f"Error getting URL {url}. Status code: {response.status_code}. "
                "Ensure your access token is correct"
            )
        elif response.status_code == 403:
            raise Exception(
                f"Error getting URL {url}. Status code: {response.status_code}. "
                "Make sure you have the read:statuses scope enabled for your access token."
            )
        else:
            raise Exception(
                f"Error getting URL {url}. Status code: {response.status_code}"
            )

        # Paginate as needed
        while len(toots) < max and 'next' in response.links:
            response = get_toots(response.links['next']['url'], access_token)
            toots = toots + response.json()
    except Exception as ex:
        print(f"Error getting timeline toots: {ex}")
        sys.exit(1)

    print(f"Found {len(toots)} toots in timeline")

    return toots
    
def get_toots(url, access_token):
    response = requests.get(
        url, headers={
            "Authorization": f"Bearer {access_token}",
            'User-Agent': 'mastodon_get_replies (https://go.thms.uk/mgr)'
        }, timeout=5
    )

    if response.status_code == 200:
        return response
    elif response.status_code == 401:
        raise Exception(
            f"Error getting URL {url}. Status code: {response.status_code}. "
            "It looks like your access token is incorrect."
        )
    elif response.status_code == 403:
        raise Exception(
            f"Error getting URL {url}. Status code: {response.status_code}. "
            "Make sure you have the read:statuses scope enabled for your access token."
        )
    else:
        raise Exception(
            f"Error getting URL {url}. Status code: {response.status_code}"
        )
    
def get_active_user_ids(server, access_token, reply_interval_hours):
    """get all user IDs on the server that have posted a toot in the given
       time interval"""
    since = datetime.now() - timedelta(days=reply_interval_hours / 24 + 1)
    url = f"https://{server}/api/v1/admin/accounts"
    resp = requests.get(
        url, headers={
            "Authorization": f"Bearer {access_token}",
            'User-Agent': 'mastodon_get_replies (https://go.thms.uk/mgr)'
        }, timeout=5
    )
    if resp.status_code == 200:
        for user in resp.json():
            last_status_at = user["account"]["last_status_at"]
            if last_status_at is not None:
                last_active = datetime.strptime(last_status_at, "%Y-%m-%d")
                if last_active > since:
                    print(f"Found active user: {user['username']}")
                    yield user["id"]
    elif resp.status_code == 401:
        raise Exception(
            f"Error getting user IDs on server {server}. Status code: {resp.status_code}. "
            "Ensure your access token is correct"
        )
    elif resp.status_code == 403:
        raise Exception(
            f"Error getting user IDs on server {server}. Status code: {resp.status_code}. "
            "Make sure you have the admin:read:accounts scope enabled for your access token."
        )
    else:
        raise Exception(
            f"Error getting user IDs on server {server}. Status code: {resp.status_code}"
        )


def get_all_reply_toots(
    server, user_ids, access_token, seen_urls, reply_interval_hours
):
    """get all replies to other users by the given users in the last day"""
    replies_since = datetime.now() - timedelta(hours=reply_interval_hours)
    reply_toots = list(
        itertools.chain.from_iterable(
            get_reply_toots(
                user_id, server, access_token, seen_urls, replies_since
            )
            for user_id in user_ids
        )
    )
    print(f"Found {len(reply_toots)} reply toots")
    return reply_toots


def get_reply_toots(user_id, server, access_token, seen_urls, reply_since):
    """get replies by the user to other users since the given date"""
    url = f"https://{server}/api/v1/accounts/{user_id}/statuses?exclude_replies=false&limit=40"

    try:
        resp = requests.get(
            url, headers={
                "Authorization": f"Bearer {access_token}",
                'User-Agent': 'mastodon_get_replies (https://go.thms.uk/mgr)'
            }, timeout=5
        )
    except Exception as ex:
        print(
            f"Error getting replies for user {user_id} on server {server}: {ex}"
        )
        return []

    if resp.status_code == 200:
        toots = [
            toot
            for toot in resp.json()
            if toot["in_reply_to_id"] is not None
            and toot["url"] not in seen_urls
            and datetime.strptime(toot["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
            > reply_since
        ]
        for toot in toots:
            print(f"Found reply toot: {toot['url']}")
        return toots
    elif resp.status_code == 403:
        raise Exception(
            f"Error getting replies for user {user_id} on server {server}. Status code: {resp.status_code}. "
            "Make sure you have the read:statuses scope enabled for your access token."
        )

    raise Exception(
        f"Error getting replies for user {user_id} on server {server}. Status code: {resp.status_code}"
    )


def get_all_known_context_urls(server, reply_toots,parsed_urls):
    """get the context toots of the given toots from their original server"""
    known_context_urls = set(
        filter(
            lambda url: not url.startswith(f"https://{server}/"),
            itertools.chain.from_iterable(
                get_toot_context(*parse_url(toot["url"] if toot["reblog"] is None else toot["reblog"]["url"],parsed_urls), toot["url"])
                for toot in filter(
                    lambda toot: toot_has_parseable_url(toot,parsed_urls),
                    reply_toots
                )            
            ),
        )
    )
    print(f"Found {len(known_context_urls)} known context toots")
    return known_context_urls


def toot_has_parseable_url(toot,parsed_urls):
    parsed = parse_url(toot["url"] if toot["reblog"] is None else toot["reblog"]["url"],parsed_urls)
    if(parsed is None) :
        return False
    return True
                

def get_all_replied_toot_server_ids(
    server, reply_toots, replied_toot_server_ids, parsed_urls
):
    """get the server and ID of the toots the given toots replied to"""
    return filter(
        lambda x: x is not None,
        (
            get_replied_toot_server_id(server, toot, replied_toot_server_ids, parsed_urls)
            for toot in reply_toots
        ),
    )


def get_replied_toot_server_id(server, toot, replied_toot_server_ids,parsed_urls):
    """get the server and ID of the toot the given toot replied to"""
    in_reply_to_id = toot["in_reply_to_id"]
    in_reply_to_account_id = toot["in_reply_to_account_id"]
    mentions = toot["mentions"]
    if len(mentions) == 0:
        return None

    mention = [
        mention
        for mention in mentions
        if mention["id"] == in_reply_to_account_id
    ][0]

    o_url = f"https://{server}/@{mention['acct']}/{in_reply_to_id}"
    if o_url in replied_toot_server_ids:
        return replied_toot_server_ids[o_url]

    url = get_redirect_url(o_url)

    if url is None:
        return None

    match = parse_url(url,parsed_urls)
    if match is not None:
        replied_toot_server_ids[o_url] = (url, match)
        return (url, match)

    print(f"Error parsing toot URL {url}")
    replied_toot_server_ids[o_url] = None
    return None

def parse_url(url, parsed_urls):
    if url not in parsed_urls:
        match = parse_mastodon_url(url)
        if match is not None:
            parsed_urls[url] = match
    
    if url not in parsed_urls:
        match = parse_pleroma_url(url)
        if match is not None:
            parsed_urls[url] = match

    if url not in parsed_urls:
        print(f"Error parsing toot URL {url}")
        parsed_urls[url] = None
    
    return parsed_urls[url]

def parse_mastodon_url(url):
    """parse a Mastodon URL and return the server and ID"""
    match = re.match(
        r"https://(?P<server>.*)/@(?P<username>.*)/(?P<toot_id>.*)", url
    )
    if match is not None:
        return (match.group("server"), match.group("toot_id"))
    return None


def parse_pleroma_url(url):
    """parse a Pleroma URL and return the server and ID"""
    match = re.match(r"https://(?P<server>.*)/objects/(?P<toot_id>.*)", url)
    if match is not None:
        server = match.group("server")
        url = get_redirect_url(url)
        if url is None:
            return None
        
        match = re.match(r"/notice/(?P<toot_id>.*)", url)
        if match is not None:
            return (server, match.group("toot_id"))
        return None
    return None


def get_redirect_url(url):
    """get the URL given URL redirects to"""
    try:
        resp = requests.head(url, allow_redirects=False, timeout=5,headers={
            'User-Agent': 'mastodon_get_replies (https://go.thms.uk/mgr)'
        })
    except Exception as ex:
        print(f"Error getting redirect URL for URL {url}. Exception: {ex}")
        return None

    if resp.status_code == 200:
        return url
    elif resp.status_code == 302:
        redirect_url = resp.headers["Location"]
        print(f"Discovered redirect for URL {url}")
        return redirect_url
    else:
        print(
            f"Error getting redirect URL for URL {url}. Status code: {resp.status_code}"
        )
        return None


def get_all_context_urls(server, replied_toot_ids):
    """get the URLs of the context toots of the given toots"""
    return filter(
        lambda url: not url.startswith(f"https://{server}/"),
        itertools.chain.from_iterable(
            get_toot_context(server, toot_id, url)
            for (url, (server, toot_id)) in replied_toot_ids
        ),
    )


def get_toot_context(server, toot_id, toot_url):
    """get the URLs of the context toots of the given toot"""
    url = f"https://{server}/api/v1/statuses/{toot_id}/context"
    try:
        resp = requests.get(url, timeout=5,headers={
            'User-Agent': 'mastodon_get_replies (https://go.thms.uk/mgr)'
        })
    except Exception as ex:
        print(f"Error getting context for toot {toot_url}. Exception: {ex}")
        return []

    if resp.status_code == 200:
        try:
            res = resp.json()
            print(f"Got context for toot {toot_url}")
            return (toot["url"] for toot in (res["ancestors"] + res["descendants"]))
        except Exception as ex:
            print(f"Error parsing context for toot {toot_url}. Exception: {ex}")
        return []
    elif resp.status_code == 429:
        reset = datetime.strptime(resp.headers['x-ratelimit-reset'], '%Y-%m-%dT%H:%M:%S.%fZ')
        print(f"Rate Limit hit when getting context for {toot_url}. Waiting to retry at {resp.headers['x-ratelimit-reset']}")
        time.sleep((reset - datetime.now()).total_seconds() + 1)
        return get_toot_context(server, toot_id, toot_url)

    print(
        f"Error getting context for toot {toot_url}. Status code: {resp.status_code}"
    )
    return []


def add_context_urls(server, access_token, context_urls, seen_urls):
    """add the given toot URLs to the server"""
    count = 0
    failed = 0
    for url in context_urls:
        if url not in seen_urls:
            added = add_context_url(url, server, access_token)
            if added is True:
                seen_urls.add(url)
                count += 1
            else:
                failed += 1

    print(f"Added {count} new context toots (with {failed} failures)")


def add_context_url(url, server, access_token):
    """add the given toot URL to the server"""
    search_url = f"https://{server}/api/v2/search?q={url}&resolve=true&limit=1"

    try:
        resp = requests.get(
            search_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                'User-Agent': 'mastodon_get_replies (https://go.thms.uk/mgr)'
            },
            timeout=5,
        )
    except Exception as ex:
        print(
            f"Error adding url {search_url} to server {server}. Exception: {ex}"
        )
        return False

    if resp.status_code == 200:
        print(f"Added context url {url}")
        return True
    elif resp.status_code == 403:
        print(
            f"Error adding url {search_url} to server {server}. Status code: {resp.status_code}. "
            "Make sure you have the read:search scope enabled for your access token."
        )
        return False
    elif resp.status_code == 429:
        reset = datetime.strptime(resp.headers['x-ratelimit-reset'], '%Y-%m-%dT%H:%M:%S.%fZ')
        print(f"Rate Limit hit when adding url {search_url}. Waiting to retry at {resp.headers['x-ratelimit-reset']}")
        time.sleep((reset - datetime.now()).total_seconds() + 1)
        return add_context_url(url, server, access_token)
    else:
        print(
            f"Error adding url {search_url} to server {server}. Status code: {resp.status_code}"
        )
        return False


class OrderedSet:
    """An ordered set implementation over a dict"""

    def __init__(self, iterable):
        self._dict = {}
        for item in iterable:
            self.add(item)

    def add(self, item):
        if item not in self._dict:
            self._dict[item] = None

    def update(self, iterable):
        for item in iterable:
            self.add(item)

    def __contains__(self, item):
        return item in self._dict

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)


if __name__ == "__main__":
    HELP_MESSAGE = """
Usage: python3 pull_context.py <access_token> <server> <reply_interval_in_hours> <home_timeline_length>

 - <access_token>: The access token can be generated at https://<server>/settings/applications,
   and must have read:search, read:statuses and admin:read:accounts scopes.
 - <server>: The name of your server (e.g. `mstdn.thms.uk`)
 - <reply_interval_in_hours>: Only look at posts that have received replies in this period
 - <home_timeline_length>: Also look for replies to posts in the API-Key owner's home timeline, up to 
   this many posts


"""

   

    if len(sys.argv) < 5:
        print(HELP_MESSAGE)
        sys.exit(1)

    ACCESS_TOKEN = sys.argv[1]
    SERVER = sys.argv[2]
    REPLY_INTERVAL_IN_HOURS = int(sys.argv[3])
    MAX_HOME_TIMELINE_LENGTH = int(sys.argv[4])

    print(
        f"Getting last {REPLY_INTERVAL_IN_HOURS} hrs of replies, and latest {MAX_HOME_TIMELINE_LENGTH} posts in home timeline from {SERVER}"
    )

    SEEN_URLS_FILE = "artifacts/seen_urls"
    REPLIED_TOOT_SERVER_IDS_FILE = "artifacts/replied_toot_server_ids"


    SEEN_URLS = OrderedSet([])
    if os.path.exists(SEEN_URLS_FILE):
        with open(SEEN_URLS_FILE, "r", encoding="utf-8") as f:
            SEEN_URLS = OrderedSet(f.read().splitlines())

    REPLIED_TOOT_SERVER_IDS = {}
    if os.path.exists(REPLIED_TOOT_SERVER_IDS_FILE):
        with open(REPLIED_TOOT_SERVER_IDS_FILE, "r", encoding="utf-8") as f:
            REPLIED_TOOT_SERVER_IDS = json.load(f)

    pull_context(
        SERVER,
        ACCESS_TOKEN,
        SEEN_URLS,
        REPLIED_TOOT_SERVER_IDS,
        REPLY_INTERVAL_IN_HOURS,
        MAX_HOME_TIMELINE_LENGTH,
    )

    with open(SEEN_URLS_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(list(SEEN_URLS)[-10000:]))

    with open(REPLIED_TOOT_SERVER_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(list(REPLIED_TOOT_SERVER_IDS.items())[-10000:]), f)
